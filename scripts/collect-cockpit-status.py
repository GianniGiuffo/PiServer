#!/usr/bin/env python3
"""Collect host-only Cockpit health and metrics into an atomic, read-only snapshot."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.request import urlopen

NAMES = {"cockpit-ws", "cockpit-tls", "cockpit-bridge", "cockpit-session"}
EXECUTABLES = {
    f"{prefix}/{name}"
    for prefix in ("/usr/bin", "/usr/lib/cockpit", "/usr/libexec", "/usr/libexec/cockpit")
    for name in NAMES
}


def command(args: list[str]) -> str:
    result = subprocess.run(args, capture_output=True, text=True, timeout=4, check=True)
    return result.stdout.strip()


def processes(proc: Path = Path("/proc")) -> dict[tuple[int, int], tuple[int, int]]:
    result = {}
    for directory in proc.iterdir():
        if not directory.name.isdigit():
            continue
        try:
            name = (directory / "comm").read_text().strip()
            argv = (directory / "cmdline").read_bytes().split(b"\0")
            # Modern bridges may be Python scripts. Match exact executable paths,
            # never arbitrary arguments or a filename being edited in a session.
            executable_args = argv[:2] if argv and Path(os.fsdecode(argv[0])).name.startswith("python") else argv[:1]
            if name not in NAMES and not any(os.fsdecode(arg) in EXECUTABLES for arg in executable_args):
                continue
            stat = (directory / "stat").read_text().rsplit(")", 1)[1].split()
            key = (int(directory.name), int(stat[19]))  # PID and start time
            cpu_ticks = int(stat[11]) + int(stat[12])
            memory = max(0, int(stat[21])) * os.sysconf("SC_PAGE_SIZE")
            result[key] = (cpu_ticks, memory)
        except (OSError, ValueError, IndexError):
            continue  # A process can exit between the proc reads.
    return result


def usage(before: dict, after: dict, elapsed: float, ticks: int, cpus: int) -> tuple[float, int]:
    consumed = sum(max(0, value[0] - before[key][0]) for key, value in after.items() if key in before)
    cpu = min(100.0, consumed * 100 / (ticks * max(elapsed, 0.001) * max(cpus, 1)))
    return round(cpu, 2), sum(value[1] for value in after.values())


def private_route(payload: dict, fqdn: str) -> bool:
    key = f"{fqdn}:8465"
    return (
        payload.get("TCP", {}).get("8465") == {"HTTPS": True}
        and payload.get("Web", {}).get(key, {}).get("Handlers") == {"/": {"Proxy": "http://127.0.0.1:9090"}}
        and not payload.get("AllowFunnel", {}).get(key, False)
    )


def loopback_listener(output: str) -> bool:
    addresses = [line.split()[3] for line in output.splitlines() if len(line.split()) >= 4]
    return bool(addresses) and all(address in {"127.0.0.1:9090", "[::1]:9090"} for address in addresses)


def classify(checks: dict[str, bool | None], metrics_complete: bool) -> tuple[str, str]:
    if any(value is False for value in checks.values()):
        return "red", "Non disponibile"
    if any(value is None for value in checks.values()) or not metrics_complete:
        return "yellow", "Controlli incompleti"
    return "green", "Disponibile"


def collect(fqdn: str) -> dict:
    checks: dict[str, bool | None] = {}
    try:
        manifest = json.loads(Path("/usr/share/cockpit/files/manifest.json").read_text())
        checks["files"] = isinstance(manifest, dict) and bool(manifest.get("tools"))
    except FileNotFoundError:
        checks["files"] = False
    except (OSError, ValueError):
        checks["files"] = None
    checks["shell"] = any(Path(f"/usr/share/cockpit/shell/{name}").is_file() for name in ("shell.html", "index.html"))
    try:
        checks["socket"] = command(["systemctl", "show", "cockpit.socket", "--property=ActiveState", "--value"]) == "active"
    except (OSError, subprocess.SubprocessError):
        checks["socket"] = None
    # Probe the real backend, including when socket activation has left the web
    # service idle. Its inactive state alone does not mean the app is down.
    try:
        with urlopen("http://127.0.0.1:9090/ping", timeout=3) as response:
            payload = json.load(response)
            checks["web"] = response.status == 200 and isinstance(payload, dict) and payload.get("service") == "cockpit"
    except (OSError, ValueError):
        checks["web"] = False
    try:
        checks["private"] = private_route(json.loads(command(["tailscale", "serve", "status", "--json"])), fqdn)
        checks["loopback"] = loopback_listener(command(["ss", "-H", "-lnt", "sport = :9090"]))
    except (OSError, ValueError, subprocess.SubprocessError):
        checks["private"] = checks["loopback"] = None
    cpu = memory = free = used = None
    try:
        before = processes()
        started = time.monotonic()
        time.sleep(1)
        after = processes()
        cpu, memory = usage(before, after, time.monotonic() - started, os.sysconf("SC_CLK_TCK"), os.cpu_count() or 1)
    except (OSError, ValueError):
        pass
    try:
        disk = os.statvfs("/")
        total = disk.f_blocks * disk.f_frsize
        free = disk.f_bavail * disk.f_frsize
        used = round((total - free) * 100 / total, 1)
    except (OSError, ZeroDivisionError):
        pass
    color, status = classify(checks, all(value is not None for value in (cpu, memory, free, used)))
    return {
        "color": color, "status": status, "updated_at": time.time(),
        "cpu_percent": cpu, "memory_bytes": memory,
        "free_bytes": free, "used_percent": used,
    }


def write_snapshot(path: Path, payload: dict) -> None:
    # Directory is provisioned by the installer; no access to arbitrary host
    # files is exposed to the Docker monitoring API or Homepage.
    descriptor, temporary = tempfile.mkstemp(prefix="cockpit.", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w") as stream:
            json.dump(payload, stream, ensure_ascii=False, allow_nan=False)
            stream.write("\n")
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--status-file", required=True, type=Path)
    parser.add_argument("--fqdn", required=True)
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error("Run with sudo on the mini PC")
    write_snapshot(args.status_file, collect(args.fqdn))


if __name__ == "__main__":
    main()
