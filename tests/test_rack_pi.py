from __future__ import annotations

import re
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
RACK = REPO / "rack-pi"


class RackPiArchitectureTests(unittest.TestCase):
    def read(self, relative: str) -> str:
        return (REPO / relative).read_text(encoding="utf-8")

    def test_rest_server_is_append_only_and_tailnet_bound(self) -> None:
        compose = self.read("rack-pi/compose.yaml")
        self.assertIn("OPTIONS: --append-only --private-repos", compose)
        self.assertIn("${RACK_PI_TAILSCALE_IP", compose)
        self.assertNotIn('"0.0.0.0:8000:8000', compose)
        self.assertIn('restart: "no"', compose)

    def test_homepage_never_mounts_docker_socket(self) -> None:
        compose = self.read("rack-pi/compose.yaml")
        homepage = compose.split("  homepage:", 1)[1].split("  uptime-kuma:", 1)[0]
        self.assertNotIn("/var/run/docker.sock", homepage)
        self.assertIn("docker-socket-proxy", compose)

    def test_minipc_uptime_kuma_resolves_rack_pi_fqdn(self) -> None:
        compose = self.read("compose.yaml")
        uptime_kuma = compose.split("  uptime-kuma:", 1)[1].split("networks:", 1)[0]
        env_example = self.read(".env.example")
        self.assertIn("extra_hosts:", uptime_kuma)
        self.assertIn("${RACK_PI_TAILSCALE_FQDN", uptime_kuma)
        self.assertIn("${RACK_PI_TAILSCALE_IP", uptime_kuma)
        self.assertIn("RACK_PI_TAILSCALE_FQDN=", env_example)
        self.assertIn("RACK_PI_TAILSCALE_IP=", env_example)

    def test_rack_homepage_matches_horizontal_system_layout(self) -> None:
        settings = self.read("rack-pi/config/homepage/settings.yaml")
        services = self.read("rack-pi/config/homepage/services.yaml")
        css = self.read("rack-pi/config/homepage/custom.css")
        rack_layout = settings.split("  Sistema rack:", 1)[1].split(
            "  Servizi rack:", 1
        )[0]
        self.assertIn("style: row", rack_layout)
        self.assertIn("columns: 4", rack_layout)
        self.assertIn("header: false", rack_layout)
        for card_id in (
            "rack-system-server",
            "rack-system-nas",
            "rack-system-network",
            "rack-system-backup",
        ):
            self.assertIn(f"id: {card_id}", services)
            self.assertIn(f"#{card_id} .service-block", css)
        self.assertIn("flex-direction: column-reverse", css)
        self.assertIn("#information-widgets", css)

    def test_pihole_replication_does_not_copy_dhcp_or_upstreams(self) -> None:
        compose = self.read("rack-pi/compose.yaml")
        nebula = compose.split("  nebula-sync:", 1)[1].split(
            "  docker-socket-proxy:", 1
        )[0]
        self.assertIn('FULL_SYNC: "false"', nebula)
        self.assertNotIn("SYNC_CONFIG_DHCP: \"true\"", nebula)
        self.assertIn("SYNC_CONFIG_DNS_EXCLUDE: upstreams,listeningMode", nebula)

    def test_remote_ssh_key_is_forced_and_source_restricted(self) -> None:
        installer = self.read("scripts/install-remote-backup-client.sh")
        self.assertIn('from="%s",restrict,command="/usr/bin/sudo -n %s"', installer)
        self.assertIn("Match LocalPort 2222", installer)
        self.assertIn("AllowUsers pibackup", installer)
        self.assertIn("pibackup-shell", installer)
        self.assertRegex(installer, r"NOPASSWD: %s")

    def test_photo_copy_does_not_stop_immich(self) -> None:
        photos = self.read("scripts/backup-photos.sh")
        self.assertNotIn("docker compose", photos)
        self.assertNotIn("stop immich", photos.lower())
        self.assertIn("--one-file-system", photos)
        self.assertIn("PHOTO_MEDIA_MARKER", photos)

    def test_backup_schedule_and_retention_are_scoped(self) -> None:
        timer = self.read("rack-pi/systemd/rack-backup.timer")
        self.assertIn("OnCalendar=*-*-* 04:15:00", timer)
        self.assertIn("RandomizedDelaySec=1h", timer)
        maintenance = self.read("rack-pi/scripts/repository-maintenance.sh")
        self.assertIn("--tag \"${tag}\"", maintenance)
        self.assertIn("--keep-within", maintenance)
        self.assertIn("14d 2m 1y", maintenance)
        self.assertIn("7d 1m 6m", maintenance)

    def test_minipc_legacy_timers_stay_disabled_in_rack_mode(self) -> None:
        remote_env = self.read("config/backup/remote-state-backup.env.example")
        installer = self.read("scripts/install-systemd.sh")
        self.assertIn("BACKUP_TIMER_MANAGED_EXTERNALLY=true", remote_env)
        self.assertIn("systemctl disable --now backup.timer backup-recovery.timer", installer)
        self.assertIn("BACKUP_TIMER_MANAGED_EXTERNALLY", installer)

    def test_backup_disk_check_triggers_automount_via_child_path(self) -> None:
        disk_check = self.read("rack-pi/scripts/check-backup-disk.sh")
        marker_assignment = disk_check.index(
            "marker=${BACKUP_MOUNTPOINT}/.rack-pi-restic"
        )
        marker_stat = disk_check.index('stat -- "${marker}"')
        findmnt = disk_check.index("findmnt -rn --mountpoint")
        self.assertLess(marker_assignment, marker_stat)
        self.assertLess(marker_stat, findmnt)
        self.assertIn('awk \'$2 != "autofs" { print; exit }\'', disk_check)
        self.assertNotIn('timeout 30s mount "${BACKUP_MOUNTPOINT}"', disk_check)
        self.assertIn("systemd-escape --path --suffix=mount", disk_check)

    def test_rack_phase_contains_no_nut_or_fan_runtime(self) -> None:
        runtime_files = [
            RACK / "compose.yaml",
            *sorted((RACK / "scripts").glob("*.sh")),
            *sorted((RACK / "systemd").glob("*")),
        ]
        runtime = "\n".join(path.read_text(encoding="utf-8") for path in runtime_files)
        self.assertIsNone(re.search(r"\bnut-(server|client|driver)\b", runtime, re.I))
        self.assertIsNone(re.search(r"\b(gpio|pwm|fancontrol)\b", runtime, re.I))

    def test_systemd_installer_references_existing_units(self) -> None:
        installer = self.read("rack-pi/scripts/install-systemd.sh")
        names = set(re.findall(r"rack-[a-z-]+\.(?:service|timer)", installer))
        self.assertGreaterEqual(len(names), 10)
        for name in names:
            self.assertTrue((RACK / "systemd" / name).is_file(), name)


if __name__ == "__main__":
    unittest.main()
