#!/usr/bin/env python3
"""Prepare and atomically activate Seerr's bridge-owned Arr routing.

Run ``prepare`` after the Restic backup. Run ``activate`` only with Seerr and
the old bridge stopped; it disconnects Arr from Seerr while retaining the real
Arr credentials exclusively in the private bridge environment file.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from urllib.request import Request, urlopen


ROOT = Path("/srv/raspberry-server/data/seerr")
SETTINGS = ROOT / "settings.json"
DB = ROOT / "db/db.sqlite3"
CONFIG = Path("/etc/raspberry-server/seerr-streamingcommunity-bridge.env")
ROLLBACK = Path("/etc/raspberry-server/seerr-settings-pre-priority.json")


def atomic_write(path: Path, content: str, reference: Path) -> None:
    stat = reference.stat()
    temporary = path.with_name(path.name + ".priority-tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.chown(temporary, stat.st_uid, stat.st_gid)
        os.chmod(temporary, stat.st_mode & 0o777)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def read_env() -> dict[str, str]:
    return dict(line.split("=", 1) for line in CONFIG.read_text().splitlines()
                if line and not line.startswith("#"))


def write_env(values: dict[str, str]) -> None:
    atomic_write(CONFIG, "".join(f"{k}={v}\n" for k, v in values.items()), CONFIG)


def users() -> tuple[int, int]:
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    admin = con.execute("SELECT id,permissions,jellyfinUserId FROM user WHERE id=1").fetchone()
    normal = con.execute("SELECT id,permissions FROM user WHERE username='NormalUser'").fetchone()
    if not admin or admin[1] != 2 or not admin[2]:
        raise RuntimeError("The real Seerr admin must retain its Jellyfin account")
    if not normal or normal[1] != 32:
        raise RuntimeError("NormalUser must retain only Request permission")
    return admin[0], normal[0]


def assert_stopped() -> None:
    for service in ("raspberry-server-seerr-1",
                    "raspberry-server-seerr-streamingcommunity-bridge-1"):
        result = subprocess.run(["docker", "inspect", "--format",
                                 "{{.State.Running}}", service],
                                capture_output=True, text=True, check=True)
        if result.stdout.strip() != "false":
            raise RuntimeError(f"Stop {service} before activation")


def validate_arr(kind: str, item: dict) -> None:
    # This runs on the host, outside Docker's service-name DNS.
    base = f"http://127.0.0.1:{item['port']}/api/v3"
    for endpoint, field, wanted in (
        ("qualityprofile", "id", item["activeProfileId"]),
        ("rootfolder", "path", item["activeDirectory"]),
    ):
        request = Request(base + "/" + endpoint,
                          headers={"X-Api-Key": item["apiKey"]})
        with urlopen(request, timeout=10) as response:
            records = json.load(response)
        if not any(row.get(field) == wanted for row in records):
            raise RuntimeError(f"{kind} {endpoint} selection is invalid")


def prepare() -> None:
    settings = json.loads(SETTINGS.read_text())
    if len(settings.get("radarr", [])) != 1 or len(settings.get("sonarr", [])) != 1:
        raise RuntimeError("Expected one real Radarr and one real Sonarr")
    radarr, sonarr = settings["radarr"][0], settings["sonarr"][0]
    if radarr.get("is4k") or sonarr.get("is4k"):
        raise RuntimeError("4K Arr setup needs a separate routing design")
    admin_id, normal_id = users()
    env = read_env()
    if int(env["SEERR_REQUEST_USER_ID"]) != normal_id:
        raise RuntimeError("Existing bridge user differs from NormalUser")
    validate_arr("radarr", radarr)
    validate_arr("sonarr", sonarr)
    env.update({
        "SEERR_ADMIN_USER_ID": str(admin_id),
        "RADARR_API_KEY": radarr["apiKey"],
        "SONARR_API_KEY": sonarr["apiKey"],
        "RADARR_ROOT_FOLDER": radarr["activeDirectory"],
        "SONARR_ROOT_FOLDER": sonarr["activeDirectory"],
        "RADARR_PROFILE_ID": str(radarr["activeProfileId"]),
        "SONARR_PROFILE_ID": str(sonarr["activeProfileId"]),
        "RADARR_MINIMUM_AVAILABILITY": radarr.get("minimumAvailability", "released"),
    })
    write_env(env)
    print("Prepared private Arr fallback settings; Seerr configuration is unchanged")


def activate() -> None:
    assert_stopped()
    admin_id, normal_id = users()
    settings = json.loads(SETTINGS.read_text())
    if len(settings.get("radarr", [])) != 1 or len(settings.get("sonarr", [])) != 1:
        raise RuntimeError("Seerr Arr configuration changed since preparation")
    env = read_env()
    if int(env["SEERR_ADMIN_USER_ID"]) != admin_id or int(
            env["SEERR_REQUEST_USER_ID"]) != normal_id:
        raise RuntimeError("Bridge user identity changed")
    for key in ("RADARR_API_KEY", "SONARR_API_KEY", "RADARR_PROFILE_ID",
                "SONARR_PROFILE_ID", "RADARR_ROOT_FOLDER", "SONARR_ROOT_FOLDER"):
        if not env.get(key):
            raise RuntimeError(f"Missing prepared {key}")
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    next_id = con.execute("SELECT COALESCE(MAX(id),0)+1 FROM media_request").fetchone()[0]
    env["SEERR_ADMIN_MIN_REQUEST_ID"] = str(next_id)
    write_env(env)
    if ROLLBACK.exists():
        raise RuntimeError("Pre-priority settings backup already exists")
    atomic_write(ROLLBACK, SETTINGS.read_text(), SETTINGS)
    os.chown(ROLLBACK, 0, 0)
    os.chmod(ROLLBACK, 0o600)
    settings["radarr"] = []
    settings["sonarr"] = []
    atomic_write(SETTINGS, json.dumps(settings, indent=2) + "\n", SETTINGS)
    print(f"Seerr disconnected from Arr; admin routing begins at request {next_id}")


if __name__ == "__main__":
    if os.geteuid() != 0:
        raise SystemExit("Run as root on mini-pc")
    if len(sys.argv) != 2 or sys.argv[1] not in ("prepare", "activate"):
        raise SystemExit("Usage: activate-seerr-priority.py <prepare|activate>")
    (prepare if sys.argv[1] == "prepare" else activate)()
