#!/usr/bin/env python3
"""Read-only metrics API used by Homepage's Custom API widgets."""

from __future__ import annotations

import json
import os
import re
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen


PROC_STAT = Path(os.getenv("HOST_PROC_STAT", "/host/proc/stat"))
PROC_MEMINFO = Path(os.getenv("HOST_PROC_MEMINFO", "/host/proc/meminfo"))
PROC_UPTIME = Path(os.getenv("HOST_PROC_UPTIME", "/host/proc/uptime"))
PROC_NET_DEV = Path(os.getenv("HOST_PROC_NET_DEV", "/host/proc/net/dev"))
PROC_MOUNTS = Path(os.getenv("HOST_PROC_MOUNTS", "/host/proc/mounts"))
THERMAL_ROOT = Path(os.getenv("HOST_THERMAL_ROOT", "/host/sys/class/thermal"))
HWMON_ROOT = Path(os.getenv("HOST_HWMON_ROOT", "/host/sys/class/hwmon"))
MEDIA_MOUNTPOINT = os.getenv("MEDIA_MOUNTPOINT", "/srv/media")
MEDIA_STATUS_FILE = Path(os.getenv("MEDIA_STATUS_FILE", "/status/media.json"))
BACKUP_STATUS_FILE = Path(
    os.getenv("BACKUP_STATUS_FILE", "/status/backup.json")
)
UPS_STATUS_FILE = Path(os.getenv("UPS_STATUS_FILE", "/status/ups.json"))
NETWORK_INTERFACE = os.getenv("NETWORK_INTERFACE", "auto").strip()
RACK_PI_STATUS_URL = os.getenv("RACK_PI_STATUS_URL", "").strip().rstrip("/")
DOCKER_API_URL = os.getenv("DOCKER_API_URL", "").strip().rstrip("/")
EXPECTED_COMPOSE_PROJECT = os.getenv("EXPECTED_COMPOSE_PROJECT", "").strip()
EXPECTED_SERVICES = tuple(
    value.strip()
    for value in os.getenv("EXPECTED_SERVICES", "").split(",")
    if value.strip()
)

_SAFE_INTERFACE = re.compile(r"^[A-Za-z0-9_.:-]+$")
_VIRTUAL_PREFIXES = (
    "lo",
    "br-",
    "docker",
    "veth",
    "virbr",
    "tailscale",
    "zt",
)


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _get_json(url: str, timeout: float = 4) -> object:
    request = Request(url, headers={"Accept": "application/json"})
    with urlopen(request, timeout=timeout) as response:
        return json.load(response)


def _relative_age(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        return "Non disponibile"
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        seconds = max(0, int((datetime.now(timezone.utc) - moment).total_seconds()))
    except ValueError:
        return "Non disponibile"
    if seconds < 60:
        return "ora"
    if seconds < 3600:
        minutes = seconds // 60
        return f"{minutes} min fa"
    if seconds < 86400:
        hours = seconds // 3600
        return f"{hours} {'ora' if hours == 1 else 'ore'} fa"
    days = seconds // 86400
    return f"{days} {'giorno' if days == 1 else 'giorni'} fa"


def _read_cpu_times() -> tuple[int, int]:
    first = _read_text(PROC_STAT).splitlines()[0].split()
    if not first or first[0] != "cpu":
        raise ValueError("invalid /proc/stat")
    values = [int(value) for value in first[1:]]
    idle = values[3] + (values[4] if len(values) > 4 else 0)
    return sum(values), idle


def _read_memory_percent() -> float:
    values: dict[str, int] = {}
    for line in _read_text(PROC_MEMINFO).splitlines():
        key, _, raw_value = line.partition(":")
        if key in {"MemTotal", "MemAvailable"}:
            values[key] = int(raw_value.strip().split()[0])
    total = values["MemTotal"]
    available = values["MemAvailable"]
    return round((total - available) * 100 / total, 1)


def _read_uptime() -> int:
    return int(float(_read_text(PROC_UPTIME).split()[0]))


def _temperature_candidates() -> list[tuple[int, float]]:
    candidates: list[tuple[int, float]] = []
    priorities = {
        "x86_pkg_temp": 0,
        "package": 0,
        "cpu": 1,
        "coretemp": 1,
        "acpitz": 2,
    }

    for zone in THERMAL_ROOT.glob("thermal_zone*"):
        try:
            sensor_type = _read_text(zone / "type").strip().lower()
            value = float(_read_text(zone / "temp").strip()) / 1000
            priority = min(
                (rank for name, rank in priorities.items() if name in sensor_type),
                default=10,
            )
            if -20 <= value <= 150:
                candidates.append((priority, value))
        except (OSError, ValueError):
            continue

    for hwmon in HWMON_ROOT.glob("hwmon*"):
        try:
            chip_name = _read_text(hwmon / "name").strip().lower()
        except OSError:
            chip_name = ""
        for sensor in hwmon.glob("temp*_input"):
            try:
                value = float(_read_text(sensor).strip()) / 1000
                priority = 1 if chip_name in {"coretemp", "k10temp", "cpu_thermal"} else 5
                if -20 <= value <= 150:
                    candidates.append((priority, value))
            except (OSError, ValueError):
                continue
    return candidates


def _read_temperature() -> float | None:
    candidates = _temperature_candidates()
    if not candidates:
        return None
    best_priority = min(priority for priority, _ in candidates)
    values = [value for priority, value in candidates if priority == best_priority]
    return round(max(values), 1)


def _read_network_counters() -> dict[str, tuple[int, int]]:
    counters: dict[str, tuple[int, int]] = {}
    for line in _read_text(PROC_NET_DEV).splitlines()[2:]:
        name, separator, raw_values = line.partition(":")
        if not separator:
            continue
        fields = raw_values.split()
        if len(fields) >= 16:
            counters[name.strip()] = (int(fields[0]), int(fields[8]))
    return counters


def _select_interface(counters: dict[str, tuple[int, int]]) -> str | None:
    if NETWORK_INTERFACE and NETWORK_INTERFACE.lower() != "auto":
        if not _SAFE_INTERFACE.fullmatch(NETWORK_INTERFACE):
            return None
        return NETWORK_INTERFACE if NETWORK_INTERFACE in counters else None

    physical = [
        name
        for name in counters
        if not name.startswith(_VIRTUAL_PREFIXES)
    ]
    if not physical:
        return None
    preferred = [
        name
        for name in physical
        if name.startswith(("en", "eth", "wl", "wlan", "bond"))
    ]
    choices = preferred or physical
    return max(choices, key=lambda name: sum(counters[name]))


def _unescape_mount_path(value: str) -> str:
    return (
        value.replace(r"\040", " ")
        .replace(r"\011", "\t")
        .replace(r"\012", "\n")
        .replace(r"\134", "\\")
    )


def _media_is_mounted() -> bool:
    try:
        for line in _read_text(PROC_MOUNTS).splitlines():
            fields = line.split()
            if len(fields) < 3:
                continue
            mountpoint = _unescape_mount_path(fields[1])
            filesystem = fields[2]
            if mountpoint == MEDIA_MOUNTPOINT and filesystem != "autofs":
                return True
    except OSError:
        return False
    return False


class Metrics:
    _last_raspberry_backup: object = None
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cpu_percent: float | None = None
        self._interface: str | None = None
        self._rx_bps: float | None = None
        self._tx_bps: float | None = None
        self._sample_thread = threading.Thread(target=self._sample_loop, daemon=True)
        self._sample_thread.start()

    def _sample_loop(self) -> None:
        previous_cpu: tuple[int, int] | None = None
        previous_network: dict[str, tuple[int, int]] = {}
        previous_time = time.monotonic()

        while True:
            try:
                current_cpu = _read_cpu_times()
                current_network = _read_network_counters()
                current_time = time.monotonic()
                elapsed = max(current_time - previous_time, 0.001)
                interface = _select_interface(current_network)

                cpu_percent = None
                if previous_cpu is not None:
                    total_delta = current_cpu[0] - previous_cpu[0]
                    idle_delta = current_cpu[1] - previous_cpu[1]
                    if total_delta > 0:
                        cpu_percent = round(
                            (total_delta - idle_delta) * 100 / total_delta, 1
                        )

                rx_bps = tx_bps = None
                if interface and interface in previous_network:
                    current_rx, current_tx = current_network[interface]
                    previous_rx, previous_tx = previous_network[interface]
                    # /proc/net/dev exposes bytes; Homepage's bitrate formatter
                    # expects bits per second.
                    rx_bps = max(0, current_rx - previous_rx) * 8 / elapsed
                    tx_bps = max(0, current_tx - previous_tx) * 8 / elapsed

                with self._lock:
                    self._cpu_percent = cpu_percent
                    self._interface = interface
                    self._rx_bps = round(rx_bps, 1) if rx_bps is not None else None
                    self._tx_bps = round(tx_bps, 1) if tx_bps is not None else None

                previous_cpu = current_cpu
                previous_network = current_network
                previous_time = current_time
            except (OSError, ValueError, KeyError):
                pass
            time.sleep(1)

    def server(self) -> dict[str, object]:
        with self._lock:
            cpu_percent = self._cpu_percent
        try:
            memory_percent = _read_memory_percent()
        except (OSError, ValueError, KeyError, ZeroDivisionError):
            memory_percent = None
        try:
            uptime_seconds = _read_uptime()
        except (OSError, ValueError, IndexError):
            uptime_seconds = None
        return {
            "cpu_percent": cpu_percent,
            "memory_percent": memory_percent,
            "temperature_c": _read_temperature(),
            "uptime_seconds": uptime_seconds,
        }

    def network(self) -> dict[str, object]:
        with self._lock:
            return {
                "interface": self._interface or "Non rilevata",
                "rx_bps": self._rx_bps,
                "tx_bps": self._tx_bps,
            }

    @staticmethod
    def nas() -> dict[str, object]:
        if not _media_is_mounted():
            return {
                "status": "Non montato",
                "free_bytes": None,
                "total_bytes": None,
                "used_percent": None,
            }
        try:
            payload = json.loads(_read_text(MEDIA_STATUS_FILE))
            if (
                isinstance(payload, dict)
                and payload.get("status") in {"Montato", "Non disponibile"}
            ):
                return {
                    "status": payload["status"],
                    "free_bytes": payload.get("free_bytes"),
                    "total_bytes": payload.get("total_bytes"),
                    "used_percent": payload.get("used_percent"),
                }
        except (OSError, json.JSONDecodeError):
            pass
        return {
            "status": "Non disponibile",
            "free_bytes": None,
            "total_bytes": None,
            "used_percent": None,
        }

    @staticmethod
    def backup() -> dict[str, object]:
        try:
            payload = json.loads(_read_text(BACKUP_STATUS_FILE))
            if isinstance(payload, dict):
                return payload
        except (OSError, json.JSONDecodeError):
            pass
        return {
            "status": "Non ancora registrato",
            "last_success": None,
            "next_run": None,
        }

    @staticmethod
    def ups() -> dict[str, object]:
        try:
            payload = json.loads(_read_text(UPS_STATUS_FILE))
            if isinstance(payload, dict):
                return payload
        except (OSError, json.JSONDecodeError):
            pass
        return {
            "charge_percent": None,
            "power": "Non disponibile",
            "state": "Non disponibile",
            "runtime_seconds": None,
            "load_percent": None,
            "updated_at": None,
        }

    @staticmethod
    def _local_raspberry() -> dict[str, object]:
        backup = Metrics.backup()
        ups = Metrics.ups()
        services_ok = False
        if DOCKER_API_URL and EXPECTED_COMPOSE_PROJECT and EXPECTED_SERVICES:
            filters = json.dumps(
                {"label": [f"com.docker.compose.project={EXPECTED_COMPOSE_PROJECT}"]},
                separators=(",", ":"),
            )
            query = urlencode({"all": "1", "filters": filters})
            try:
                payload = _get_json(f"{DOCKER_API_URL}/containers/json?{query}")
                states: dict[str, bool] = {}
                if isinstance(payload, list):
                    for container in payload:
                        if not isinstance(container, dict):
                            continue
                        labels = container.get("Labels") or {}
                        service = labels.get("com.docker.compose.service")
                        state = container.get("State")
                        health = (container.get("Status") or "").lower()
                        states[service] = state == "running" and "unhealthy" not in health
                    services_ok = all(states.get(name, False) for name in EXPECTED_SERVICES)
            except (HTTPError, URLError, TimeoutError, OSError, ValueError):
                services_ok = False
        return {
            "status": "Online",
            "services": "Online" if services_ok else "Offline",
            "last_backup": backup.get("last_success"),
            "last_backup_age": _relative_age(backup.get("last_success")),
            "ups_charge_percent": ups.get("charge_percent"),
        }

    @staticmethod
    def raspberry() -> dict[str, object]:
        if not RACK_PI_STATUS_URL:
            return Metrics._local_raspberry()
        try:
            payload = _get_json(f"{RACK_PI_STATUS_URL}/raspberry")
            if isinstance(payload, dict):
                Metrics._last_raspberry_backup = payload.get("last_backup")
                return {
                    "status": "Online",
                    "services": (
                        "Online" if payload.get("services") == "Online" else "Offline"
                    ),
                    "last_backup": payload.get("last_backup"),
                    "last_backup_age": _relative_age(payload.get("last_backup")),
                    "ups_charge_percent": payload.get("ups_charge_percent"),
                }
        except (HTTPError, URLError, TimeoutError, OSError, ValueError):
            pass
        return {
            "status": "Offline",
            "services": "Offline",
            "last_backup": Metrics._last_raspberry_backup,
            "last_backup_age": _relative_age(Metrics._last_raspberry_backup),
            "ups_charge_percent": None,
        }


METRICS = Metrics()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        endpoint = urlparse(self.path).path
        routes = {
            "/server": METRICS.server,
            "/nas": METRICS.nas,
            "/network": METRICS.network,
            "/backup": METRICS.backup,
            "/ups": METRICS.ups,
            "/raspberry": METRICS.raspberry,
            "/health": lambda: {"status": "ok"},
        }
        callback = routes.get(endpoint)
        if callback is None:
            self._send_json(404, {"error": "not found"})
            return
        self._send_json(200, callback())

    def _send_json(self, status: int, payload: dict[str, object]) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return


if __name__ == "__main__":
    server = ThreadingHTTPServer(("0.0.0.0", 8080), Handler)
    server.serve_forever()
