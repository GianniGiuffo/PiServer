#!/usr/bin/env python3
"""Prepare private credentials, or replace Stirling's existing default password."""
import argparse
import json
from pathlib import Path
import secrets
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:8087"


def request(path, values, token=None):
    headers = {}
    if token:
        headers["Authorization"] = "Bearer " + token
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        body = urllib.parse.urlencode(values).encode()
    else:
        headers["Content-Type"] = "application/json"
        body = json.dumps(values).encode()
    req = urllib.request.Request(BASE + path, data=body, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.load(response)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare", action="store_true", help="Generate missing .env credentials; do not contact Stirling")
    args = parser.parse_args()
    env = ROOT / ".env"
    content = env.read_text()
    values = {}
    for line in content.splitlines():
        key, separator, value = line.partition("=")
        if separator and not key.startswith("#"):
            values[key.strip()] = value.strip().strip("\"'")
    if args.prepare:
        additions = []
        for key, default in [("STIRLING_ADMIN_USERNAME", "admin"),
                             ("STIRLING_ADMIN_PASSWORD", secrets.token_hex(24))]:
            if not values.get(key) or values[key] == "CHANGE_ME" or (key == "STIRLING_ADMIN_PASSWORD" and values[key] == "stirling"):
                content = "\n".join(line for line in content.splitlines()
                                    if not line.startswith(key + "="))
                additions.append(key + "=" + default)
        if additions:
            env.write_text(content.rstrip() + "\n" + "\n".join(additions) + "\n")
        env.chmod(0o600)
        print("Stirling credentials prepared in private .env; values are not printed.")
        return
    username = values.get("STIRLING_ADMIN_USERNAME", "admin")
    password = values.get("STIRLING_ADMIN_PASSWORD", "")
    if password in ("", "CHANGE_ME", "stirling"):
        raise SystemExit("Run this script with --prepare first.")
    try:
        data = request("/api/v1/auth/login", {"username": username, "password": password})
    except urllib.error.HTTPError as error:
        if error.code not in (400, 401, 403) or username != "admin":
            raise SystemExit("Configured Stirling login failed; existing credentials were not changed.") from None
        try:
            data = request("/api/v1/auth/login", {"username": "admin", "password": "stirling"})
            request("/api/v1/user/change-password-on-login",
                    {"currentPassword": "stirling", "newPassword": password,
                     "confirmPassword": password}, data["session"]["access_token"])
            data = request("/api/v1/auth/login", {"username": username, "password": password})
        except urllib.error.HTTPError:
            raise SystemExit("Default password migration failed; check the existing admin account locally.") from None
    if "ADMIN" not in data["user"].get("role", "").upper():
        raise SystemExit("Login works but the account is not an administrator.")
    print("Stirling administrator login verified; the default password has been replaced.")


if __name__ == "__main__":
    main()
