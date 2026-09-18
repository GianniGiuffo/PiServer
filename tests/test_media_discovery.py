from __future__ import annotations

import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]


class MediaDiscoveryStackTests(unittest.TestCase):
    def read(self, relative: str) -> str:
        return (REPO / relative).read_text(encoding="utf-8")

    def test_images_are_pinned_to_reviewed_stable_releases(self) -> None:
        env = self.read(".env.example")
        self.assertIn("JELLYFIN_IMAGE=jellyfin/jellyfin:12.1", env)
        self.assertIn("SEERR_IMAGE=ghcr.io/seerr-team/seerr:v3.4.1", env)
        self.assertNotIn("SEERR_IMAGE=ghcr.io/seerr-team/seerr:latest", env)

    def test_seerr_is_persistent_hardened_and_loopback_only(self) -> None:
        compose = self.read("compose.media.yaml")
        seerr = compose.split("  seerr:", 1)[1].split("  streamingcommunity:", 1)[0]
        self.assertIn("${DATA_DIR:?Set DATA_DIR in .env}/seerr:/app/config", seerr)
        self.assertIn('127.0.0.1:5055:5055/tcp', seerr)
        self.assertIn("http://127.0.0.1:5055/api/v1/settings/public", seerr)
        self.assertIn("no-new-privileges:true", seerr)
        self.assertIn("cap_drop:", seerr)
        self.assertIn("- ALL", seerr)
        self.assertNotIn('"0.0.0.0:5055', seerr)

    def test_seerr_is_in_media_lifecycle_and_consistent_backup(self) -> None:
        for script in ("start-stack.sh", "stop-stack.sh", "update-images.sh"):
            self.assertIn("seerr", self.read(f"scripts/{script}"), script)
        backup = self.read("scripts/backup.sh")
        self.assertIn("SEERR_STOPPED", backup)
        self.assertIn('${DATA_DIR}/seerr', backup)
        self.assertIn("JELLYFIN_FULL_BACKUP", backup)

    def test_seerr_is_tailnet_only_and_shown_with_media(self) -> None:
        homepage = self.read("config/homepage/services.yaml")
        media = homepage.split("- Media e file:", 1)[1].split("- Musica:", 1)[0]
        self.assertIn("- Seerr:", media)
        self.assertIn("HOMEPAGE_VAR_TAILSCALE_FQDN}}:8457", media)
        self.assertIn("http://seerr:5055/api/v1/settings/public", media)
        serve = self.read("scripts/configure-tailscale-serve.sh")
        self.assertIn("--https=8457", serve)
        self.assertIn("http://127.0.0.1:5055", serve)

    def test_helper_installer_is_version_and_checksum_pinned(self) -> None:
        installer = self.read("scripts/install-jellyfin-helper.sh")
        self.assertIn("PLUGIN_VERSION=3.0.0.2", installer)
        self.assertIn(
            "PLUGIN_SHA256=692d108b71e3755471aa6d2ffa0f475bbc93f21dd069270b648105e9fecdf025",
            installer,
        )
        self.assertIn("PLUGIN_MD5=974ff1d2c486431f2cac0b9a79e9d2e6", installer)
        self.assertIn("TRANSFORMATION_VERSION=3.0.1.0", installer)
        self.assertIn(
            "TRANSFORMATION_SHA256=c1318b2438f4c0dbfd46850bcbd3a5c18ecaf6f873a4790318693e0d3dbaa7b3",
            installer,
        )
        self.assertIn("TRANSFORMATION_MD5=1451642c8dc6f036cb00aa703a9f0834", installer)
        self.assertIn(
            "PLUGIN_SOURCE_SHA256=cfb9c2daf321590cf924eeba6922c342e5d3647cbf32d62f2dea8bade8a8e4c8",
            installer,
        )
        self.assertIn("PATCH_LEVEL=italian-react-discovery-4", installer)
        self.assertIn("NEWTONSOFT_VERSION=13.0.1", installer)
        self.assertIn(
            "NEWTONSOFT_SHA256=2b6b52556e27e1b7913f33eedeb95568110c746bd64afff74357f1683878323a",
            installer,
        )
        self.assertIn("discovery-sidebar-${PLUGIN_VERSION}.js", installer)
        self.assertIn("TmdbGenreMap-${PLUGIN_VERSION}.cs", installer)
        self.assertIn("Plugin-${PLUGIN_VERSION}.cs", installer)
        self.assertIn(
            '"internal const int MaxVisiblePerUser = 10;": "internal const int MaxVisiblePerUser = 40;"',
            installer,
        )
        self.assertIn(
            '"private const int MaxPoolPerUser = 20;": "private const int MaxPoolPerUser = 40;"',
            installer,
        )
        self.assertIn(
            '"private const int CreditsEnrichmentBudget = 20;": "private const int CreditsEnrichmentBudget = 40;"',
            installer,
        )
        self.assertIn("server_version} != 12.*", installer)
        self.assertIn("rolling back the plugin installation", installer)

    def test_helper_rewrites_only_the_docker_seerr_url_for_browsers(self) -> None:
        sidebar = self.read("patches/jellyfin-helper/discovery-sidebar-3.0.0.2.js")
        self.assertIn("function resolveSeerrBrowserUrl(configuredUrl)", sidebar)
        self.assertIn("configured.hostname.toLowerCase() !== 'seerr'", sidebar)
        self.assertIn("publicUrl.port = '8457'", sidebar)
        self.assertIn("_seerrBaseUrl = resolveSeerrBrowserUrl(data.SeerrUrl)", sidebar)


if __name__ == "__main__":
    unittest.main()
