from __future__ import annotations

import http.client
import importlib.util
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


REPO = Path(__file__).resolve().parents[1]


def _load_controller():
    name = "gaming_pc_controller"
    path = REPO / "scripts/gaming-pc-controller.py"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class GamingControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = _load_controller()

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        for name, content in (
            ("id_ed25519", "private-test-key"),
            ("known_hosts", "100.64.0.10 ssh-ed25519 AAAATEST"),
            ("session-token", "a" * 64),
        ):
            (root / name).write_text(content, encoding="ascii")
        self.environment = {
            "GAMING_PC_MAC": "00:11:22:33:44:55",
            "GAMING_PC_BROADCAST": "192.168.1.255",
            "GAMING_PC_TAILSCALE_IP": "100.64.0.10",
            "GAMING_PC_SSH_USER": "gaming",
            "GAMING_ALLOWED_TAILSCALE_LOGINS": "owner@example.com",
            "GAMING_PC_SSH_KEY": str(root / "id_ed25519"),
            "GAMING_PC_KNOWN_HOSTS": str(root / "known_hosts"),
            "GAMING_SESSION_TOKEN_FILE": str(root / "session-token"),
            "GAMING_CONTROLLER_STATE_FILE": str(root / "state.json"),
            "GAMING_CONTROLLER_BIND": "127.0.0.1",
            "GAMING_IDLE_TIMEOUT_SECONDS": "1800",
        }

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def config(self):
        with patch.dict(os.environ, self.environment, clear=True):
            return self.module.Config.from_environment()

    def test_configuration_requires_tailnet_ip_and_loopback_bind(self) -> None:
        for key, value in (
            ("GAMING_PC_TAILSCALE_IP", "192.168.1.10"),
            ("GAMING_CONTROLLER_BIND", "0.0.0.0"),
        ):
            with self.subTest(key=key), patch.dict(
                os.environ, {**self.environment, key: value}, clear=True
            ), self.assertRaises(self.module.ConfigError):
                self.module.Config.from_environment()

    def test_wake_packet_has_only_configured_mac(self) -> None:
        controller = self.module.Controller(self.config())
        fake_socket = MagicMock()
        context = MagicMock()
        context.__enter__.return_value = fake_socket
        with patch.object(self.module, "_tcp_reachable", return_value=False), patch.object(
            self.module.socket, "socket", return_value=context
        ), patch.object(self.module.time, "sleep"):
            controller.wake("owner@example.com")
        expected = b"\xff" * 6 + bytes.fromhex("001122334455") * 16
        self.assertEqual(fake_socket.sendto.call_count, 3)
        fake_socket.sendto.assert_called_with(expected, ("192.168.1.255", 9))

    def test_shutdown_uses_fixed_command_and_pinned_host_key(self) -> None:
        config = self.config()
        controller = self.module.Controller(config)

        def reachable(_host: str, port: int, timeout: float = 0.8) -> bool:
            return port == config.ssh_port

        completed = subprocess.CompletedProcess([], 0, "scheduled", "")
        with patch.object(self.module, "_tcp_reachable", side_effect=reachable), patch.object(
            self.module.subprocess, "run", return_value=completed
        ) as run:
            controller.shutdown("owner@example.com")
        command = run.call_args.args[0]
        self.assertEqual(command[-1], "shutdown")
        self.assertIn("StrictHostKeyChecking=yes", command)
        self.assertIn(f"UserKnownHostsFile={config.known_hosts}", command)
        self.assertNotIn("shell", " ".join(command).lower())

    def test_session_timer_only_arms_for_managed_power(self) -> None:
        controller = self.module.Controller(self.config())
        controller.session(False)
        self.assertIsNone(controller.state.data["idle_since"])
        controller.state.data["managed_power"] = True
        controller.session(False)
        self.assertIsInstance(controller.state.data["idle_since"], int)
        controller.session(True)
        self.assertIsNone(controller.state.data["idle_since"])

    def test_http_actions_require_tailscale_identity_and_csrf(self) -> None:
        controller = self.module.Controller(self.config())
        handler = self.module.Handler
        handler.controller = controller
        server = self.module.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port)
            connection.request("GET", "/")
            response = connection.getresponse()
            self.assertEqual(response.status, 401)
            response.read()

            headers = {"Tailscale-User-Login": "owner@example.com"}
            connection.request("GET", "/", headers=headers)
            page = connection.getresponse()
            self.assertEqual(page.status, 200)
            self.assertIn(controller.csrf_token.encode(), page.read())

            connection.request("POST", "/api/postpone", headers=headers)
            response = connection.getresponse()
            self.assertEqual(response.status, 403)
            response.read()

            headers["X-CSRF-Token"] = controller.csrf_token
            connection.request("POST", "/api/postpone", headers=headers)
            response = connection.getresponse()
            self.assertEqual(response.status, 202)
            response.read()

            connection.request(
                "POST",
                "/api/session/start",
                headers={"Authorization": f"Bearer {controller.config.session_token}"},
            )
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            response.read()
            self.assertTrue(controller.state.data["session_active"])
            connection.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


class GamingArchitectureTests(unittest.TestCase):
    def read(self, relative: str) -> str:
        return (REPO / relative).read_text(encoding="utf-8")

    def test_controller_is_loopback_only_and_tailnet_served(self) -> None:
        example = self.read("config/gaming/gaming.env.example")
        serve = self.read("scripts/configure-tailscale-serve.sh")
        installer = self.read("scripts/install-systemd.sh")
        unit = self.read("systemd/gaming-pc-controller.service")
        self.assertIn("GAMING_CONTROLLER_BIND=127.0.0.1", example)
        self.assertIn("--https=8455", serve)
        self.assertIn("http://127.0.0.1:8084", serve)
        self.assertIn("gaming-pc-controller.service", installer)
        self.assertTrue((REPO / "systemd/gaming-pc-controller.service").is_file())
        self.assertIn("ProtectSystem=strict", unit)

    def test_windows_shutdown_is_forced_and_source_restricted(self) -> None:
        power = self.read("windows/gaming/gaming-power.ps1")
        installer = self.read("windows/gaming/install-gaming-host.ps1")
        self.assertIn('SSH_ORIGINAL_COMMAND -cne "shutdown"', power)
        self.assertIn("ForceCommand powershell.exe", installer)
        self.assertIn("PasswordAuthentication no", installer)
        self.assertIn("-RemoteAddress $MiniPcTailscaleIp.IPAddressToString", installer)
        self.assertIn('"100.64.0.0/10"', installer)
        self.assertIn("-LocalPort 47984,47989,48010", installer)

    def test_homepage_links_to_controller_without_embedding_secrets(self) -> None:
        homepage = self.read("config/homepage/services.yaml")
        self.assertIn("HOMEPAGE_VAR_TAILSCALE_FQDN}}:8455", homepage)
        self.assertNotIn("session-token", homepage)
        self.assertNotIn("id_ed25519", homepage)

    def test_tailnet_policy_documents_sunshine_callback_direction(self) -> None:
        guide = self.read("docs/cloud-gaming.md")
        self.assertIn("PC gaming → mini PC: TCP `8455`", guide)

    def test_monitoring_api_remains_read_only_and_separate(self) -> None:
        compose = self.read("compose.yaml")
        monitoring = compose.split("  monitoring-api:", 1)[1].split(
            "  homepage:", 1
        )[0]
        self.assertIn("read_only: true", monitoring)
        self.assertNotIn("gaming", monitoring.lower())
        self.assertNotIn("gaming-pc-controller.py", compose)


if __name__ == "__main__":
    unittest.main()
