#!/usr/bin/env python3
"""Tailnet-only power controller for the Windows gaming PC.

The HTTP listener is deliberately restricted to loopback. Tailscale Serve is
the only supported frontend and supplies the authenticated user identity used
for human actions. A separate random bearer token is used only by Sunshine's
start/stop callbacks on the gaming PC.
"""

from __future__ import annotations

import argparse
import hmac
import html
import ipaddress
import json
import os
import re
import secrets
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


_MAC_RE = re.compile(r"^(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")
_USER_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
_TAILSCALE_V4 = ipaddress.ip_network("100.64.0.0/10")


class ConfigError(ValueError):
    """Raised when the controller configuration is unsafe or incomplete."""


def _positive_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise ConfigError(f"{name} must be between {minimum} and {maximum}")
    return value


@dataclass(frozen=True)
class Config:
    mac: bytes
    mac_text: str
    broadcast: str
    wol_port: int
    pc_ip: str
    sunshine_port: int
    ssh_port: int
    ssh_user: str
    ssh_key: Path
    known_hosts: Path
    allowed_logins: frozenset[str]
    session_token: str
    idle_timeout: int
    wake_timeout: int
    poll_interval: int
    state_file: Path
    bind_host: str
    bind_port: int

    @classmethod
    def from_environment(cls) -> "Config":
        mac_text = os.getenv("GAMING_PC_MAC", "").strip().replace("-", ":")
        if not _MAC_RE.fullmatch(mac_text):
            raise ConfigError("GAMING_PC_MAC must contain six hexadecimal octets")
        mac = bytes.fromhex(mac_text.replace(":", ""))
        if mac in {b"\x00" * 6, b"\xff" * 6} or mac[0] & 1:
            raise ConfigError("GAMING_PC_MAC must be a unicast hardware address")

        broadcast = os.getenv("GAMING_PC_BROADCAST", "").strip()
        try:
            broadcast_ip = ipaddress.IPv4Address(broadcast)
        except ipaddress.AddressValueError as exc:
            raise ConfigError("GAMING_PC_BROADCAST must be an IPv4 address") from exc
        if not broadcast_ip.is_private:
            raise ConfigError("GAMING_PC_BROADCAST must belong to a private LAN")

        pc_ip = os.getenv("GAMING_PC_TAILSCALE_IP", "").strip()
        try:
            parsed_pc_ip = ipaddress.IPv4Address(pc_ip)
        except ipaddress.AddressValueError as exc:
            raise ConfigError("GAMING_PC_TAILSCALE_IP must be an IPv4 address") from exc
        if parsed_pc_ip not in _TAILSCALE_V4:
            raise ConfigError("GAMING_PC_TAILSCALE_IP must be inside 100.64.0.0/10")

        ssh_user = os.getenv("GAMING_PC_SSH_USER", "gaming").strip()
        if not _USER_RE.fullmatch(ssh_user):
            raise ConfigError("GAMING_PC_SSH_USER contains unsupported characters")

        allowed_logins = frozenset(
            value.strip().lower()
            for value in os.getenv("GAMING_ALLOWED_TAILSCALE_LOGINS", "").split(",")
            if value.strip()
        )
        if not allowed_logins:
            raise ConfigError("GAMING_ALLOWED_TAILSCALE_LOGINS cannot be empty")

        ssh_key = Path(
            os.getenv(
                "GAMING_PC_SSH_KEY",
                "/etc/raspberry-server/gaming/id_ed25519",
            )
        )
        known_hosts = Path(
            os.getenv(
                "GAMING_PC_KNOWN_HOSTS",
                "/etc/raspberry-server/gaming/known_hosts",
            )
        )
        token_file = Path(
            os.getenv(
                "GAMING_SESSION_TOKEN_FILE",
                "/etc/raspberry-server/gaming/session-token",
            )
        )
        for name, path in (
            ("GAMING_PC_SSH_KEY", ssh_key),
            ("GAMING_PC_KNOWN_HOSTS", known_hosts),
            ("GAMING_SESSION_TOKEN_FILE", token_file),
        ):
            if not path.is_file():
                raise ConfigError(f"{name} does not point to a readable file: {path}")
        try:
            session_token = token_file.read_text(encoding="ascii").strip()
        except OSError as exc:
            raise ConfigError(f"cannot read {token_file}") from exc
        if len(session_token) < 32 or not re.fullmatch(r"[A-Za-z0-9_-]+", session_token):
            raise ConfigError("the session token is too short or malformed")

        bind_host = os.getenv("GAMING_CONTROLLER_BIND", "127.0.0.1").strip()
        if bind_host != "127.0.0.1":
            raise ConfigError("GAMING_CONTROLLER_BIND must be 127.0.0.1")

        return cls(
            mac=mac,
            mac_text=mac_text.lower(),
            broadcast=str(broadcast_ip),
            wol_port=_positive_int("GAMING_PC_WOL_PORT", 9, 1, 65535),
            pc_ip=str(parsed_pc_ip),
            sunshine_port=_positive_int(
                "GAMING_PC_SUNSHINE_PORT", 47984, 1, 65535
            ),
            ssh_port=_positive_int("GAMING_PC_SSH_PORT", 22, 1, 65535),
            ssh_user=ssh_user,
            ssh_key=ssh_key,
            known_hosts=known_hosts,
            allowed_logins=allowed_logins,
            session_token=session_token,
            idle_timeout=_positive_int(
                "GAMING_IDLE_TIMEOUT_SECONDS", 1800, 300, 86400
            ),
            wake_timeout=_positive_int(
                "GAMING_WAKE_TIMEOUT_SECONDS", 180, 30, 900
            ),
            poll_interval=_positive_int(
                "GAMING_POLL_INTERVAL_SECONDS", 5, 2, 60
            ),
            state_file=Path(
                os.getenv(
                    "GAMING_CONTROLLER_STATE_FILE",
                    "/var/lib/raspberry-server/gaming-controller/state.json",
                )
            ),
            bind_host=bind_host,
            bind_port=_positive_int("GAMING_CONTROLLER_PORT", 8084, 1024, 65535),
        )


class State:
    DEFAULT = {
        "managed_power": False,
        "ready_seen": False,
        "session_active": False,
        "idle_since": None,
        "operation": None,
        "operation_started": None,
        "last_error": None,
        "last_wake": None,
        "last_shutdown": None,
    }

    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = threading.RLock()
        self.data = dict(self.DEFAULT)
        try:
            stored = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(stored, dict):
                self.data.update(
                    {key: stored[key] for key in self.DEFAULT if key in stored}
                )
        except (OSError, json.JSONDecodeError):
            pass

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(self.data, separators=(",", ":")), encoding="utf-8"
        )
        os.replace(temporary, self.path)


def _tcp_reachable(host: str, port: int, timeout: float = 0.8) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


class Controller:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.state = State(config.state_file)
        self.csrf_token = secrets.token_urlsafe(32)
        self._stop = threading.Event()
        self._worker = threading.Thread(target=self._monitor_loop, daemon=True)

    def start(self) -> None:
        self.observe()
        self._worker.start()

    def stop(self) -> None:
        self._stop.set()
        self._worker.join(timeout=2)

    def _monitor_loop(self) -> None:
        while not self._stop.wait(self.config.poll_interval):
            try:
                snapshot = self.observe()
                if (
                    snapshot["managed_power"]
                    and snapshot["ready"]
                    and not snapshot["session_active"]
                    and snapshot["idle_remaining_seconds"] == 0
                    and snapshot["operation"] is None
                ):
                    self.shutdown("idle-timeout")
            except Exception as exc:  # pragma: no cover - service safety net
                self._record_error(f"monitor error: {type(exc).__name__}")

    def _record_error(self, message: str) -> None:
        with self.state.lock:
            self.state.data["last_error"] = message[:300]
            self.state.data["operation"] = None
            self.state.data["operation_started"] = None
            self.state.save()

    def observe(self) -> dict[str, object]:
        ready = _tcp_reachable(self.config.pc_ip, self.config.sunshine_port)
        online = ready or _tcp_reachable(self.config.pc_ip, self.config.ssh_port)
        now = int(time.time())
        with self.state.lock:
            data = self.state.data
            previous = dict(data)
            operation = data["operation"]
            operation_started = int(data["operation_started"] or now)

            if ready:
                data["ready_seen"] = True
                if operation == "waking":
                    data["operation"] = None
                    data["operation_started"] = None
                data["last_error"] = None
                if data["managed_power"] and not data["session_active"]:
                    data["idle_since"] = data["idle_since"] or now
            elif operation == "waking" and now - operation_started >= self.config.wake_timeout:
                data["operation"] = None
                data["operation_started"] = None
                data["managed_power"] = False
                data["last_error"] = "Timeout: Sunshine non è diventato disponibile."

            if (
                online
                and operation == "shutting_down"
                and now - operation_started >= self.config.wake_timeout
            ):
                data["operation"] = None
                data["operation_started"] = None
                data["last_error"] = "Timeout: Windows non si è spento."

            if not online and (data["ready_seen"] or operation == "shutting_down"):
                # A machine that was observed ready and is now offline completed
                # a shutdown (requested here or performed locally).
                data.update(
                    {
                        "managed_power": False,
                        "ready_seen": False,
                        "session_active": False,
                        "idle_since": None,
                        "operation": None,
                        "operation_started": None,
                    }
                )

            idle_remaining: int | None = None
            if (
                data["managed_power"]
                and ready
                and not data["session_active"]
                and data["idle_since"] is not None
            ):
                elapsed = max(0, now - int(data["idle_since"]))
                idle_remaining = max(0, self.config.idle_timeout - elapsed)

            operation = data["operation"]
            if operation == "waking":
                power = "waking"
                label = "Accensione in corso"
            elif operation == "shutting_down":
                power = "shutting_down"
                label = "Spegnimento in corso"
            elif ready:
                power = "ready"
                label = "Pronto per Moonlight"
            elif online:
                power = "online"
                label = "Windows online, Sunshine non pronto"
            else:
                power = "off"
                label = "Spento"

            if data != previous:
                self.state.save()
            return {
                "power": power,
                "label": label,
                "online": online,
                "ready": ready,
                "managed_power": bool(data["managed_power"]),
                "session_active": bool(data["session_active"]),
                "idle_remaining_seconds": idle_remaining,
                "idle_timeout_seconds": self.config.idle_timeout,
                "operation": operation,
                "last_error": data["last_error"],
                "last_wake": data["last_wake"],
                "last_shutdown": data["last_shutdown"],
            }

    def wake(self, actor: str) -> None:
        snapshot = self.observe()
        if snapshot["online"]:
            return
        now = int(time.time())
        with self.state.lock:
            if self.state.data["operation"] is not None:
                return
            self.state.data.update(
                {
                    "managed_power": True,
                    "ready_seen": False,
                    "session_active": False,
                    "idle_since": None,
                    "operation": "waking",
                    "operation_started": now,
                    "last_error": None,
                    "last_wake": now,
                }
            )
            self.state.save()
        packet = b"\xff" * 6 + self.config.mac * 16
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                for _ in range(3):
                    sock.sendto(packet, (self.config.broadcast, self.config.wol_port))
                    time.sleep(0.15)
            print(f"wake requested by {actor}", flush=True)
        except OSError as exc:
            self._record_error(f"Wake-on-LAN fallito: {exc}")
            raise

    def shutdown(self, actor: str) -> None:
        snapshot = self.observe()
        if not snapshot["online"]:
            with self.state.lock:
                self.state.data.update(
                    {
                        "managed_power": False,
                        "ready_seen": False,
                        "session_active": False,
                        "idle_since": None,
                        "operation": None,
                        "operation_started": None,
                    }
                )
                self.state.save()
            return
        now = int(time.time())
        with self.state.lock:
            if self.state.data["operation"] is not None:
                return
            self.state.data.update(
                {
                    "operation": "shutting_down",
                    "operation_started": now,
                    "last_error": None,
                    "last_shutdown": now,
                }
            )
            self.state.save()
        command = [
            "/usr/bin/ssh",
            "-T",
            "-p",
            str(self.config.ssh_port),
            "-i",
            str(self.config.ssh_key),
            "-o",
            "BatchMode=yes",
            "-o",
            "IdentitiesOnly=yes",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            f"UserKnownHostsFile={self.config.known_hosts}",
            "-o",
            "ClearAllForwardings=yes",
            "-o",
            "PermitLocalCommand=no",
            "-o",
            "ConnectTimeout=8",
            f"{self.config.ssh_user}@{self.config.pc_ip}",
            "shutdown",
        ]
        try:
            completed = subprocess.run(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=20,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            self._record_error(f"Comando di spegnimento fallito: {type(exc).__name__}")
            raise RuntimeError("shutdown command failed") from exc
        if completed.returncode != 0:
            detail = completed.stderr.strip().splitlines()
            reason = detail[-1][:160] if detail else f"SSH exit {completed.returncode}"
            self._record_error(f"Comando di spegnimento rifiutato: {reason}")
            raise RuntimeError("shutdown command rejected")
        print(f"shutdown requested by {actor}", flush=True)

    def session(self, active: bool) -> None:
        now = int(time.time())
        with self.state.lock:
            self.state.data["session_active"] = active
            self.state.data["idle_since"] = None if active else (
                now if self.state.data["managed_power"] else None
            )
            self.state.save()
        print(f"Sunshine session {'started' if active else 'stopped'}", flush=True)

    def postpone(self) -> None:
        with self.state.lock:
            if self.state.data["managed_power"] and not self.state.data["session_active"]:
                self.state.data["idle_since"] = int(time.time())
                self.state.save()


STYLE = b"""
:root{color-scheme:dark;font-family:Inter,system-ui,sans-serif;background:#0f172a;color:#e2e8f0}
body{margin:0;min-height:100vh;display:grid;place-items:center;padding:20px;box-sizing:border-box}
main{width:min(620px,100%);background:#172033;border:1px solid #334155;border-radius:20px;padding:28px;box-shadow:0 20px 50px #0006}
h1{margin:0 0 6px;font-size:1.6rem}.muted{color:#94a3b8;margin:0 0 24px}
.status{display:flex;align-items:center;gap:12px;background:#0f172a;border-radius:14px;padding:18px;margin-bottom:18px}
.dot{width:13px;height:13px;border-radius:50%;background:#64748b;box-shadow:0 0 16px currentColor}
.ready .dot{background:#22c55e}.waking .dot,.shutting_down .dot{background:#f59e0b}.online .dot{background:#38bdf8}.error .dot{background:#ef4444}
.label{font-weight:700}.detail{font-size:.9rem;color:#94a3b8;margin-top:4px}
.actions{display:grid;grid-template-columns:1fr 1fr;gap:12px}
button{border:0;border-radius:12px;padding:14px;font-weight:700;cursor:pointer;background:#2563eb;color:white}
button.danger{background:#b91c1c}button.secondary{grid-column:1/-1;background:#334155}
button:disabled{opacity:.38;cursor:not-allowed}.error-text{color:#fca5a5;min-height:1.4em;margin:16px 0 0}
@media(max-width:480px){main{padding:20px}.actions{grid-template-columns:1fr}button.secondary{grid-column:auto}}
"""


SCRIPT = r"""
const csrf=document.querySelector('meta[name="csrf-token"]').content;
const statusBox=document.getElementById('status');
const label=document.getElementById('label');
const detail=document.getElementById('detail');
const errorText=document.getElementById('error');
const wake=document.getElementById('wake');
const shutdown=document.getElementById('shutdown');
const postpone=document.getElementById('postpone');
function duration(value){if(value===null)return '';const m=Math.ceil(value/60);return `Spegnimento automatico tra ${m} min`;}
async function refresh(){
  try{const response=await fetch('/api/status',{cache:'no-store'});if(!response.ok)throw new Error(`HTTP ${response.status}`);
    const data=await response.json();statusBox.className=`status ${data.last_error?'error':data.power}`;
    label.textContent=data.label;detail.textContent=data.session_active?'Sessione Moonlight attiva':duration(data.idle_remaining_seconds)||(data.managed_power?'Acceso dal controller':'Avvio non gestito dal controller');
    errorText.textContent=data.last_error||'';wake.disabled=data.online||data.operation!==null;shutdown.disabled=!data.online||data.operation!==null;postpone.disabled=data.idle_remaining_seconds===null||data.operation!==null;
  }catch(error){statusBox.className='status error';label.textContent='Controller non raggiungibile';detail.textContent='';errorText.textContent=error.message;wake.disabled=shutdown.disabled=postpone.disabled=true;}}
async function action(path){const response=await fetch(path,{method:'POST',headers:{'X-CSRF-Token':csrf}});if(!response.ok){const data=await response.json().catch(()=>({error:`HTTP ${response.status}`}));throw new Error(data.error||`HTTP ${response.status}`);}await refresh();}
wake.addEventListener('click',()=>action('/api/wake').catch(e=>errorText.textContent=e.message));
shutdown.addEventListener('click',()=>{if(confirm('Spegnere il PC gaming? Windows conceder\u00e0 60 secondi per annullare localmente.'))action('/api/shutdown').catch(e=>errorText.textContent=e.message);});
postpone.addEventListener('click',()=>action('/api/postpone').catch(e=>errorText.textContent=e.message));
refresh();setInterval(refresh,3000);
""".encode("ascii")


def _page(csrf_token: str, login: str) -> bytes:
    return f"""<!doctype html>
<html lang="it"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="csrf-token" content="{html.escape(csrf_token, quote=True)}"><title>Gaming PC</title><link rel="stylesheet" href="/style.css"></head>
<body><main><h1>Gaming PC</h1><p class="muted">Controllo privato · {html.escape(login)}</p>
<section id="status" class="status"><span class="dot"></span><div><div id="label" class="label">Verifica in corso</div><div id="detail" class="detail"></div></div></section>
<div class="actions"><button id="wake">Accendi</button><button id="shutdown" class="danger">Spegni</button><button id="postpone" class="secondary">Rimanda di 30 minuti</button></div>
<p id="error" class="error-text" role="alert"></p></main><script src="/app.js" defer></script></body></html>""".encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    controller: Controller

    def _human_login(self) -> str | None:
        login = (self.headers.get("Tailscale-User-Login") or "").strip().lower()
        return login if login in self.controller.config.allowed_logins else None

    def _machine_authorized(self) -> bool:
        authorization = self.headers.get("Authorization", "")
        expected = f"Bearer {self.controller.config.session_token}"
        return hmac.compare_digest(authorization, expected)

    def _security_headers(self, content_type: str, length: int) -> None:
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", "default-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")

    def _bytes(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self._security_headers(content_type, len(body))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, payload: dict[str, object]) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self._bytes(status, body, "application/json; charset=utf-8")

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        path = urlparse(self.path).path
        if path == "/health":
            self._json(200, {"status": "ok"})
            return
        login = self._human_login()
        if login is None:
            self._json(401, {"error": "Identità Tailscale non autorizzata"})
            return
        if path == "/":
            self._bytes(200, _page(self.controller.csrf_token, login), "text/html; charset=utf-8")
        elif path == "/style.css":
            self._bytes(200, STYLE, "text/css; charset=utf-8")
        elif path == "/app.js":
            self._bytes(200, SCRIPT, "text/javascript; charset=utf-8")
        elif path == "/api/status":
            self._json(200, self.controller.observe())
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        path = urlparse(self.path).path
        if int(self.headers.get("Content-Length", "0") or "0") > 1024:
            self._json(413, {"error": "request too large"})
            return

        if path in {"/api/session/start", "/api/session/stop"}:
            if not self._machine_authorized():
                self._json(401, {"error": "invalid session token"})
                return
            self.controller.session(path.endswith("/start"))
            self._json(200, {"status": "ok"})
            return

        login = self._human_login()
        if login is None:
            self._json(401, {"error": "Identità Tailscale non autorizzata"})
            return
        if not hmac.compare_digest(
            self.headers.get("X-CSRF-Token", ""), self.controller.csrf_token
        ):
            self._json(403, {"error": "Token CSRF non valido"})
            return
        try:
            if path == "/api/wake":
                self.controller.wake(login)
            elif path == "/api/shutdown":
                threading.Thread(
                    target=self._shutdown_background, args=(login,), daemon=True
                ).start()
            elif path == "/api/postpone":
                self.controller.postpone()
            else:
                self._json(404, {"error": "not found"})
                return
        except (OSError, RuntimeError) as exc:
            self._json(502, {"error": str(exc)})
            return
        self._json(202, {"status": "accepted"})

    def _shutdown_background(self, login: str) -> None:
        try:
            self.controller.shutdown(login)
        except RuntimeError:
            pass

    def log_message(self, format: str, *args: object) -> None:
        return


def _load_environment_file(path: Path) -> None:
    for number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
            raise ConfigError(f"invalid environment entry at line {number}")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        os.environ[key] = value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-config", type=Path)
    args = parser.parse_args()
    try:
        if args.check_config:
            _load_environment_file(args.check_config)
        config = Config.from_environment()
    except (ConfigError, OSError) as exc:
        print(f"gaming controller configuration error: {exc}", file=sys.stderr)
        return 2
    if args.check_config:
        print("Gaming controller configuration is valid.")
        return 0

    controller = Controller(config)
    Handler.controller = controller
    server = ThreadingHTTPServer((config.bind_host, config.bind_port), Handler)
    controller.start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        controller.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
