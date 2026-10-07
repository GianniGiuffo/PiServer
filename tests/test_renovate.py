from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "rack_renovate", ROOT / "rack-pi/scripts/run-renovate.py"
)
renovate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(renovate)


class RenovateTests(unittest.TestCase):
    def test_homepage_summary_is_public_and_excludes_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "renovate.json"
            path.write_text(json.dumps({"token": "SECRET", "open_prs": 7}),
                            encoding="utf-8")
            with patch.object(renovate, "STATUS_FILE", path):
                renovate.publish_status("Completato", open_prs=3, updates=5)
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "Completato")
            self.assertEqual(payload["open_prs"], 3)
            self.assertEqual(payload["updates"], 5)
            self.assertNotIn("SECRET", json.dumps(payload))
            self.assertTrue(payload["last_run"])
            self.assertRegex(payload["last_run_display"], r"\d{2}/\d{2} \d{2}:\d{2}")

    def test_running_status_retains_last_result_without_claiming_new_pr_count(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "renovate.json"
            with patch.object(renovate, "STATUS_FILE", path):
                renovate.publish_status("Completato", open_prs=3, updates=5)
                last = json.loads(path.read_text(encoding="utf-8"))["last_run"]
                renovate.publish_status("In corso")
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["last_run"], last)
            self.assertEqual(payload["open_prs"], 3)

    def test_monitoring_api_serves_only_public_summary_fields(self):
        api_spec = importlib.util.spec_from_file_location(
            "renovate_monitoring", ROOT / "scripts/monitoring-api.py"
        )
        api = importlib.util.module_from_spec(api_spec)
        api_spec.loader.exec_module(api)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "renovate.json"
            with patch.object(api, "RENOVATE_STATUS_FILE", path):
                self.assertEqual(api.Metrics.renovate()["status"], "Da configurare")
                path.write_text(json.dumps({"status": "Completato", "open_prs": 2,
                                            "token": "SECRET"}), encoding="utf-8")
                response = api.Metrics.renovate()
            self.assertEqual(response["open_prs"], 2)
            self.assertNotIn("SECRET", json.dumps(response))

    def test_manager_covers_every_minipc_image_and_both_existing_digests(self):
        config = json.loads((ROOT / "renovate.json").read_text(encoding="utf-8"))
        source = (ROOT / ".env.example").read_text(encoding="utf-8")
        # Execute the actual ECMAScript capture expression, including adjacent lines.
        result = subprocess.run(
            ["node", "-e",
             "const c=JSON.parse(process.argv[1]); const s=process.argv[2];"
             "console.log(JSON.stringify([...s.matchAll(new RegExp("
             "c.customManagers[0].matchStrings[0],'g'))].map(m=>m.groups)));",
             json.dumps(config), source],
            check=True, capture_output=True, text=True,
        )
        deps = json.loads(result.stdout)
        used = set()
        for filename in ("compose.yaml", "compose.media.yaml", "compose.automation.yaml"):
            used.update(re.findall(r"image: \$\{([A-Z0-9_]+_IMAGE)",
                                   (ROOT / filename).read_text(encoding="utf-8")))
        self.assertEqual(used, {dep["depType"] for dep in deps})
        digests = {dep["depType"] for dep in deps if dep.get("currentDigest")}
        self.assertEqual(digests, {"IMMICH_POSTGRES_IMAGE", "IMMICH_REDIS_IMAGE"})
        self.assertEqual(len(deps), len(used))
        self.assertTrue(all("sha256:" not in dep["currentValue"] for dep in deps))

    def log_record(self):
        return {
            "repository": renovate.REPOSITORY,
            "msg": "packageFiles with updates",
            "config": {"custom.regex": [{"deps": [
                {"depName": renovate.PATCHED_IMAGE, "depType": "AURRAL_IMAGE",
                 "currentValue": "2.10.0",
                 "updates": [{"newValue": "2.11.0", "updateType": "minor"}]},
                {"depName": "example/rolling", "currentValue": "latest",
                 "updates": [{"newValue": "latest", "newDigest": "sha256:abc",
                              "updateType": "digest"}]},
                {"depName": "example/pinned", "currentValue": "1",
                 "updates": [{"newValue": "1", "newDigest": "sha256:def",
                              "updateType": "pinDigest"}]},
            ]}]},
        }

    def test_release_parser_distinguishes_release_build_and_initial_pin(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "log.json"
            log.write_text("invalid\n" + json.dumps(self.log_record()), encoding="utf-8")
            messages = list(renovate.update_events(log).values())
        self.assertEqual(len(messages), 3)
        self.assertIn("Nuova versione", messages[0])
        self.assertIn("patch e mount", messages[0])
        self.assertIn("Nuova build", messages[1])
        self.assertIn("non una nuova versione", messages[2])

    def test_missing_lookup_is_an_error_not_silent_success(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "log.json"
            log.write_text(json.dumps({"msg": "other"}), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "Lookup"):
                renovate.update_events(log)

    def test_successful_delivery_survives_restart_and_does_not_repeat(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            state = renovate.read_state(path)
            with patch.object(renovate, "send_telegram") as send:
                renovate.notify_events({"one": "Nuova versione"}, state, path)
                renovate.notify_events({"one": "Nuova versione"},
                                       renovate.read_state(path), path)
            send.assert_called_once()

    def test_failed_delivery_is_retried_without_acknowledging_unsent_events(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            state = renovate.read_state(path)
            events = {"one": "x" * 2000, "two": "y" * 2000}
            with patch.object(renovate, "send_telegram",
                              side_effect=[None, RuntimeError("Offline")]):
                with self.assertRaisesRegex(RuntimeError, "Offline"):
                    renovate.notify_events(events, state, path)
            stored = renovate.read_state(path)
            self.assertEqual(stored["seen"], {"one": True})
            with patch.object(renovate, "send_telegram") as send:
                renovate.notify_events(events, stored, path)
            self.assertEqual(send.call_count, 1)
            self.assertEqual(renovate.read_state(path)["seen"], {"one": True, "two": True})

    def pr(self, number=1, branch="renovate/example", repo=None):
        return {"number": number, "title": "Update image to v2", "body": "proposal",
                "html_url": f"https://github.com/{renovate.REPOSITORY}/pull/{number}",
                "head": {"ref": branch, "repo": {"full_name": repo or renovate.REPOSITORY},
                         "sha": "old"},
                "base": {"ref": "master"}}

    def test_github_pagination_filters_forks_and_other_branches(self):
        first = [self.pr(i) for i in range(100)]
        with patch.object(renovate, "request_json", side_effect=[
                first, [self.pr(100), self.pr(101, branch="feature/test"),
                        self.pr(102, repo="someone/fork")]]) as api:
            result = renovate.open_pull_requests("secret")
        self.assertEqual(len(result), 101)
        self.assertIn("page=2", api.call_args_list[1].args[0])

    def test_rebase_is_quiet_but_changed_proposal_notifies(self):
        pr = self.pr()
        before = renovate.pr_events([pr])
        pr["head"]["sha"] = "rebased"
        self.assertEqual(before, renovate.pr_events([pr]))
        pr["title"] = "Update image to v3"
        self.assertNotEqual(before, renovate.pr_events([pr]))

    def test_api_errors_do_not_expose_telegram_token(self):
        url = "https://api.telegram.org/botSECRET/sendMessage"
        with patch.object(renovate, "urlopen",
                          side_effect=HTTPError(url, 403, "Forbidden", {}, None)):
            with self.assertRaises(RuntimeError) as caught:
                renovate.request_json(url, payload={"text": "hello"})
        self.assertNotIn("SECRET", str(caught.exception))

    def test_container_receives_only_github_secret_and_no_deploy_access(self):
        args = renovate.docker_command(ROOT, "ghcr.io/renovatebot/renovate:44.143.0", True)
        text = " ".join(args)
        self.assertIn("--dry-run=full", args)
        self.assertIn("--automerge=false", args)
        self.assertIn("--auto-approve=false", args)
        self.assertIn("RENOVATE_TOKEN", args)
        self.assertNotIn("TELEGRAM", text)
        self.assertNotIn("docker.sock", text)
        self.assertNotIn("/.ssh", text)
        self.assertNotIn("/.env:", text)
        self.assertIn("renovate-repository.json:ro", text)


if __name__ == "__main__":
    unittest.main()
