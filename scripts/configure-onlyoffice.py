#!/usr/bin/env python3
"""Configure the Nextcloud connector without passing the JWT in argv or logs."""
from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    values = {}
    for line in (ROOT / ".env").read_text(encoding="utf8").splitlines():
        key, separator, value = line.partition("=")
        if separator and not key.startswith("#"):
            values[key.strip()] = value.strip().strip("\"'")
    hostname = values.get("NEXTCLOUD_PUBLIC_DOMAIN", "")
    secret = values.get("ONLYOFFICE_JWT_SECRET", "")
    if (not re.fullmatch(r"[a-zA-Z0-9](?:[a-zA-Z0-9.-]*[a-zA-Z0-9])?", hostname)
            or "." not in hostname or ".." in hostname):
        raise SystemExit("Set a valid NEXTCLOUD_PUBLIC_DOMAIN hostname in .env first.")
    if not re.fullmatch(r"[a-fA-F0-9]{64,}", secret):
        raise SystemExit("Set ONLYOFFICE_JWT_SECRET with openssl rand -hex 32.")

    compose = ["docker", "compose", "--project-directory", str(ROOT),
               "-f", str(ROOT / "compose.yaml"),
               "-f", str(ROOT / "compose.media.yaml")]
    execute = compose + ["exec", "-T", "--user", "www-data", "nextcloud", "php"]
    apps = json.loads(subprocess.check_output(execute + ["occ", "app:list", "--output=json"]))
    if "onlyoffice" not in apps.get("enabled", {}):
        command = "app:enable" if "onlyoffice" in apps.get("disabled", {}) else "app:install"
        subprocess.run(execute + ["occ", command, "onlyoffice"], check=True)

    settings = {
        "DocumentServerUrl": f"https://{hostname}/office/",
        "DocumentServerInternalUrl": "http://onlyoffice/",
        "StorageUrl": "http://nextcloud/",
        "jwt_secret": secret,
        "jwt_header": "AuthorizationJwt",
        "verify_peer_off": "false",
    }
    # Only fixed PHP code is passed as an argument. The secret travels over
    # stdin and is stored in Nextcloud's existing backed-up PostgreSQL database.
    php = r'''
define('OC_CONSOLE', true);
require '/var/www/html/lib/base.php';
$settings = json_decode(stream_get_contents(STDIN), true, 512, JSON_THROW_ON_ERROR);
$config = \OC::$server->get(\OCP\IConfig::class);
foreach ($settings as $key => $value) {
    $config->setAppValue('onlyoffice', $key, $value);
}
$office = $config->getSystemValue('onlyoffice', []);
$office['allow_local_address'] = true;
$config->setSystemValue('onlyoffice', $office);
$domains = $config->getSystemValue('trusted_domains', []);
if (!in_array('nextcloud', $domains, true)) {
    $domains[] = 'nextcloud';
    $config->setSystemValue('trusted_domains', $domains);
}
echo "ONLYOFFICE connector configured.\n";
'''
    subprocess.run(execute + ["-r", php], input=json.dumps(settings), text=True, check=True)
    subprocess.run(execute + ["occ", "onlyoffice:documentserver", "--check"], check=True)


if __name__ == "__main__":
    main()
