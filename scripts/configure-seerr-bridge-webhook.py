#!/usr/bin/env python3
"""Connect Seerr's MEDIA_PENDING notification to the private bridge listener."""

import json
import os
import secrets
from pathlib import Path
from urllib.request import Request, urlopen


CONFIG = Path('/etc/raspberry-server/seerr-streamingcommunity-bridge.env')
URL = 'http://127.0.0.1:5055/api/v1/settings/notifications/webhook'
TARGET = 'http://seerr-streamingcommunity-bridge:8765/webhook'


def call(method, api_key, body=None):
    data = json.dumps(body).encode() if body is not None else None
    request = Request(URL, data=data, method=method, headers={
        'X-Api-Key': api_key, 'Content-Type': 'application/json',
    })
    with urlopen(request, timeout=30) as response:
        content = response.read()
    return json.loads(content) if content else None


def main():
    if os.geteuid() != 0:
        raise SystemExit('Run as root on mini-pc')
    original = CONFIG.read_text()
    values = dict(line.split('=', 1) for line in original.splitlines() if line)
    current = call('GET', values['SEERR_API_KEY'])
    options = current['options']
    configured_url = options.get('webhookUrl', '')
    if configured_url and configured_url != TARGET:
        raise SystemExit('Seerr already has a different webhook; not replacing it')

    token = values.get('BRIDGE_WEBHOOK_TOKEN') or secrets.token_urlsafe(48)
    if not values.get('BRIDGE_WEBHOOK_TOKEN'):
        temp = CONFIG.with_suffix('.env.tmp')
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o640)
        with os.fdopen(fd, 'w') as output:
            output.write(original.rstrip('\n') + '\nBRIDGE_WEBHOOK_TOKEN=' + token + '\n')
        stat = CONFIG.stat()
        os.chown(temp, stat.st_uid, stat.st_gid)
        os.replace(temp, CONFIG)

    options = {**options, 'webhookUrl': TARGET, 'authHeader': 'Bearer ' + token}
    call('POST', values['SEERR_API_KEY'], {
        'enabled': True, 'types': current['types'] | 2, 'options': options,
    })
    saved = call('GET', values['SEERR_API_KEY'])
    if not saved['enabled'] or not saved['types'] & 2 or saved['options']['webhookUrl'] != TARGET:
        raise RuntimeError('Seerr did not retain the webhook settings')
    print('Seerr MEDIA_PENDING webhook configured for the private bridge listener')


if __name__ == '__main__':
    main()
