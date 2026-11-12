import http.client
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


ROOT = Path(__file__).resolve().parents[1]
CADDY = os.environ.get("CADDY_TEST_BIN") or shutil.which("caddy")


class Origin(BaseHTTPRequestHandler):
    def respond(self):
        body = json.dumps({
            "path": self.path,
            "method": self.command,
            "headers": dict(self.headers),
        }).encode()
        self.send_response(200)
        self.send_header("Cache-Control", "public, max-age=60")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_GET = do_POST = do_PROPFIND = respond

    def log_message(self, *args):
        pass


@unittest.skipUnless(CADDY, "Caddy is not installed; set CADDY_TEST_BIN to run the proxy checks")
class NextcloudProxyTests(unittest.TestCase):
    def setUp(self):
        self.origin = ThreadingHTTPServer(("127.0.0.1", 0), Origin)
        self.addCleanup(self.origin.server_close)
        thread = threading.Thread(target=self.origin.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.origin.shutdown)
        self.workdir = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def start_caddy(self, enabled, tunnel_peer="127.0.0.1"):
        with socket.socket() as public, socket.socket() as tailnet:
            public.bind(("127.0.0.1", 0))
            tailnet.bind(("127.0.0.1", 0))
            self.public_port = public.getsockname()[1]
            self.tailnet_port = tailnet.getsockname()[1]
        config = (ROOT / "Caddyfile").read_text(encoding="utf8")
        # Run the actual listeners on loopback with HTTP test doubles in
        # place of Docker backends. Set the expected tunnel peer per test.
        config = (config.replace("auto_https off", "auto_https off\n\tadmin off\n\tpersist_config off\n\tdefault_bind 127.0.0.1")
                  .replace("http://:80 {", f"http://:{self.public_port} {{")
                  .replace("http://:8084 {", f"http://:{self.tailnet_port} {{")
                  .replace("http://:8083 {", "http://:0 {")
                  .replace("}:8089 {", "}:0 {")
                  .replace("http://{$NEXTCLOUD_PUBLIC_DOMAIN} {",
                           f"http://{{$NEXTCLOUD_PUBLIC_DOMAIN}}:{self.public_port} {{")
                  .replace("remote_ip 10.203.253.2", f"remote_ip {tunnel_peer}")
                  .replace("/data/security-access.jsonl", (self.workdir / "access.jsonl").as_posix())
                  .replace("nextcloud-origin:80", f"127.0.0.1:{self.origin.server_port}")
                  .replace("onlyoffice:80", f"127.0.0.1:{self.origin.server_port}"))
        env = dict(os.environ, SITE_1_DOMAIN="site.example.test:0", SITE_2_DOMAIN="site2.example.test:0",
                   NAVIDROME_PUBLIC_DOMAIN="music.example.test:0", PENPOT_PUBLIC_DOMAIN="penpot.example.test",
                   NEXTCLOUD_PUBLIC_DOMAIN="cloud.example.test", NEXTCLOUD_PUBLIC_ENABLED=enabled)
        path = self.workdir / "Caddyfile"
        path.write_text(config, encoding="utf8")
        log = self.enterContext((self.workdir / "caddy.log").open("wb"))
        caddy = subprocess.Popen([CADDY, "run", "--config", str(path), "--adapter", "caddyfile"],
                                 env=env, stdout=log, stderr=subprocess.STDOUT)
        def stop():
            if caddy.poll() is None:
                caddy.terminate()
            caddy.wait(timeout=5)
        self.addCleanup(stop)
        for _ in range(100):
            if caddy.poll() is not None:
                break
            try:
                with socket.create_connection(("127.0.0.1", self.public_port), timeout=0.2):
                    return
            except OSError:
                time.sleep(0.05)
        self.fail((self.workdir / "caddy.log").read_text(encoding="utf8"))

    def request(self, path, *, method="GET", port=None, **headers):
        connection = http.client.HTTPConnection("127.0.0.1", port or self.public_port,
                                                timeout=3)
        try:
            connection.request(method, path, headers={"Host": "cloud.example.test", **headers})
            response = connection.getresponse()
            return response.status, response.headers, response.read()
        finally:
            connection.close()

    def test_public_application_only_uses_authenticated_tunnel_peer(self):
        self.start_caddy("true")
        edge = {"CF-Connecting-IP": "2001:db8::50"}
        for method, path in (("GET", "/login"), ("GET", "/s/existing"), ("PROPFIND", "/remote.php/dav/")):
            status, headers, body = self.request(path, method=method, **edge, **{
                "X-Forwarded-For": "192.0.2.123", "X-Forwarded-Proto": "http",
                "X-Forwarded-Host": "spoof.example.test", "X-Real-IP": "192.0.2.123",
            })
            self.assertEqual(status, 200)
            self.assertEqual(headers["Cache-Control"], "private, no-store")
            self.assertIn("max-age=", headers["Strict-Transport-Security"])
            forwarded = json.loads(body)
            self.assertEqual((forwarded["method"], forwarded["path"]), (method, path))
            sent = {key.lower(): value for key, value in forwarded["headers"].items()}
            self.assertEqual(sent["x-forwarded-for"], "2001:db8::50")
            self.assertEqual(sent["x-forwarded-proto"], "https")
            self.assertEqual(sent["x-forwarded-host"], "cloud.example.test")
            self.assertNotIn("x-real-ip", sent)
        self.assertEqual(self.request("/login")[0], 404)
        self.assertEqual(self.request("/login", **{"CF-Connecting-IP": "192.0.2.1, 192.0.2.2"})[0], 404)
        status, headers, _ = self.request("/.well-known/caldav", **edge)
        self.assertEqual((status, headers["Location"]), (301, "/remote.php/dav/"))
        self.assertEqual(self.request("/office/healthcheck", **edge)[0], 404)
        self.assertEqual(self.request("/index.php/apps/onlyoffice/track", method="POST", **edge)[0], 404)

    def test_other_docker_peers_cannot_forge_the_tunnel_header(self):
        self.start_caddy("true", tunnel_peer="127.0.0.2")
        edge = {"CF-Connecting-IP": "192.0.2.50"}
        self.assertEqual(self.request("/login", **edge)[0], 404)
        self.assertEqual(self.request("/office/web-apps/apps/api/documents/api.js", **edge)[0], 404)

    def test_disabled_public_ui_keeps_tailnet_and_onlyoffice_allowlist(self):
        self.start_caddy("false")
        edge = {"CF-Connecting-IP": "192.0.2.50"}
        self.assertEqual(self.request("/login", **edge)[0], 404)
        path = "/ocs/v2.php/apps/files_sharing/api/v1/shares"
        status, _, body = self.request(path, port=self.tailnet_port, Host="mini.example.test:8445")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["headers"]["Host"], "mini.example.test:8445")
        asset = "/office/web-apps/apps/api/documents/api.js"
        status, _, body = self.request(asset, **edge)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["path"], asset.removeprefix("/office"))
        for method, path in (("GET", "/office"), ("GET", "/office/healthcheck"), ("POST", asset)):
            self.assertEqual(self.request(path, method=method, **edge)[0], 404)


if __name__ == "__main__":
    unittest.main()
