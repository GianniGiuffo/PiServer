from __future__ import annotations

import unittest
import re
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]


class VideoAutomationStackTests(unittest.TestCase):
    def read(self, relative: str) -> str:
        return (REPO / relative).read_text(encoding="utf-8")

    def test_images_are_pinned_to_reviewed_stable_releases(self) -> None:
        env = self.read(".env.example")
        expected = (
            "RADARR_IMAGE=lscr.io/linuxserver/radarr:version-6.4.4.10685",
            "SONARR_IMAGE=lscr.io/linuxserver/sonarr:version-4.0.20.3014",
            "PROWLARR_IMAGE=lscr.io/linuxserver/prowlarr:version-2.5.2.5491",
            "QBITTORRENT_IMAGE=lscr.io/linuxserver/qbittorrent:5.2.3_v2.0.14-ls476",
            "BAZARR_IMAGE=lscr.io/linuxserver/bazarr:version-v1.6.0",
        )
        for image in expected:
            self.assertIn(image, env)
        self.assertNotIn("RADARR_IMAGE=lscr.io/linuxserver/radarr:latest", env)

    def test_services_share_paths_and_bind_web_uis_only_to_loopback(self) -> None:
        compose = self.read("compose.media.yaml")
        expected_ports = {
            "radarr": "127.0.0.1:7878:7878/tcp",
            "sonarr": "127.0.0.1:8989:8989/tcp",
            "prowlarr": "127.0.0.1:9696:9696/tcp",
            "qbittorrent": "127.0.0.1:8086:8080/tcp",
            "bazarr": "127.0.0.1:6767:6767/tcp",
        }
        for service, port in expected_ports.items():
            match = re.search(
                rf"^  {service}:\n(.*?)(?=^  [a-z0-9_-]+:|\Z)",
                compose,
                flags=re.MULTILINE | re.DOTALL,
            )
            self.assertIsNotNone(match)
            block = match.group(1)
            self.assertIn(port, block)
            self.assertIn("no-new-privileges:true", block)
        for service in ("radarr", "sonarr", "qbittorrent", "bazarr"):
            match = re.search(
                rf"^  {service}:\n(.*?)(?=^  [a-z0-9_-]+:|\Z)",
                compose,
                flags=re.MULTILINE | re.DOTALL,
            )
            self.assertIsNotNone(match)
            block = match.group(1)
            self.assertIn("target: /data", block)
        self.assertNotIn("6881:6881", compose)
        self.assertNotIn("6881:6881/udp", compose)

    def test_services_are_in_lifecycle_backup_dashboard_and_tailnet(self) -> None:
        services = ("radarr", "sonarr", "prowlarr", "qbittorrent", "bazarr")
        for script in ("start-stack.sh", "stop-stack.sh", "update-images.sh"):
            content = self.read(f"scripts/{script}")
            for service in services:
                self.assertIn(service, content, f"{service} missing from {script}")

        backup = self.read("scripts/backup.sh")
        homepage = self.read("config/homepage/services.yaml")
        serve = self.read("scripts/configure-tailscale-serve.sh")
        homepage_labels = {
            "radarr": "Radarr",
            "sonarr": "Sonarr",
            "prowlarr": "Prowlarr",
            "qbittorrent": "qBittorrent",
            "bazarr": "Bazarr",
        }
        for service in services:
            self.assertIn(f'"${{DATA_DIR}}/{service}"', backup)
            self.assertIn(f"- {homepage_labels[service]}:", homepage)
        for port in range(8458, 8463):
            self.assertIn(f"--https={port}", serve)

    def test_required_media_directories_are_checked(self) -> None:
        check = self.read("scripts/check-media-mount.sh")
        for directory in (
            "downloads/Films",
            "downloads/Series",
            "downloads/.arr-downloads/complete",
            "downloads/.arr-downloads/incomplete",
        ):
            self.assertIn(directory, check)

    def test_bazarr_connector_preserves_provider_configuration(self) -> None:
        connector = self.read("scripts/configure-bazarr-arr.py")
        self.assertIn('(\"general\", \"use_radarr\"): \"true\"', connector)
        self.assertIn('(\"general\", \"use_sonarr\"): \"true\"', connector)
        self.assertIn('(\"radarr\", \"ip\"): \"radarr\"', connector)
        self.assertIn('(\"sonarr\", \"ip\"): \"sonarr\"', connector)
        self.assertNotIn("enabled_providers", connector)


if __name__ == "__main__":
    unittest.main()
