#!/usr/bin/env python3
"""Root-side allowlisted operations gateway for the local AI Ops workflow.

The service listens only on a Unix socket. It never accepts shell strings,
filesystem paths or model-generated patches: each operation is converted to a
fixed argv list only after policy validation and Telegram approval.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import socketserver
import subprocess
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


STACK_DIR = Path(os.getenv("AI_OPS_STACK_DIR", "/opt/raspberry-server")).resolve()
POLICY_FILE = Path(
    os.getenv("AI_OPS_POLICY_FILE", str(STACK_DIR / "config/ai-ops/policy.json"))
).resolve()
STATE_DIR = Path(os.getenv("AI_OPS_STATE_DIR", "/var/lib/raspberry-server/ai-ops"))
TOKEN_FILE = Path(os.getenv("AI_OPS_TOKEN_FILE", "/etc/raspberry-server/ai-ops-token"))
APPROVAL_TOKEN_FILE = Path(
    os.getenv("AI_OPS_APPROVAL_TOKEN_FILE", "/etc/raspberry-server/ai-ops-approval-token")
)
SOCKET_PATH = Path(os.getenv("AI_OPS_SOCKET", "/run/piserver-ai-ops/gateway.sock"))

MAX_REQUEST_BYTES = 131_072
MAX_OUTPUT_CHARS = 4_000
_PLAN_ID = re.compile(r"^[a-f0-9]{12}$")
_SECRET_LINE = re.compile(
    r"(?i)(password|passwd|token|secret|api[_-]?key|authorization)"
    r"(\s*[=:]\s*|\s+)([^\s,;]+)"
)
_BEARER = re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+")


class ApiError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


POLICY = _load_json(POLICY_FILE)
API_TOKEN = TOKEN_FILE.read_text(encoding="utf-8").strip()
APPROVAL_API_TOKEN = APPROVAL_TOKEN_FILE.read_text(encoding="utf-8").strip()
if len(API_TOKEN) < 32 or len(APPROVAL_API_TOKEN) < 32:
    raise RuntimeError("AI Ops tokens must contain at least 32 characters")
PLAN_LOCK = threading.Lock()


def _redact(value: str) -> str:
    value = _BEARER.sub(r"\1[REDACTED]", value)
    value = _SECRET_LINE.sub(r"\1\2[REDACTED]", value)
    return value[:MAX_OUTPUT_CHARS]


def _run(argv: list[str], *, timeout: int = 60) -> dict[str, Any]:
    started = time.monotonic()
    try:
        result = subprocess.run(
            argv,
            cwd=str(STACK_DIR),
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "LC_ALL": "C.UTF-8", "LANG": "C.UTF-8"},
        )
        combined = "\n".join(part for part in (result.stdout, result.stderr) if part)
        return {
            "ok": result.returncode == 0,
            "exit_code": result.returncode,
            "duration_ms": round((time.monotonic() - started) * 1000),
            "output": _redact(combined.strip()),
        }
    except subprocess.TimeoutExpired as exc:
        output = "\n".join(
            part for part in (exc.stdout or "", exc.stderr or "") if isinstance(part, str)
        )
        return {
            "ok": False,
            "exit_code": None,
            "duration_ms": round((time.monotonic() - started) * 1000),
            "output": _redact(f"timeout after {timeout}s\n{output}".strip()),
        }
    except OSError as exc:
        return {
            "ok": False,
            "exit_code": None,
            "duration_ms": round((time.monotonic() - started) * 1000),
            "output": _redact(str(exc)),
        }


def _compose_argv(stack: str) -> list[str]:
    argv = [
        "docker", "compose", "--project-directory", str(STACK_DIR),
        "-f", str(STACK_DIR / "compose.yaml"),
    ]
    overlays = {
        "core": None,
        "media": "compose.media.yaml",
        "automation": "compose.automation.yaml",
    }
    if stack not in overlays:
        raise ApiError(400, "unknown compose stack")
    if overlays[stack]:
        argv.extend(["-f", str(STACK_DIR / str(overlays[stack]))])
    return argv


def _disk_summary(path: Path) -> dict[str, Any]:
    try:
        usage = shutil.disk_usage(path)
        return {
            "path": str(path),
            "total_bytes": usage.total,
            "used_bytes": usage.used,
            "free_bytes": usage.free,
            "used_percent": round(usage.used * 100 / usage.total, 1),
        }
    except OSError as exc:
        return {"path": str(path), "error": str(exc)}


def _diagnostic_sources() -> dict[str, Any]:
    sources: dict[str, Any] = {}
    total = 0
    for relative in POLICY["diagnostic_files"]:
        path = (STACK_DIR / relative).resolve()
        if not path.is_relative_to(STACK_DIR):
            sources[relative] = {"error": "path outside repository"}
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            sources[relative] = {"error": str(exc)}
            continue
        remaining = max(0, 12_000 - total)
        original_length = len(content)
        content = _redact(content[: min(4_000, remaining)])
        total += len(content)
        sources[relative] = {
            "content": content,
            "truncated": original_length > len(content),
        }
        if total >= 12_000:
            break
    return sources


def collect_diagnostics() -> dict[str, Any]:
    units: dict[str, Any] = {}
    for unit in POLICY["diagnostic_units"]:
        units[unit] = _run(
            [
                "systemctl", "show", unit, "--no-pager",
                "--property=ActiveState,SubState,Result,ExecMainStatus,StateChangeTimestamp",
            ],
            timeout=10,
        )

    compose: dict[str, Any] = {}
    for stack in ("core", "media", "automation"):
        compose[stack] = _run(_compose_argv(stack) + ["ps", "--format", "json"], timeout=20)

    return {
        "generated_at": int(time.time()),
        "privacy": {
            "model_location": "local Ollama container",
            "included": [
                "systemd state for explicitly listed units",
                "Docker Compose container state and health",
                "repository git status",
                "disk usage for the repository filesystem",
                "fixed versioned infrastructure configuration files",
            ],
            "excluded": [
                "application logs",
                ".env and credential files",
                "database contents",
                "Nextcloud files and all media directories",
                "Docker socket and arbitrary filesystem reads",
            ],
        },
        "policy": {
            "action_types": [
                "restart_systemd_unit",
                "restart_compose_service",
                "run_maintenance_task",
            ],
            "restartable_systemd_units": POLICY["restartable_systemd_units"],
            "restartable_compose_services": sorted(POLICY["restartable_compose_services"]),
            "maintenance_tasks": POLICY["maintenance_tasks"],
            "arbitrary_shell": False,
            "arbitrary_file_changes": False,
        },
        "systemd": units,
        "compose": compose,
        # Do not expose names of untracked local files to the model or Telegram.
        "git": _run(["git", "status", "--short", "--untracked-files=no"], timeout=10),
        "configuration_sources": _diagnostic_sources(),
        "disk": [_disk_summary(STACK_DIR)],
    }


def _required_string(value: Any, name: str, maximum: int = 8000) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ApiError(400, f"{name} must be a non-empty string")
    if len(value) > maximum:
        raise ApiError(400, f"{name} is too long")
    return value.strip()


def validate_action(raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict):
        raise ApiError(400, "each action must be an object")
    if set(raw) != {"type", "target", "rationale"}:
        raise ApiError(400, "action fields must be type, target and rationale")
    action_type = _required_string(raw["type"], "action.type", 64)
    target = _required_string(raw["target"], "action.target", 128)
    rationale = _required_string(raw["rationale"], "action.rationale", 2000)

    if action_type == "restart_systemd_unit":
        if target not in POLICY["restartable_systemd_units"]:
            raise ApiError(400, "systemd action is outside policy")
    elif action_type == "restart_compose_service":
        if target not in POLICY["restartable_compose_services"]:
            raise ApiError(400, "Compose service is outside policy")
    elif action_type == "run_maintenance_task":
        if target not in POLICY["maintenance_tasks"]:
            raise ApiError(400, "maintenance task is outside policy")
    else:
        raise ApiError(400, f"unsupported action type: {action_type}")
    return {"type": action_type, "target": target, "rationale": rationale}


def validate_plan(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ApiError(400, "plan must be a JSON object")
    expected = {"summary", "problem", "evidence", "actions", "risks", "verification"}
    if set(raw) != expected:
        raise ApiError(400, "invalid plan fields")
    actions_raw = raw["actions"]
    if not isinstance(actions_raw, list) or not actions_raw:
        raise ApiError(400, "an executable plan needs at least one action")
    if len(actions_raw) > int(POLICY["max_actions_per_plan"]):
        raise ApiError(400, "too many actions")
    for name in ("evidence", "risks", "verification"):
        value = raw[name]
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ApiError(400, f"{name} must be an array of strings")
        if len(value) > 12:
            raise ApiError(400, f"{name} contains too many items")
    return {
        "summary": _required_string(raw["summary"], "summary", 2000),
        "problem": _required_string(raw["problem"], "problem", 4000),
        "evidence": [item[:2000] for item in raw["evidence"]],
        "actions": [validate_action(action) for action in actions_raw],
        "risks": [item[:2000] for item in raw["risks"]],
        "verification": [item[:2000] for item in raw["verification"]],
    }


def _plan_path(plan_id: str) -> Path:
    if not _PLAN_ID.fullmatch(plan_id):
        raise ApiError(400, "invalid plan id")
    return STATE_DIR / f"{plan_id}.json"


def _write_plan(path: Path, plan: dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=STATE_DIR, delete=False
    ) as handle:
        json.dump(plan, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.chmod(0o600)
    temporary.replace(path)


def create_plan(raw: Any) -> dict[str, Any]:
    plan = validate_plan(raw)
    for _ in range(10):
        plan_id = secrets.token_hex(6)
        if not _plan_path(plan_id).exists():
            break
    else:
        raise ApiError(503, "could not allocate a plan id")
    approval_token = secrets.token_urlsafe(15)
    now = int(time.time())
    record = {
        **plan,
        "id": plan_id,
        "status": "pending",
        "created_at": now,
        "expires_at": now + int(POLICY["plan_ttl_seconds"]),
        "approval_token_sha256": hashlib.sha256(approval_token.encode()).hexdigest(),
        "results": [],
    }
    _write_plan(_plan_path(plan_id), record)
    return {
        "id": plan_id,
        "status": "pending",
        "expires_at": record["expires_at"],
        "approve_callback": f"aiok:{plan_id}:{approval_token}",
        "reject_callback": f"aino:{plan_id}:{approval_token}",
    }


def _verified_plan(plan_id: str, token: Any) -> tuple[Path, dict[str, Any]]:
    if not isinstance(token, str):
        raise ApiError(403, "approval token is required")
    path = _plan_path(plan_id)
    try:
        record = _load_json(path)
    except FileNotFoundError as exc:
        raise ApiError(404, "plan not found") from exc
    expected = str(record.get("approval_token_sha256", ""))
    actual = hashlib.sha256(token.encode()).hexdigest()
    if not hmac.compare_digest(actual, expected):
        raise ApiError(403, "invalid approval token")
    return path, record


def _authorized_plan(
    plan_id: str, token: Any, required_status: str = "pending"
) -> tuple[Path, dict[str, Any]]:
    path, record = _verified_plan(plan_id, token)
    if record.get("status") != required_status:
        raise ApiError(409, f"plan is already {record.get('status', 'closed')}")
    if int(record.get("expires_at", 0)) < int(time.time()):
        record["status"] = "expired"
        _write_plan(path, record)
        raise ApiError(410, "plan approval expired")
    return path, record


def approve_plan(plan_id: str, token: Any) -> dict[str, Any]:
    with PLAN_LOCK:
        path, record = _verified_plan(plan_id, token)
        if record.get("status") == "approved":
            if int(record.get("expires_at", 0)) < int(time.time()):
                record["status"] = "expired"
                _write_plan(path, record)
                raise ApiError(410, "plan approval expired")
            return {"id": plan_id, "status": "approved"}
        if record.get("status") != "pending":
            raise ApiError(409, f"plan is already {record.get('status', 'closed')}")
        if int(record.get("expires_at", 0)) < int(time.time()):
            record["status"] = "expired"
            _write_plan(path, record)
            raise ApiError(410, "plan approval expired")
        record["status"] = "approved"
        record["approved_at"] = int(time.time())
        _write_plan(path, record)
    return {"id": plan_id, "status": "approved"}


def execute_action(action: dict[str, str]) -> dict[str, Any]:
    action_type = action["type"]
    target = action["target"]
    if action_type == "restart_systemd_unit":
        result = _run(["systemctl", "restart", target], timeout=180)
    elif action_type == "restart_compose_service":
        stack = POLICY["restartable_compose_services"][target]
        result = _run(_compose_argv(stack) + ["restart", target], timeout=180)
    elif action_type == "run_maintenance_task":
        scripts = {
            "preflight": ["bash", str(STACK_DIR / "scripts/preflight.sh")],
            "recover-media-stack": ["systemctl", "start", "media-recovery.service"],
        }
        result = _run(scripts[target], timeout=300)
    else:  # validate_action prevents this path.
        raise ApiError(400, "unsupported action")
    return {
        "type": action_type,
        "target": target,
        "rationale": action["rationale"],
        **result,
    }


def execute_plan(plan_id: str, token: Any) -> dict[str, Any]:
    with PLAN_LOCK:
        path, record = _authorized_plan(plan_id, token, "approved")
        record["status"] = "executing"
        record["started_at"] = int(time.time())
        _write_plan(path, record)
    results: list[dict[str, Any]] = []
    for action in record["actions"]:
        try:
            result = execute_action(action)
        except Exception:
            result = {
                "type": action["type"],
                "target": action["target"],
                "rationale": action["rationale"],
                "ok": False,
                "exit_code": None,
                "duration_ms": 0,
                "output": "internal execution error",
            }
        results.append(result)
        if not result["ok"]:
            break
    record["results"] = results
    record["finished_at"] = int(time.time())
    record["status"] = "completed" if all(item["ok"] for item in results) else "failed"
    _write_plan(path, record)
    return {"id": plan_id, "status": record["status"], "results": results}


def cancel_plan(plan_id: str, token: Any) -> dict[str, Any]:
    with PLAN_LOCK:
        path, record = _authorized_plan(plan_id, token)
        record["status"] = "cancelled"
        record["finished_at"] = int(time.time())
        _write_plan(path, record)
    return {"id": plan_id, "status": "cancelled"}


class Handler(BaseHTTPRequestHandler):
    server_version = "PiServerAiOps/2"

    def do_GET(self) -> None:  # noqa: N802
        try:
            path = urlparse(self.path).path
            if path == "/v1/health":
                self._json(200, {"status": "ok"})
                return
            self._require_auth()
            if path == "/v1/diagnostics":
                self._json(200, collect_diagnostics())
                return
            self._json(404, {"error": "not found"})
        except ApiError as exc:
            self._json(exc.status, {"error": str(exc)})

    def do_POST(self) -> None:  # noqa: N802
        try:
            path = urlparse(self.path).path
            approval_match = re.fullmatch(r"/v1/plans/([a-f0-9]{12})/approve", path)
            if approval_match:
                self._require_approval_auth()
                body = self._body()
                self._json(
                    200,
                    approve_plan(approval_match.group(1), body.get("approval_token")),
                )
                return
            self._require_auth()
            body = self._body()
            if path == "/v1/plans":
                self._json(201, create_plan(body))
                return
            match = re.fullmatch(r"/v1/plans/([a-f0-9]{12})/(execute|cancel)", path)
            if match:
                if match.group(2) == "execute":
                    result = execute_plan(match.group(1), body.get("approval_token"))
                else:
                    result = cancel_plan(match.group(1), body.get("approval_token"))
                self._json(200, result)
                return
            self._json(404, {"error": "not found"})
        except ApiError as exc:
            self._json(exc.status, {"error": str(exc)})
        except Exception:
            self._json(500, {"error": "internal error"})

    def _require_auth(self) -> None:
        expected = f"Bearer {API_TOKEN}"
        if not hmac.compare_digest(self.headers.get("Authorization", ""), expected):
            raise ApiError(401, "unauthorized")

    def _require_approval_auth(self) -> None:
        expected = f"Bearer {APPROVAL_API_TOKEN}"
        if not hmac.compare_digest(self.headers.get("Authorization", ""), expected):
            raise ApiError(401, "approval authority required")

    def _body(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ApiError(400, "invalid content length") from exc
        if length <= 0 or length > MAX_REQUEST_BYTES:
            raise ApiError(413, "invalid request size")
        try:
            value = json.loads(self.rfile.read(length))
        except json.JSONDecodeError as exc:
            raise ApiError(400, "invalid JSON") from exc
        if not isinstance(value, dict):
            raise ApiError(400, "JSON body must be an object")
        return value

    def _json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return


if hasattr(socketserver, "UnixStreamServer"):
    class UnixHTTPServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):  # type: ignore[misc]
        daemon_threads = True
else:
    class UnixHTTPServer:  # pragma: no cover - Windows test-only fallback
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            raise RuntimeError("Unix domain sockets are required")


if __name__ == "__main__":
    STATE_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    SOCKET_PATH.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
    SOCKET_PATH.unlink(missing_ok=True)
    server = UnixHTTPServer(str(SOCKET_PATH), Handler)
    SOCKET_PATH.chmod(0o660)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        SOCKET_PATH.unlink(missing_ok=True)
