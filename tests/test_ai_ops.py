from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class GatewayPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory()
        root = Path(cls.temporary.name)
        token = root / "gateway-token"
        approval_token = root / "approval-token"
        token.write_text("a" * 64, encoding="ascii")
        approval_token.write_text("c" * 64, encoding="ascii")
        os.environ.update(
            {
                "AI_OPS_STACK_DIR": str(REPO),
                "AI_OPS_POLICY_FILE": str(REPO / "config/ai-ops/policy.json"),
                "AI_OPS_STATE_DIR": str(root / "state"),
                "AI_OPS_TOKEN_FILE": str(token),
                "AI_OPS_APPROVAL_TOKEN_FILE": str(approval_token),
                "AI_OPS_SOCKET": str(root / "gateway.sock"),
            }
        )
        cls.gateway = _load("ai_ops_gateway", REPO / "scripts/ai-ops-gateway.py")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary.cleanup()

    def test_allowed_action_is_normalized(self) -> None:
        action = self.gateway.validate_action(
            {
                "type": "restart_compose_service",
                "target": "homepage",
                "patch": "",
                "rationale": "Ripristina il servizio non raggiungibile.",
            }
        )
        self.assertEqual(action["target"], "homepage")

    def test_command_injection_target_is_rejected(self) -> None:
        with self.assertRaises(self.gateway.ApiError):
            self.gateway.validate_action(
                {
                    "type": "restart_systemd_unit",
                    "target": "core-stack.service;id",
                    "patch": "",
                    "rationale": "tentativo",
                }
            )

    def test_enforcement_file_patch_is_rejected(self) -> None:
        patch = "\n".join(
            [
                "diff --git a/config/ai-ops/policy.json b/config/ai-ops/policy.json",
                "--- a/config/ai-ops/policy.json",
                "+++ b/config/ai-ops/policy.json",
                "@@ -1 +1 @@",
                "-{}",
                "+{}",
            ]
        )
        with self.assertRaises(self.gateway.ApiError):
            self.gateway._patch_paths(patch)

    def test_mismatched_patch_header_is_rejected(self) -> None:
        patch = "\n".join(
            [
                "diff --git a/docs/security.md b/docs/security.md",
                "--- a/docs/security.md",
                "+++ b/scripts/ai-ops-gateway.py",
                "@@ -1 +1 @@",
                "-old",
                "+new",
            ]
        )
        with self.assertRaises(self.gateway.ApiError):
            self.gateway._patch_paths(patch)

    def test_plan_token_is_single_use(self) -> None:
        plan = {
            "summary": "Riavvio Homepage",
            "problem": "Il container non risponde.",
            "evidence": ["Stato non healthy"],
            "actions": [
                {
                    "type": "restart_compose_service",
                    "target": "homepage",
                    "patch": "",
                    "rationale": "Riavvio limitato al servizio.",
                }
            ],
            "risks": ["Breve indisponibilità"],
            "verification": ["Nuova diagnostica"],
        }
        registration = self.gateway.create_plan(plan)
        callback = registration["reject_callback"].split(":")
        result = self.gateway.cancel_plan(callback[1], callback[2])
        self.assertEqual(result["status"], "cancelled")
        with self.assertRaises(self.gateway.ApiError) as context:
            self.gateway.cancel_plan(callback[1], callback[2])
        self.assertEqual(context.exception.status, 409)

    def test_execution_requires_separate_telegram_approval(self) -> None:
        plan = {
            "summary": "Riavvio Homepage",
            "problem": "Il container non risponde.",
            "evidence": ["Stato non healthy"],
            "actions": [
                {
                    "type": "restart_compose_service",
                    "target": "homepage",
                    "patch": "",
                    "rationale": "Riavvio limitato al servizio.",
                }
            ],
            "risks": ["Breve indisponibilità"],
            "verification": ["Nuova diagnostica"],
        }
        registration = self.gateway.create_plan(plan)
        callback = registration["approve_callback"].split(":")
        with self.assertRaises(self.gateway.ApiError) as context:
            self.gateway.execute_plan(callback[1], callback[2])
        self.assertEqual(context.exception.status, 409)
        approved = self.gateway.approve_plan(callback[1], callback[2])
        self.assertEqual(approved["status"], "approved")
        repeated = self.gateway.approve_plan(callback[1], callback[2])
        self.assertEqual(repeated["status"], "approved")


class TelegramBridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory()
        root = Path(cls.temporary.name)
        bot = root / "bot-token"
        bridge = root / "bridge-token"
        approval = root / "approval-token"
        bot.write_text("123456:" + "A" * 32, encoding="ascii")
        bridge.write_text("b" * 64, encoding="ascii")
        approval.write_text("c" * 64, encoding="ascii")
        os.environ.update(
            {
                "TELEGRAM_BOT_TOKEN_FILE": str(bot),
                "TELEGRAM_BRIDGE_TOKEN_FILE": str(bridge),
                "AI_OPS_APPROVAL_TOKEN_FILE": str(approval),
                "TELEGRAM_OFFSET_FILE": str(root / "offset"),
                "AI_OPS_TELEGRAM_CHAT_ID": "123456789",
                "AI_OPS_TELEGRAM_USER_ID": "123456789",
            }
        )
        cls.telegram = _load("ai_ops_telegram", REPO / "scripts/ai-ops-telegram.py")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary.cleanup()

    def test_long_reports_are_split_without_loss(self) -> None:
        text = ("riga di dettaglio\n" * 1000).strip()
        chunks = self.telegram._message_chunks(text)
        self.assertGreater(len(chunks), 1)
        self.assertEqual("\n".join(chunks), text)
        self.assertTrue(all(len(chunk) <= 3900 for chunk in chunks))

    def test_only_ai_ops_callbacks_are_accepted(self) -> None:
        self.assertTrue(
            self.telegram._valid_keyboard(
                [[{"text": "Conferma", "callback_data": "aiok:012345abcdef:tokenvalue123"}]]
            )
        )
        self.assertFalse(
            self.telegram._valid_keyboard(
                [[{"text": "Apri", "callback_data": "https://example.com"}]]
            )
        )

    def test_update_must_match_both_user_and_chat(self) -> None:
        allowed = {
            "message": {
                "from": {"id": 123456789},
                "chat": {"id": 123456789},
                "text": "/fix test",
            }
        }
        wrong_user = {
            "message": {
                "from": {"id": 987654321},
                "chat": {"id": 123456789},
                "text": "/fix test",
            }
        }
        self.assertTrue(self.telegram._is_authorized(allowed))
        self.assertFalse(self.telegram._is_authorized(wrong_user))


class WorkflowTests(unittest.TestCase):
    def test_connections_reference_existing_nodes(self) -> None:
        workflow = json.loads(
            (REPO / "workflows/n8n-ai-ops-telegram.json").read_text(encoding="utf-8")
        )
        names = {node["name"] for node in workflow["nodes"]}
        references = {
            connection["node"]
            for value in workflow["connections"].values()
            for branch in value["main"]
            for connection in branch
        }
        self.assertLessEqual(references, names)
        code = "\n".join(
            node.get("parameters", {}).get("jsCode", "") for node in workflow["nodes"]
        )
        self.assertNotIn("$env", code)


if __name__ == "__main__":
    unittest.main()
