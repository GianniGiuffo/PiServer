#!/usr/bin/env python3
"""Verify public editor assets and rejection of private routes without credentials."""
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
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.read()
    for path in ['/office/web-apps/apps/api/documents/api.js',
                 '/custom_apps/onlyoffice/js/onlyoffice-main.mjs',
                 '/custom_apps/onlyoffice/templates/loader.html']:
        status, body=request(path)
        if status!=200 or not body:
            raise RuntimeError(f'Editor asset failed: {path}, HTTP {status}')
    private=['/', '/login', '/index.php/login', '/status.php', '/apps/files/',
             '/settings/admin', '/remote.php/dav/', '/apps/onlyoffice/123',
             '/ocs/v2.php/apps/onlyoffice/api/v1/config/123',
             '/office/', '/office/welcome/', '/office/example/',
             '/office/healthcheck', '/office/info/info.json',
             '/office/internal/cluster/inactive', '/office/ConvertService.ashx',
             '/office/coauthoring/CommandService.ashx',
             '/office/9.3.1-test/internal/cluster/inactive',
             '/office/9.3.1-test/info/info.json']
    for path in private:
        status, _=request(path)
        if status!=404:
            raise RuntimeError(f'Private route is exposed: {path}, HTTP {status}')
    for path,method in [('/apps/onlyoffice/ajax/new','POST'),
                        ('/apps/onlyoffice/track','POST'),
                        ('/public.php/dav/files/invalid/file.docx','PUT'),
                        ('/office/web-apps/apps/api/documents/api.js','POST')]:
        status,_=request(path,method)
        if status!=404:
            raise RuntimeError(f'Unexpected public method: {method} {path}, HTTP {status}')
    status,_=request('/office/cache/files/invalid/output.docx')
    if status!=403:
        raise RuntimeError(f'Unsigned cached document must be refused, HTTP {status}')
    status,body=request('/ocs/v2.php/apps/onlyoffice/api/v1/config/123?shareToken=invalid')
    if status==200:
        payload=json.loads(body)
        data=payload.get('ocs',{}).get('data',payload)
        if not isinstance(data,dict) or not data.get('error') or 'document' in data or 'token' in data:
            raise RuntimeError('Invalid share returned a document configuration')
    elif status not in (401,403,404,412):
        raise RuntimeError(f'Unexpected invalid-share status: {status}')
    print('Public editor assets available; private routes, public writes, unsigned files and invalid shares refused.')

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
