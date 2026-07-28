#!/usr/bin/env python3
"""Small read-only metrics API used by Homepage's Custom API widgets."""

from __future__ import annotations

import json
import os
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


PROC_STAT = Path(os.getenv("HOST_PROC_STAT", "/host/proc/stat"))
PROC_MEMINFO = Path(os.getenv("HOST_PROC_MEMINFO", "/host/proc/meminfo"))
PROC_UPTIME = Path(os.getenv("HOST_PROC_UPTIME", "/host/proc/uptime"))
PROC_NET_DEV = Path(os.getenv("HOST_PROC_NET_DEV", "/host/proc/net/dev"))
PROC_MOUNTS = Path(os.getenv("HOST_PROC_MOUNTS", "/host/proc/mounts"))
THERMAL_ROOT = Path(os.getenv("HOST_THERMAL_ROOT", "/host/sys/class/thermal"))
HWMON_ROOT = Path(os.getenv("HOST_HWMON_ROOT", "/host/sys/class/hwmon"))
MEDIA_PATH = Path(os.getenv("MEDIA_PATH", "/srv/media"))
BACKUP_STATUS_FILE = Path(
    os.getenv("BACKUP_STATUS_FILE", "/status/backup.json")
)
NETWORK_INTERFACE = os.getenv("NETWORK_INTERFACE", "auto").strip()

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
    media = str(MEDIA_PATH)
    try:
        for line in _read_text(PROC_MOUNTS).splitlines():
            fields = line.split()
            if len(fields) < 3:
                continue
            mountpoint = _unescape_mount_path(fields[1])
            filesystem = fields[2]
            if mountpoint == media and filesystem != "autofs":
                return True
    except OSError:
        return False
    return False


class Metrics:
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
            stats = os.statvfs(MEDIA_PATH)
            total = stats.f_blocks * stats.f_frsize
            free = stats.f_bavail * stats.f_frsize
            used_percent = round((total - free) * 100 / total, 1) if total else None
            return {
                "status": "Montato",
                "free_bytes": free,
                "total_bytes": total,
                "used_percent": used_percent,
            }
        except OSError:
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


METRICS = Metrics()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        endpoint = urlparse(self.path).path
        routes = {
            "/server": METRICS.server,
            "/nas": METRICS.nas,
            "/network": METRICS.network,
            "/backup": METRICS.backup,
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
