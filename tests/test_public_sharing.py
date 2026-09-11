import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PublicSharingConfigTests(unittest.TestCase):
    def read(self, relative_path: str) -> str:
        return (ROOT / relative_path).read_text(encoding="utf-8")

    def service_block(self, compose: str, name: str, next_name: str) -> str:
        return compose.split(f"  {name}:", 1)[1].split(f"  {next_name}:", 1)[0]

    def test_public_domains_are_explicit_and_passed_only_to_caddy(self) -> None:
        env_example = self.read(".env.example")
        core = self.read("compose.yaml")

        self.assertIn("NEXTCLOUD_PUBLIC_DOMAIN=cloud.tommasofrancescon.it", env_example)
        self.assertIn("NAVIDROME_PUBLIC_DOMAIN=music.tommasofrancescon.it", env_example)
        self.assertIn("NEXTCLOUD_PUBLIC_DOMAIN:", core)
        self.assertIn("NAVIDROME_PUBLIC_DOMAIN:", core)

    def test_no_new_public_host_ports_are_added(self) -> None:
        core = self.read("compose.yaml")
        media = self.read("compose.media.yaml")
        caddy = self.service_block(core, "caddy", "cloudflared")
        nextcloud = self.service_block(media, "nextcloud", "nextcloud-readonly")
        navidrome = self.service_block(media, "navidrome", "aurral")

        self.assertIn('"127.0.0.1:8084:8084/tcp"', caddy)
        self.assertEqual(caddy.count('"127.0.0.1:8084:8084/tcp"'), 1)
        self.assertIn('"127.0.0.1:8082:80/tcp"', nextcloud)
        self.assertNotIn('"8082:80/tcp"', nextcloud.replace('"127.0.0.1:8082:80/tcp"', ""))
        self.assertIn('"127.0.0.1:4533:4533/tcp"', navidrome)
        self.assertNotIn('"4533:4533/tcp"', navidrome.replace('"127.0.0.1:4533:4533/tcp"', ""))

    def test_nextcloud_accepts_both_hosts_without_forcing_one(self) -> None:
        media = self.read("compose.media.yaml")
        nextcloud = self.service_block(media, "nextcloud", "nextcloud-readonly")

        self.assertIn("${TAILSCALE_FQDN", nextcloud)
        self.assertIn("${NEXTCLOUD_PUBLIC_DOMAIN", nextcloud)
        self.assertNotIn("OVERWRITEHOST:", nextcloud)
        self.assertIn("OVERWRITECLIURL: https://${NEXTCLOUD_PUBLIC_DOMAIN", nextcloud)

    def test_navidrome_shares_are_revocable_and_downloads_opt_in(self) -> None:
        media = self.read("compose.media.yaml")
        navidrome = self.service_block(media, "navidrome", "aurral")

        self.assertIn('ND_ENABLESHARING: "true"', navidrome)
        self.assertIn('ND_ENABLEDOWNLOADS: "true"', navidrome)
        self.assertIn("ND_SHAREURL: https://${NAVIDROME_PUBLIC_DOMAIN", navidrome)
        self.assertIn('ND_DEFAULTSHAREEXPIRATION: "876000h"', navidrome)
        self.assertIn('ND_DEFAULTDOWNLOADABLESHARE: "false"', navidrome)

    def test_caddy_keeps_navidrome_ui_private(self) -> None:
        caddy = self.read("Caddyfile")
        public_music = caddy.split("http://{$NAVIDROME_PUBLIC_DOMAIN}", 1)[1]

        self.assertIn("method GET HEAD OPTIONS", public_music)
        self.assertIn("path /share /share/*", public_music)
        self.assertIn("reverse_proxy navidrome:4533", public_music)
        self.assertIn("respond 404", public_music)

    def test_caddy_exposes_only_nextcloud_public_share_routes(self) -> None:
        caddy = self.read("Caddyfile")
        public_cloud = caddy.split("http://{$NEXTCLOUD_PUBLIC_DOMAIN}", 1)[1].split(
            "http://{$NAVIDROME_PUBLIC_DOMAIN}", 1
        )[0]

        self.assertIn("path /s/* /index.php/s/*", public_cloud)
        self.assertIn("/public.php/dav/files/*", public_cloud)
        self.assertIn("/index.php/apps/files_sharing/publicpreview/*", public_cloud)
        self.assertIn("@share_assets", public_cloud)
        self.assertIn("respond 404", public_cloud)
        self.assertNotIn("path /login", public_cloud)
        self.assertNotIn("path /remote.php", public_cloud)
        share_data = public_cloud.split("@share_data", 1)[1].split("}", 1)[0]
        self.assertNotIn("PUT", share_data)

    def test_tailnet_proxy_rewrites_only_share_api_urls(self) -> None:
        caddy = self.read("Caddyfile")
        serve = self.read("scripts/configure-tailscale-serve.sh")
        private_cloud = caddy.split("http://:8084", 1)[1].split(
            "http://{$NEXTCLOUD_PUBLIC_DOMAIN}", 1
        )[0]

        self.assertIn("/ocs/v2.php/apps/files_sharing/api/v1/shares*", private_cloud)
        self.assertIn("header_up Host {$NEXTCLOUD_PUBLIC_DOMAIN}", private_cloud)
        self.assertIn("handle {", private_cloud)
        self.assertIn("http://127.0.0.1:8084", serve)

    def test_configurator_preserves_domains_and_safe_share_defaults(self) -> None:
        script = self.read("scripts/configure-public-sharing.sh")

        self.assertIn('source "${SCRIPT_DIR}/read-stack-path.sh"', script)
        self.assertNotIn("source \"${STACK_ENV}\"", script)
        self.assertIn('config:system:delete overwritehost', script)
        self.assertIn('config:system:get trusted_domains', script)
        self.assertIn('shareapi_enforce_links_password --value=no', script)
        self.assertIn('shareapi_default_expire_date --value=no', script)
        self.assertIn('shareapi_allow_public_upload --value=no', script)
        self.assertIn('auth.bruteforce.protection.enabled', script)


if __name__ == "__main__":
    unittest.main()
