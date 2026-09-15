from __future__ import annotations

import importlib.util
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


REPO = Path(__file__).resolve().parents[1]


def _load_controller():
    name = "pihole_control"
    path = REPO / "scripts/pihole-control.py"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_monitoring():
    name = "homepage_monitoring"
    path = REPO / "scripts/monitoring-api.py"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class PiHoleControlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = _load_controller()

    def environment(self) -> dict[str, str]:
        return {
            "PIHOLE_CONTROL_BIND": "127.0.0.1",
            "PIHOLE_CONTROL_ALLOWED_TAILSCALE_LOGINS": "owner@example.com",
            "TAILSCALE_FQDN": "mini.example.ts.net",
            "RACK_PI_TAILSCALE_FQDN": "rack.example.ts.net",
            "RACK_PI_TAILSCALE_IP": "100.64.0.4",
            "MINIPC_PIHOLE_CONTROL_PASSWORD": "local-app-password",
            "RACK_PI_PIHOLE_CONTROL_PASSWORD": "rack-app-password",
        }

    def test_configuration_is_loopback_only_and_requires_an_identity(self) -> None:
        for changes in (
            {"PIHOLE_CONTROL_BIND": "0.0.0.0"},
            {"PIHOLE_CONTROL_ALLOWED_TAILSCALE_LOGINS": ""},
        ):
            with self.subTest(changes=changes), patch.dict(
                os.environ, {**self.environment(), **changes}, clear=True
            ), self.assertRaises(self.module.ConfigError):
                self.module.Config.from_environment()

    def test_toggle_changes_both_nodes_to_the_same_state(self) -> None:
        with patch.dict(os.environ, self.environment(), clear=True):
            controller = self.module.Controller(self.module.Config.from_environment())
        states = {"mini PC": True, "Raspberry": False}

        class FakeClient:
            def __init__(self, node):
                self.node = node

            def blocking(self):
                return states[self.node.name]

            def set_blocking(self, enabled):
                states[self.node.name] = enabled

        with patch.object(self.module, "PiHoleClient", FakeClient):
            result = controller.toggle()
        self.assertEqual(states, {"mini PC": True, "Raspberry": True})
        self.assertTrue(result["blocking"])

    def test_live_pihole_string_blocking_state_is_supported(self) -> None:
        with patch.dict(os.environ, self.environment(), clear=True):
            node = self.module.Config.from_environment().nodes[0]
        client = self.module.PiHoleClient(node)
        with patch.object(client, "_session", return_value="sid"), patch.object(
            client, "_request", side_effect=[{"blocking": "enabled"}, {}]
        ):
            self.assertTrue(client.blocking())

    def test_toggle_rolls_back_when_second_node_fails(self) -> None:
        with patch.dict(os.environ, self.environment(), clear=True):
            controller = self.module.Controller(self.module.Config.from_environment())
        states = {"mini PC": True, "Raspberry": True}

        class FakeClient:
            def __init__(self, node):
                self.node = node

            def blocking(self):
                return states[self.node.name]

            def set_blocking(self, enabled):
                if self.node.name == "Raspberry" and not enabled:
                    raise RuntimeError("rack offline")
                states[self.node.name] = enabled

        with patch.object(self.module, "PiHoleClient", FakeClient), self.assertRaises(
            RuntimeError
        ):
            controller.toggle()
        self.assertEqual(states, {"mini PC": True, "Raspberry": True})


class HomepageArchitectureTests(unittest.TestCase):
    def read(self, relative: str) -> str:
        return (REPO / relative).read_text(encoding="utf-8")

    def test_ollama_runtime_and_homepage_cards_are_removed(self) -> None:
        automation = self.read("compose.automation.yaml").lower()
        homepage = self.read("config/homepage/services.yaml").lower()
        self.assertNotIn("  ollama:", automation)
        self.assertNotIn("ollama-model-init", automation)
        self.assertNotIn("- ollama:", homepage)
        self.assertNotIn("- modello ai:", homepage)

    def test_homepage_has_raspberry_band_and_new_tab_links(self) -> None:
        homepage = self.read("config/homepage/services.yaml")
        settings = self.read("config/homepage/settings.yaml")
        self.assertIn("id: system-raspberry", homepage)
        self.assertIn("href: https://{{HOMEPAGE_VAR_RACK_PI_FQDN}}/", homepage)
        self.assertNotIn("Homepage rack-pi", self.read("config/homepage/bookmarks.yaml"))
        self.assertIn("url: http://monitoring-api:8080/raspberry", homepage)
        self.assertIn("field: services", homepage)
        self.assertIn("field: last_backup", homepage)
        self.assertIn("field: ups_charge_percent", homepage)
        self.assertIn("target: _blank", settings)

    def test_pihole_control_is_tailnet_only_and_in_network_card(self) -> None:
        javascript = self.read("config/homepage/custom.js")
        serve = self.read("scripts/configure-tailscale-serve.sh")
        unit = self.read("systemd/pihole-control.service")
        self.assertIn('#system-network', self.read("config/homepage/custom.css"))
        self.assertIn('querySelector("#system-network")', javascript)
        self.assertIn(":8456/api", javascript)
        self.assertIn("--https=8456", serve)
        self.assertIn("http://127.0.0.1:8085", serve)
        self.assertIn("PIHOLE_CONTROL_BIND", self.read("scripts/pihole-control.py"))
        self.assertIn("ProtectSystem=strict", unit)


class RaspberryStatusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = _load_monitoring()

    def test_remote_raspberry_failure_is_reported_as_offline(self) -> None:
        self.module.Metrics._last_raspberry_backup = None
        with patch.object(self.module, "RACK_PI_STATUS_URL", "https://rack:8456"), patch.object(
            self.module, "_get_json", side_effect=OSError("offline")
        ):
            self.assertEqual(
                self.module.Metrics.raspberry(),
                {
                    "status": "Offline",
                    "services": "Offline",
                    "last_backup": None,
                    "last_backup_age": "Non disponibile",
                    "ups_charge_percent": None,
                },
            )

    def test_remote_raspberry_includes_ups_charge(self) -> None:
        payload = {
            "services": "Online",
            "last_backup": "2026-09-15T04:15:00+02:00",
            "ups_charge_percent": 90,
        }
        with patch.object(
            self.module, "RACK_PI_STATUS_URL", "https://rack:8456"
        ), patch.object(self.module, "_get_json", return_value=payload):
            result = self.module.Metrics.raspberry()
        self.assertEqual(result["ups_charge_percent"], 90)
        self.assertEqual(result["status"], "Online")

    def test_all_expected_running_services_are_online(self) -> None:
        expected = ("pihole", "homepage")
        containers = [
            {
                "Labels": {"com.docker.compose.service": service},
                "State": "running",
                "Status": "Up 1 hour",
            }
            for service in expected
        ]
        with patch.object(self.module, "RACK_PI_STATUS_URL", ""), patch.object(
            self.module, "DOCKER_API_URL", "http://docker:2375"
        ), patch.object(self.module, "EXPECTED_COMPOSE_PROJECT", "rack-pi"), patch.object(
            self.module, "EXPECTED_SERVICES", expected
        ), patch.object(self.module, "_get_json", return_value=containers), patch.object(
            self.module.Metrics,
            "backup",
            return_value={"last_success": "2026-09-14T04:15:00+02:00"},
        ), patch.object(
            self.module.Metrics,
            "ups",
            return_value={"charge_percent": 90},
        ):
            self.assertEqual(
                self.module.Metrics.raspberry(),
                {
                    "status": "Online",
                    "services": "Online",
                    "last_backup": "2026-09-14T04:15:00+02:00",
                    "last_backup_age": self.module._relative_age(
                        "2026-09-14T04:15:00+02:00"
                    ),
                    "ups_charge_percent": 90,
                },
            )


if __name__ == "__main__":
    unittest.main()
