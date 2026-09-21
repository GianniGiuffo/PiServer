#!/usr/bin/env python3
"""Provision the bridge identity and private configuration on the server."""

import json
import os
import secrets
import sqlite3
import subprocess
from pathlib import Path
from urllib.request import Request, urlopen


SC_DB = Path('/srv/raspberry-server/data/streamingcommunity/panel.db')
SEERR_SETTINGS = Path('/srv/raspberry-server/data/seerr/settings.json')
SEERR_DB = Path('/srv/raspberry-server/data/seerr/db/db.sqlite3')
CONFIG = Path('/etc/raspberry-server/seerr-streamingcommunity-bridge.env')
PASSWORD = Path('/etc/raspberry-server/seerr-bridge-jellyfin-password')
NAME = 'SeerrBridge'
BASE = 'http://127.0.0.1:8096'


def call(method, path, key=None, data=None):
    headers = {'Accept': 'application/json', 'Content-Type': 'application/json'}
    auth = ('MediaBrowser Client="SeerrBridge", Device="mini-pc", '
            'DeviceId="SeerrBridgeService", Version="1.0"')
    if key:
        auth += f', Token="{key}"'
    headers['Authorization'] = auth
    payload = json.dumps(data).encode() if data is not None else None
    with urlopen(Request(BASE + path, data=payload, headers=headers, method=method),
                 timeout=30) as response:
        content = response.read()
    return json.loads(content) if content else None


def main():
    if os.geteuid() != 0:
        raise SystemExit('Run as root on mini-pc')
    if CONFIG.exists():
        raise SystemExit(f'{CONFIG} already exists; refusing to replace credentials')
    conn = sqlite3.connect(SC_DB)
    admin_key = conn.execute('SELECT value FROM jf_setting WHERE key=?',
                             ('jellyfin_api_key',)).fetchone()[0]
    seerr_key = json.loads(SEERR_SETTINGS.read_text())['main']['apiKey']
    seerr_user = sqlite3.connect(SEERR_DB).execute(
        'SELECT id, permissions FROM user WHERE username=?', ('NormalUser',)).fetchone()
    if not seerr_user or seerr_user[1] != 32:
        raise SystemExit('NormalUser must have only the Seerr REQUEST permission (32)')

    users = call('GET', '/Users', admin_key)
    found = next((user for user in users if user['Name'] == NAME), None)
    if found and not PASSWORD.exists():
        raise SystemExit(f'{NAME} already exists without local bootstrap password')
    if not PASSWORD.exists():
        password = secrets.token_urlsafe(48)
        PASSWORD.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(PASSWORD, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as output:
            output.write(password + '\n')
    else:
        password = PASSWORD.read_text().strip()
    if not found:
        found = call('POST', '/Users/New', admin_key,
                     {'Name': NAME, 'Password': password})

    account = call('POST', '/Users/AuthenticateByName', data={
        'Username': NAME, 'Pw': password,
    })
    token = account['AccessToken']
    user_id = found['Id']
    code = ('from app.auth import models; import sys; '
            'u=models.get_user_by_jellyfin_id(sys.argv[1]); '
            'u=u or models.create_user(sys.argv[1], "SeerrBridge", 6); '
            'models.set_permissions(u.id, 6)')
    subprocess.run(['docker', 'exec', 'raspberry-server-streamingcommunity-1',
                    'python', '-c', code, user_id], check=True)

    lines = [f'SEERR_REQUEST_USER_ID={seerr_user[0]}', f'SEERR_API_KEY={seerr_key}',
             f'BRIDGE_JELLYFIN_TOKEN={token}']
    fd = os.open(CONFIG, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o640)
    with os.fdopen(fd, 'w') as output:
        output.write('\n'.join(lines) + '\n')
    import grp
    bridge_gid = grp.getgrnam('tommaso').gr_gid
    os.chown(CONFIG.parent, 0, bridge_gid)
    os.chmod(CONFIG.parent, 0o710)
    os.chown(CONFIG, 0, bridge_gid)
    subprocess.run(['python3', str(Path(__file__).with_name(
        'configure-seerr-bridge-webhook.py'))], check=True)
    print(f'Provisioned {NAME} with StreamingCommunity REQUEST and MANAGE_REQUESTS permissions')


if __name__ == '__main__':
    main()
