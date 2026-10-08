#!/usr/bin/env python3
"""Configure Cockpit without changing Linux accounts or sudo rules."""
from __future__ import annotations

import argparse
import configparser
import json
import re
import sys
from pathlib import Path


def validate_fqdn(fqdn: str) -> str:
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\.ts\.net", fqdn):
        raise ValueError("Expected the host's Tailscale DNS name without a trailing dot")
    return fqdn


def check_serve(payload: dict, fqdn: str) -> None:
    key = f"{validate_fqdn(fqdn)}:8465"
    if payload.get("AllowFunnel", {}).get(key):
        raise ValueError("Port 8465 has Funnel enabled; disable it before installation")
    handlers = payload.get("Web", {}).get(key, {}).get("Handlers", {})
    if handlers and handlers != {"/": {"Proxy": "http://127.0.0.1:9090"}}:
        raise ValueError("Port 8465 already serves another application")
    tcp = payload.get("TCP", {}).get("8465")
    if tcp is not None and tcp != {"HTTPS": True}:
        raise ValueError("Port 8465 already has a non-HTTPS Serve configuration")


def configure(directory: Path, fqdn: str, user: str) -> None:
    validate_fqdn(fqdn)
    denied_path = directory / "disallowed-users"
    denied = denied_path.read_text() if denied_path.exists() else ""
    users = {line.split("#", 1)[0].strip() for line in denied.splitlines()}
    if user in users or user == "root":
        raise ValueError("The selected administrator is disallowed in Cockpit")
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str
    path = directory / "cockpit.conf"
    if path.exists():
        parser.read(path)
    if not parser.has_section("WebService"):
        parser.add_section("WebService")
    parser.set("WebService", "Origins", f"https://{fqdn}:8465")
    parser.set("WebService", "ProtocolHeader", "X-Forwarded-Proto")
    parser.set("WebService", "LoginTo", "false")
    with path.open("w") as stream:
        parser.write(stream)
    path.chmod(0o644)
    if "root" not in users:
        denied_path.write_text(denied.rstrip() + "\nroot\n")
    denied_path.chmod(0o644)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-serve")
    parser.add_argument("--fqdn")
    parser.add_argument("--user")
    args = parser.parse_args()
    if args.check_serve:
        check_serve(json.load(sys.stdin), args.check_serve)
    elif args.fqdn and args.user:
        configure(Path("/etc/cockpit"), args.fqdn, args.user)
    else:
        parser.error("Use --check-serve FQDN or --fqdn FQDN --user ADMIN")


if __name__ == "__main__":
    main()
