from __future__ import annotations

import configparser
import importlib.util
import json
import os
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch, MagicMock
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CONFIG = load("cockpit_config", "scripts/configure-cockpit.py")
COLLECT = load("cockpit_collect", "scripts/collect-cockpit-status.py")
API = load("cockpit_api", "scripts/monitoring-api.py")
FQDN = "mini-pc.example.ts.net"


class CockpitConfigurationTests(unittest.TestCase):
    def test_config_preserves_other_settings_and_denied_users_and_is_repeatable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "cockpit.conf").write_text("[WebService]\nLoginTitle = Private\n[Session]\nIdleTimeout = 20\n")
            (root / "disallowed-users").write_text("# Existing policy\nbackup\n")
            CONFIG.configure(root, FQDN, "tommaso")
            first = (root / "cockpit.conf").read_text()
            CONFIG.configure(root, FQDN, "tommaso")
            self.assertEqual(first, (root / "cockpit.conf").read_text())
            config = configparser.ConfigParser()
            config.read(root / "cockpit.conf")
            self.assertEqual(config["WebService"]["Origins"], f"https://{FQDN}:8465")
            self.assertEqual(config["WebService"]["LoginTitle"], "Private")
            self.assertEqual(config["Session"]["IdleTimeout"], "20")
            self.assertEqual((root / "disallowed-users").read_text().splitlines().count("root"), 1)
            self.assertIn("backup", (root / "disallowed-users").read_text())

    def test_disallowed_login_fails_without_rewriting_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "disallowed-users").write_text("tommaso\n")
            with self.assertRaises(ValueError):
                CONFIG.configure(root, FQDN, "tommaso")
            self.assertFalse((root / "cockpit.conf").exists())

    def test_funnel_and_occupied_ports_are_rejected(self):
        for payload in (
            {"AllowFunnel": {f"{FQDN}:8465": True}},
            {"Web": {f"{FQDN}:8465": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:9999"}}}}},
            {"TCP": {"8465": {"TCPForward": "127.0.0.1:9999"}}},
        ):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                CONFIG.check_serve(payload, FQDN)
        CONFIG.check_serve({"Web": {f"{FQDN}:443": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:3000"}}}}}, FQDN)

    def test_first_install_binds_socket_before_package_activation(self):
        installer = (ROOT / "scripts/install-cockpit-files.sh").read_text()
        self.assertLess(installer.index("/etc/systemd/system/cockpit.socket.d/listen.conf"), installer.index("apt-get install"))
        override = (ROOT / "config/cockpit/listen.conf").read_text()
        self.assertIn("ListenStream=\nListenStream=127.0.0.1:9090", override)
        self.assertNotIn("serve reset", installer)


class CockpitCollectorTests(unittest.TestCase):
    def test_healthy_ping_cannot_hide_missing_browser_shell(self):
        route = {"TCP": {"8465": {"HTTPS": True}}, "Web": {f"{FQDN}:8465": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:9090"}}}}}
        response = MagicMock()
        response.__enter__.return_value = response
        response.status = 200
        response.read.return_value = b'{"service":"cockpit"}'
        with patch.object(COLLECT, "Path") as paths, patch.object(COLLECT, "urlopen", return_value=response), patch.object(
            COLLECT, "command", side_effect=["active", json.dumps(route), "LISTEN 0 4096 127.0.0.1:9090 0.0.0.0:*"]
        ), patch.object(COLLECT, "processes", return_value={}), patch.object(
            COLLECT.os, "statvfs", return_value=SimpleNamespace(f_blocks=100, f_frsize=1024, f_bavail=50), create=True
        ), patch.object(COLLECT.os, "sysconf", return_value=100, create=True), patch.object(COLLECT.time, "sleep"):
            paths.return_value.read_text.return_value = '{"tools":{"index":{}}}'
            paths.return_value.is_file.return_value = False
            self.assertEqual(COLLECT.collect(FQDN)["color"], "red")

    def test_missing_failed_unknown_and_complete_checks(self):
        self.assertEqual(COLLECT.classify({"socket": True, "web": True}, True)[0], "green")
        self.assertEqual(COLLECT.classify({"socket": False, "web": None}, False)[0], "red")
        self.assertEqual(COLLECT.classify({"socket": True, "web": None}, True)[0], "yellow")
        self.assertEqual(COLLECT.classify({"socket": True}, False)[0], "yellow")

    def test_route_requires_https_exact_backend_and_no_funnel(self):
        payload = {
            "TCP": {"8465": {"HTTPS": True}},
            "Web": {f"{FQDN}:8465": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:9090"}}}},
        }
        self.assertTrue(COLLECT.private_route(payload, FQDN))
        payload["AllowFunnel"] = {f"{FQDN}:8465": True}
        self.assertFalse(COLLECT.private_route(payload, FQDN))
        self.assertFalse(COLLECT.private_route({}, FQDN))

    def test_public_and_mixed_listeners_fail(self):
        self.assertTrue(COLLECT.loopback_listener("LISTEN 0 4096 127.0.0.1:9090 0.0.0.0:*"))
        self.assertFalse(COLLECT.loopback_listener(""))
        self.assertFalse(COLLECT.loopback_listener("LISTEN 0 4096 0.0.0.0:9090 0.0.0.0:*"))
        self.assertFalse(COLLECT.loopback_listener("LISTEN 0 4096 127.0.0.1:9090 0.0.0.0:*\nLISTEN 0 4096 [::]:9090 [::]:*"))

    def test_cpu_is_normalized_and_pid_reuse_does_not_create_a_spike(self):
        before = {(10, 1): (100, 1000), (20, 1): (200, 1000)}
        after = {(10, 1): (200, 1500), (20, 2): (9999, 2000)}
        self.assertEqual(COLLECT.usage(before, after, 1, 100, 4), (25.0, 3500))
        self.assertEqual(COLLECT.usage({}, {}, 1, 100, 4), (0.0, 0))

    def test_python_bridge_is_counted_but_unrelated_arguments_are_not(self):
        with tempfile.TemporaryDirectory() as directory:
            proc = Path(directory)
            for pid, argv in (
                (10, b"/usr/bin/python3\0/usr/bin/cockpit-bridge\0"),
                (20, b"/usr/bin/python3\0/tmp/editor.py\0/usr/bin/cockpit-bridge\0"),
            ):
                root = proc / str(pid)
                root.mkdir()
                (root / "comm").write_text("python3\n")
                (root / "cmdline").write_bytes(argv)
                fields = ["0"] * 22
                fields[0], fields[11], fields[12], fields[19], fields[21] = "S", "10", "20", "100", "2"
                (root / "stat").write_text(f"{pid} (python3) " + " ".join(fields))
            with patch.object(COLLECT.os, "sysconf", return_value=4096, create=True):
                self.assertEqual(COLLECT.processes(proc), {(10, 100): (30, 8192)})

    def test_snapshot_replaces_existing_file_and_leaves_no_temporary_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cockpit.json"
            path.write_text("{}")
            COLLECT.write_snapshot(path, {"color": "red"})
            self.assertEqual(json.loads(path.read_text()), {"color": "red"})
            self.assertEqual(list(Path(directory).iterdir()), [path])


class CockpitApiTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "cockpit.json"
        self.patcher = patch.object(API, "COCKPIT_STATUS_FILE", self.path)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def write(self, **changes):
        payload = {
            "color": "green", "updated_at": time.time(), "cpu_percent": 1.5,
            "memory_bytes": 1024, "free_bytes": 2048, "used_percent": 30,
            "secret": "must never be exposed",
        }
        payload.update(changes)
        self.path.write_text(json.dumps(payload))

    def test_absent_invalid_old_and_future_snapshots_are_yellow_without_metrics(self):
        self.assertEqual(API.Metrics.cockpit()["status"], "Da configurare")
        for contents in ("broken", "[]"):
            self.path.write_text(contents)
            self.assertEqual(API.Metrics.cockpit()["color"], "yellow")
        for updated in (time.time() - 46, time.time() + 60, float("nan"), True):
            self.write(updated_at=updated)
            result = API.Metrics.cockpit()
            self.assertEqual(result["color"], "yellow")
            self.assertIsNone(result["cpu_percent"])

    def test_only_valid_selected_fields_are_exposed(self):
        self.write(status="untrusted", memory_bytes=-1)
        result = API.Metrics.cockpit()
        self.assertEqual(result["color"], "yellow")
        self.assertIsNone(result["memory_bytes"])
        self.assertNotIn("secret", result)
        self.assertEqual(result["cpu_percent"], 1.5)
        self.write(color=[])
        self.assertEqual(API.Metrics.cockpit()["color"], "yellow")
        self.write(color="red")
        self.assertEqual(API.Metrics.cockpit()["status"], "Non disponibile")

    def test_http_health_reports_green_only_for_fresh_complete_data_and_supports_head(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), API.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_port}/cockpit/health"
            for color in ("green", "yellow", "red"):
                self.write(color=color)
                for method in ("GET", "HEAD"):
                    with self.subTest(color=color, method=method):
                        try:
                            response = urlopen(Request(url, method=method), timeout=2)
                        except HTTPError as error:
                            response = error
                        with response:
                            self.assertEqual(response.status, 200 if color == "green" else 503)
                            data = response.read()
                            if method == "HEAD":
                                self.assertEqual(data, b"")
                            else:
                                self.assertNotIn(b"must never", data)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
