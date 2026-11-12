#!/usr/bin/env python3
"""Verify public Nextcloud and the restricted Office proxy without credentials."""
import argparse
import json
from pathlib import Path
import re
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]

def check_public_office(hostname):
    if not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?', hostname) or '.' not in hostname or '..' in hostname:
        raise ValueError('Expected a hostname without scheme, port or path')
    origin='https://'+hostname
    def request(path, method='GET'):
        req=urllib.request.Request(origin+path, method=method,
                                   headers={'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36'},
                                   data=b'{}' if method in ('POST','PUT') else None)
        try:
            with urllib.request.urlopen(req, timeout=20) as response:
                if not response.geturl().startswith(origin + '/'):
                    raise RuntimeError(f'Unexpected redirect off the public HTTPS hostname: {path}')
                result = response.status, response.headers, response.read()
        except urllib.error.HTTPError as error:
            result = error.code, error.headers, error.read()
        if result[1].get('CF-Cache-Status', '').upper() == 'HIT':
            raise RuntimeError(f'Cloudflare served a cached response for {path}')
        return result

    status, headers, body = request('/status.php')
    state = json.loads(body) if status == 200 else {}
    if not state.get('installed') or state.get('maintenance') or state.get('needsDbUpgrade'):
        raise RuntimeError(f'Nextcloud is unavailable or requires maintenance: HTTP {status}')
    if 'no-store' not in headers.get('Cache-Control', '').lower():
        raise RuntimeError('Nextcloud response is missing Cache-Control: no-store')
    if not headers.get('Strict-Transport-Security'):
        raise RuntimeError('Nextcloud response is missing HSTS')
    status, _, body = request('/login')
    if status != 200 or b'id="login"' not in body:
        raise RuntimeError(f'Nextcloud login form is unavailable: HTTP {status}')
    status, headers, _ = request('/remote.php/dav/', 'PROPFIND')
    if status != 401 or not headers.get('WWW-Authenticate'):
        raise RuntimeError(f'Anonymous WebDAV did not require authentication: HTTP {status}')

    for path in ['/office/web-apps/apps/api/documents/api.js',
                 '/custom_apps/onlyoffice/js/onlyoffice-main.mjs',
                 '/custom_apps/onlyoffice/templates/loader.html']:
        status, _, body=request(path)
        if status!=200 or not body:
            raise RuntimeError(f'Editor asset failed: {path}, HTTP {status}')
    private=['/office', '/office/', '/office/welcome/', '/office/example/',
             '/office/healthcheck', '/office/info/info.json',
             '/office/internal/cluster/inactive', '/office/ConvertService.ashx',
             '/office/coauthoring/CommandService.ashx',
             '/office/9.3.1-test/internal/cluster/inactive',
             '/office/9.3.1-test/info/info.json']
    for path in private:
        status, _, _=request(path)
        if status!=404:
            raise RuntimeError(f'Private route is exposed: {path}, HTTP {status}')
    for path in ('/office/web-apps/apps/api/documents/api.js', '/index.php/apps/onlyoffice/track'):
        status, _, _ = request(path, 'POST')
        if status != 404:
            raise RuntimeError(f'Unexpected POST to {path}: HTTP {status}')
    status, _, _ = request('/office/cache/files/invalid/output.docx')
    if status!=403:
        raise RuntimeError(f'Unsigned cached document must be refused, HTTP {status}')
    status, _, body = request('/ocs/v2.php/apps/onlyoffice/api/v1/config/123?shareToken=invalid&format=json')
    if status==200:
        payload=json.loads(body)
        data=payload.get('ocs',{}).get('data',payload)
        if not isinstance(data,dict) or not data.get('error') or 'document' in data or 'token' in data:
            raise RuntimeError('Invalid share returned a document configuration')
    elif status not in (401,403,404,412):
        raise RuntimeError(f'Unexpected invalid-share status: {status}')
    print('Public login and editor are available; anonymous WebDAV, internal Office routes, unsigned files and invalid shares are refused.')

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('hostname',nargs='?',help='Default: NEXTCLOUD_PUBLIC_DOMAIN in .env')
    args=parser.parse_args()
    hostname=args.hostname
    if not hostname:
        for line in (ROOT/'.env').read_text(encoding='utf8').splitlines():
            key,separator,value=line.partition('=')
            if separator and key.strip()=='NEXTCLOUD_PUBLIC_DOMAIN':
                hostname=value.strip().strip('\"\'')
                break
    if not hostname:
        parser.error('Set NEXTCLOUD_PUBLIC_DOMAIN or pass a hostname')
    check_public_office(hostname)

if __name__=='__main__':
    main()
