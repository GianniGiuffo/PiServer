#!/usr/bin/env python3
"""Private Telegram bridge for the local-Ollama n8n AI Ops workflow."""

from __future__ import annotations

import hmac
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


BOT_TOKEN_FILE = Path(os.getenv("TELEGRAM_BOT_TOKEN_FILE", "/run/secrets/bot-token"))
API_TOKEN_FILE = Path(os.getenv("TELEGRAM_BRIDGE_TOKEN_FILE", "/run/secrets/bridge-token"))
APPROVAL_TOKEN_FILE = Path(
    os.getenv("AI_OPS_APPROVAL_TOKEN_FILE", "/run/secrets/approval-token")
)
STATE_FILE = Path(os.getenv("TELEGRAM_OFFSET_FILE", "/state/offset"))
N8N_WEBHOOK_URL = os.getenv(
    "N8N_WEBHOOK_URL", "http://n8n:5678/webhook/piserver-ai-ops-telegram-v1"
)
AI_OPS_GATEWAY_URL = os.getenv("AI_OPS_GATEWAY_URL", "http://ai-ops-bridge:8080")
ALLOWED_CHAT_ID = os.getenv("AI_OPS_TELEGRAM_CHAT_ID", "").strip()
ALLOWED_USER_ID = os.getenv("AI_OPS_TELEGRAM_USER_ID", "").strip()
BOT_TOKEN = BOT_TOKEN_FILE.read_text(encoding="utf-8").strip()
API_TOKEN = API_TOKEN_FILE.read_text(encoding="utf-8").strip()
APPROVAL_TOKEN = APPROVAL_TOKEN_FILE.read_text(encoding="utf-8").strip()
if not re.fullmatch(r"\d+:[A-Za-z0-9_-]{20,}", BOT_TOKEN):
    raise RuntimeError("invalid Telegram bot token")
if len(API_TOKEN) < 32:
    raise RuntimeError("Telegram bridge API token must contain at least 32 characters")
if len(APPROVAL_TOKEN) < 32:
    raise RuntimeError("AI Ops approval token must contain at least 32 characters")
if not re.fullmatch(r"-?\d+", ALLOWED_CHAT_ID):
    raise RuntimeError("AI_OPS_TELEGRAM_CHAT_ID must be numeric")
if not re.fullmatch(r"\d+", ALLOWED_USER_ID):
    raise RuntimeError("AI_OPS_TELEGRAM_USER_ID must be numeric")

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"
MAX_BODY = 65_536


def _request_json(
    url: str,
    payload: dict[str, Any],
    timeout: int,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, separators=(",", ":")).encode(),
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read(MAX_BODY + 1)
    if len(raw) > MAX_BODY:
        raise ValueError("remote response is too large")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("remote response is not an object")
    return value


def _telegram(method: str, payload: dict[str, Any], timeout: int = 20) -> dict[str, Any]:
    result = _request_json(f"{TELEGRAM_API}/{method}", payload, timeout)
    if result.get("ok") is not True:
        raise RuntimeError(str(result.get("description", "Telegram API error")))
    return result


def _read_offset() -> int:
    try:
        return max(0, int(STATE_FILE.read_text(encoding="ascii").strip()))
    except (OSError, ValueError):
        return 0


def _write_offset(offset: int) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATE_FILE.with_suffix(".tmp")
    temporary.write_text(f"{offset}\n", encoding="ascii")
    temporary.replace(STATE_FILE)


def _forward(update: dict[str, Any]) -> None:
    request = urllib.request.Request(
        N8N_WEBHOOK_URL,
        data=json.dumps(update, separators=(",", ":")).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        if response.status < 200 or response.status >= 300:
            raise RuntimeError(f"n8n returned HTTP {response.status}")
        response.read(4096)


def _is_authorized(update: dict[str, Any]) -> bool:
    callback = update.get("callback_query")
    message = update.get("message")
    if not isinstance(callback, dict):
        callback = None
    if not isinstance(message, dict):
        message = None
    user = callback.get("from") if callback else (message or {}).get("from")
    callback_message = callback.get("message") if callback else None
    if not isinstance(callback_message, dict):
        callback_message = None
    chat = (callback_message or {}).get("chat") if callback else (message or {}).get("chat")
    if not isinstance(user, dict) or not isinstance(chat, dict):
        return False
    return str(user.get("id")) == ALLOWED_USER_ID and str(chat.get("id")) == ALLOWED_CHAT_ID


def _approve_if_requested(update: dict[str, Any]) -> None:
    callback = update.get("callback_query")
    if not isinstance(callback, dict):
        return
    data = callback.get("data")
    if not isinstance(data, str) or not data.startswith("aiok:"):
        return
    match = re.fullmatch(r"aiok:([a-f0-9]{12}):([A-Za-z0-9_-]{10,})", data)
    if not match:
        raise ValueError("invalid approval callback")
    result = _request_json(
        f"{AI_OPS_GATEWAY_URL}/v1/plans/{match.group(1)}/approve",
        {"approval_token": match.group(2)},
        20,
        {"Authorization": f"Bearer {APPROVAL_TOKEN}"},
    )
    if result.get("status") != "approved":
        raise RuntimeError("gateway did not approve the plan")


def _poll() -> None:
    offset = _read_offset()
    delay = 2
    while True:
        try:
            response = _telegram(
                "getUpdates",
                {
                    "offset": offset,
                    "timeout": 30,
                    "allowed_updates": ["message", "callback_query"],
                },
                timeout=40,
            )
            updates = response.get("result", [])
            if not isinstance(updates, list):
                raise ValueError("Telegram result is not an array")
            for update in updates:
                if not isinstance(update, dict) or not isinstance(update.get("update_id"), int):
                    continue
                if _is_authorized(update):
                    try:
                        _approve_if_requested(update)
                    except (OSError, ValueError, RuntimeError, urllib.error.URLError):
                        callback = update.get("callback_query", {})
                        query_id = callback.get("id") if isinstance(callback, dict) else None
                        if isinstance(query_id, str):
                            _telegram(
                                "answerCallbackQuery",
                                {
                                    "callback_query_id": query_id,
                                    "text": "Piano scaduto, già usato o non approvabile.",
                                    "show_alert": True,
                                },
                            )
                    else:
                        _forward(update)
                offset = update["update_id"] + 1
                _write_offset(offset)
            delay = 2
        except (OSError, ValueError, RuntimeError, urllib.error.URLError):
            time.sleep(delay)
            delay = min(delay * 2, 60)


def _valid_keyboard(value: Any) -> bool:
    if value is None:
        return True
    if not isinstance(value, list) or len(value) > 4:
        return False
    for row in value:
        if not isinstance(row, list) or not (1 <= len(row) <= 3):
            return False
        for button in row:
            if not isinstance(button, dict) or set(button) != {"text", "callback_data"}:
                return False
            text = button["text"]
            data = button["callback_data"]
            if not isinstance(text, str) or not (1 <= len(text) <= 64):
                return False
            if not isinstance(data, str) or len(data.encode()) > 64:
                return False
            if not data.startswith(("aiok:", "aino:")):
                return False
    return True


def _message_chunks(text: str, limit: int = 3900) -> list[str]:
    chunks: list[str] = []
    remaining = text
    while len(remaining) > limit:
        split_at = remaining.rfind("\n", 0, limit + 1)
        if split_at < limit // 2:
            split_at = limit
        chunks.append(remaining[:split_at])
        remaining = remaining[split_at:].lstrip("\n")
    if remaining:
        chunks.append(remaining)
    return chunks


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/v1/health":
            self._json(200, {"status": "ok"})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if not hmac.compare_digest(
            self.headers.get("Authorization", ""), f"Bearer {API_TOKEN}"
        ):
            self._json(401, {"error": "unauthorized"})
            return
        try:
            body = self._body()
            if self.path == "/v1/messages":
                chat_id = body.get("chat_id")
                message_text = body.get("text")
                keyboard = body.get("inline_keyboard")
                if str(chat_id) != ALLOWED_CHAT_ID:
                    raise ValueError("chat_id is outside policy")
                if not isinstance(message_text, str) or not (1 <= len(message_text) <= 60_000):
                    raise ValueError("invalid message text")
                if not _valid_keyboard(keyboard):
                    raise ValueError("invalid inline keyboard")
                chunks = _message_chunks(message_text)
                messages: list[Any] = []
                for index, chunk in enumerate(chunks):
                    payload: dict[str, Any] = {
                        "chat_id": chat_id,
                        "text": chunk,
                        "disable_web_page_preview": True,
                    }
                    if keyboard and index == len(chunks) - 1:
                        payload["reply_markup"] = {"inline_keyboard": keyboard}
                    result = _telegram("sendMessage", payload)
                    messages.append(result.get("result"))
                self._json(200, {"status": "sent", "telegram": messages})
                return
            if self.path == "/v1/callbacks/answer":
                query_id = body.get("query_id")
                if not isinstance(query_id, str) or not query_id:
                    raise ValueError("invalid query_id")
                _telegram(
                    "answerCallbackQuery",
                    {"callback_query_id": query_id, "text": "Richiesta ricevuta"},
                )
                self._json(200, {"status": "answered"})
                return
            self._json(404, {"error": "not found"})
        except (ValueError, RuntimeError, OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            self._json(400, {"error": str(exc)[:500]})

    def _body(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("invalid content length") from exc
        if length <= 0 or length > MAX_BODY:
            raise ValueError("invalid request size")
        value = json.loads(self.rfile.read(length))
        if not isinstance(value, dict):
            raise ValueError("body must be an object")
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


if __name__ == "__main__":
    threading.Thread(target=_poll, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
