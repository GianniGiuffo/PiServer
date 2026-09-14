#!/usr/bin/env python3
"""Tailnet-only controller that keeps both Pi-hole blockers in sync."""

from __future__ import annotations

import json
import os
import secrets
import ssl
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class PiHole:
    name: str
    url: str
    password: str


@dataclass(frozen=True)
class Config:
    bind: str
    port: int
    allowed_logins: frozenset[str]
    allowed_origin: str
    nodes: tuple[PiHole, ...]

    @classmethod
    def from_environment(cls) -> "Config":
        bind = os.getenv("PIHOLE_CONTROL_BIND", "127.0.0.1").strip()
        if bind not in {"127.0.0.1", "::1", "localhost"}:
            raise ConfigError("PIHOLE_CONTROL_BIND must remain loopback-only")
        logins = frozenset(
            value.strip().lower()
            for value in os.environ.get(
                "PIHOLE_CONTROL_ALLOWED_TAILSCALE_LOGINS", ""
            ).split(",")
            if value.strip()
        )
        if not logins:
            raise ConfigError("set PIHOLE_CONTROL_ALLOWED_TAILSCALE_LOGINS")
        fqdn = os.environ.get("TAILSCALE_FQDN", "").strip()
        rack_fqdn = os.environ.get("RACK_PI_TAILSCALE_FQDN", "").strip()
        local_password = os.environ.get("MINIPC_PIHOLE_CONTROL_PASSWORD", "")
        rack_password = os.environ.get("RACK_PI_PIHOLE_CONTROL_PASSWORD", "")
        if not fqdn or not rack_fqdn or not local_password or not rack_password:
            raise ConfigError("Pi-hole endpoints and both API passwords are required")
        return cls(
            bind=bind,
            port=int(os.getenv("PIHOLE_CONTROL_PORT", "8085")),
            allowed_logins=logins,
            allowed_origin=f"https://{fqdn}",
            nodes=(
                PiHole("mini PC", "http://127.0.0.1:8081/api", local_password),
                PiHole("Raspberry", f"https://{rack_fqdn}:8444/api", rack_password),
            ),
        )


class PiHoleClient:
    def __init__(self, node: PiHole):
        self.node = node

    def _request(self, path: str, method: str = "GET", payload=None, sid=None):
        data = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            data = json.dumps(payload, separators=(",", ":")).encode()
            headers["Content-Type"] = "application/json"
        if sid:
            headers["X-FTL-SID"] = sid
        request = Request(f"{self.node.url}{path}", data=data, headers=headers, method=method)
        with urlopen(request, timeout=6, context=ssl.create_default_context()) as response:
            if response.status == 204:
                return {}
            return json.load(response)

    def _session(self) -> str:
        payload = self._request("/auth", "POST", {"password": self.node.password})
        sid = (payload.get("session") or {}).get("sid") if isinstance(payload, dict) else None
        if not sid:
            raise RuntimeError(f"autenticazione {self.node.name} fallita")
        return sid

    def blocking(self) -> bool:
        sid = self._session()
        try:
            payload = self._request("/dns/blocking", sid=sid)
            if not isinstance(payload, dict) or not isinstance(payload.get("blocking"), bool):
                raise RuntimeError(f"risposta non valida da {self.node.name}")
            return payload["blocking"]
        finally:
            try:
                self._request("/auth", "DELETE", sid=sid)
            except Exception:
                pass

    def set_blocking(self, enabled: bool) -> None:
        sid = self._session()
        try:
            self._request(
                "/dns/blocking", "POST", {"blocking": enabled, "timer": None}, sid
            )
        finally:
            try:
                self._request("/auth", "DELETE", sid=sid)
            except Exception:
                pass


class Controller:
    def __init__(self, config: Config):
        self.config = config
        self.csrf_token = secrets.token_urlsafe(32)
        self.lock = threading.Lock()

    def status(self) -> dict[str, object]:
        states = {node.name: PiHoleClient(node).blocking() for node in self.config.nodes}
        values = set(states.values())
        return {
            "blocking": values.pop() if len(values) == 1 else None,
            "nodes": states,
            "csrf": self.csrf_token,
        }

    def toggle(self) -> dict[str, object]:
        with self.lock:
            before = {node.name: PiHoleClient(node).blocking() for node in self.config.nodes}
            desired = not all(before.values())
            changed: list[PiHole] = []
            try:
                for node in self.config.nodes:
                    if before[node.name] != desired:
                        PiHoleClient(node).set_blocking(desired)
                        changed.append(node)
            except Exception:
                for node in reversed(changed):
                    try:
                        PiHoleClient(node).set_blocking(before[node.name])
                    except Exception:
                        pass
                raise
            return {"blocking": desired, "nodes": {node.name: desired for node in self.config.nodes}}


class Handler(BaseHTTPRequestHandler):
    controller: Controller

    def _identity_allowed(self) -> bool:
        login = self.headers.get("Tailscale-User-Login", "").strip().lower()
        return login in self.controller.config.allowed_logins

    def _origin_allowed(self) -> bool:
        return self.headers.get("Origin") == self.controller.config.allowed_origin

    def _cors(self) -> None:
        origin = self.headers.get("Origin")
        if origin == self.controller.config.allowed_origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")

    def _json(self, status: int, payload: dict[str, object]) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        self.send_response(status)
        self._cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:  # noqa: N802
        if not self._identity_allowed() or not self._origin_allowed():
            self._json(403, {"error": "accesso negato"})
            return
        self.send_response(204)
        self._cors()
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-CSRF-Token")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        if self.path != "/api/status":
            self._json(404, {"error": "not found"})
            return
        if not self._identity_allowed() or not self._origin_allowed():
            self._json(403, {"error": "accesso negato"})
            return
        try:
            self._json(200, self.controller.status())
        except (HTTPError, URLError, TimeoutError, OSError, RuntimeError, ValueError) as error:
            self._json(502, {"error": str(error)})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/api/toggle":
            self._json(404, {"error": "not found"})
            return
        if not self._identity_allowed() or not self._origin_allowed():
            self._json(403, {"error": "accesso negato"})
            return
        if self.headers.get("X-CSRF-Token") != self.controller.csrf_token:
            self._json(403, {"error": "token CSRF non valido"})
            return
        try:
            self._json(200, self.controller.toggle())
        except (HTTPError, URLError, TimeoutError, OSError, RuntimeError, ValueError) as error:
            self._json(502, {"error": str(error)})

    def log_message(self, format: str, *args: object) -> None:
        return


if __name__ == "__main__":
    config = Config.from_environment()
    Handler.controller = Controller(config)
    ThreadingHTTPServer((config.bind, config.port), Handler).serve_forever()
