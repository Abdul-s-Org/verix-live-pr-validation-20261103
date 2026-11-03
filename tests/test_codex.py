"""Codex native contracts using synthetic full-file reads and patch proposals."""

import json
import unittest

from tests import test_hooks
from verix.engine.git import VerixError
from verix.hooks.claude import install
from verix.hooks.codex import handle


class CodexTests(unittest.TestCase):
    setUp = test_hooks.HookTests.setUp

    def native(self, command="cat a.py", tool="Bash", event="PreToolUse", id="read", **extra):
        return {
            "session_id": "codex",
            "cwd": str(self.root),
            "hook_event_name": event,
            "tool_use_id": id,
            "tool_name": tool,
            "tool_input": {"command": command},
            **extra,
        }

    def read(self, id="read", response="VALUE = 1\n"):
        handle(self.engine, self.native(id=id))
        handle(self.engine, self.native(event="PostToolUse", id=id, tool_response=response))

    def patch_payload(self, **extra):
        return self.native(
            "*** Begin Patch\n*** Update File: a.py\n@@\n-VALUE = 1\n+VALUE = 3\n*** End Patch",
            "apply_patch",
            id="edit",
            **extra,
        )

    def test_native_stale_block_then_reaffirm_allows(self):
        self.engine.policy.update(mode="blocking", risk={"a.py": "high"})
        self.read()
        self.assertEqual(self.engine.store.session("codex")["agent"], "codex")
        claim = self.engine.claim("codex", "Module exports VALUE", ["a.py"], [])
        with self.engine.store.transaction():
            self.engine.store.db.execute("UPDATE sessions SET incomplete=0")
        (self.root / "a.py").write_text("VALUE = 2\n", newline="\n")
        denied = handle(self.engine, self.patch_payload())
        self.assertEqual(denied["hookSpecificOutput"]["permissionDecision"], "deny")
        self.read("reread", "VALUE = 2\n")
        self.engine.verify("codex", claim, reaffirm=True)
        with self.engine.store.transaction():
            self.engine.store.db.execute("UPDATE sessions SET incomplete=0")
        allowed = handle(self.engine, {**self.patch_payload(), "tool_use_id": "reviewed"})
        self.assertIn("Verix allow", allowed["hookSpecificOutput"]["additionalContext"])
        handle(
            self.engine,
            {
                **self.patch_payload(event="PostToolUse"),
                "tool_use_id": "reviewed",
                "tool_response": "Exit code: 0\nWall time: 0.1 seconds\nOutput:\n"
                "Success. Updated the following files:\nM a.py\n",
            },
        )
        actions = [n for n in self.engine.store.nodes("codex").values() if n["kind"] == "action"]
        self.assertEqual(sum(n["executed"] for n in actions), 1)

    def test_truncated_output_and_duplicates(self):
        self.read(response="VALUE")
        self.read(response="VALUE")
        nodes = self.engine.store.nodes("codex")
        self.assertEqual(len(nodes), 1)
        self.assertEqual(list(self.engine.analyze("codex")["states"].values()), ["unknown"])

    def test_unsupported_shell_blocks_and_does_not_capture(self):
        self.engine.policy["mode"] = "blocking"
        for command in (
            "head a.py",
            "cat a.py; echo x",
            "cat a.py | head",
            "cat *.py",
            "cat $(echo a.py)",
            "cat #a.py",
            "cat a.py > b.py",
            "cat -n a.py",
        ):
            with self.subTest(command=command):
                result = handle(self.engine, self.native(command))
                self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertEqual(self.engine.store.nodes("codex"), {})

    def test_bad_paths_cwd_and_patch_rejected_atomically(self):
        for payload in (
            self.native("cat ../outside"),
            {**self.native(), "cwd": str(self.root / "sub")},
            self.native("*** Begin Patch\n*** Update File: ../x\n*** End Patch", "apply_patch"),
            self.native("bad patch", "apply_patch"),
            self.native("*** Begin Patch\n*** Update File:  a.py\n*** End Patch", "apply_patch"),
        ):
            with self.subTest(payload=payload), self.assertRaises(VerixError):
                handle(self.engine, payload)
        self.assertEqual(
            self.engine.store.db.execute("SELECT count(*) FROM sessions").fetchone()[0], 0
        )

    def test_failed_patch_does_not_mark_executed(self):
        self.read()
        handle(self.engine, self.patch_payload())
        handle(
            self.engine,
            self.patch_payload(
                event="PostToolUse",
                tool_response="Exit code: 1\nWall time: 0.1 seconds\nOutput:\n"
                "Success. Updated the following files:\nM a.py\n",
            ),
        )
        actions = [n for n in self.engine.store.nodes("codex").values() if n["kind"] == "action"]
        self.assertFalse(actions[0]["executed"])
        self.assertTrue(self.engine.store.session("codex")["incomplete"])

    def test_every_patch_target_is_checked(self):
        self.engine.policy.update(mode="blocking", risk={"b.py": "low", "a.py": "high"})
        payload = self.native(
            "*** Begin Patch\n*** Add File: b.py\n+x\n*** Update File: a.py\n@@\n-x\n+y\n*** End Patch",
            "apply_patch",
            id="multi",
        )
        result = handle(self.engine, payload)
        self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny")
        actions = [n for n in self.engine.store.nodes("codex").values() if n["kind"] == "action"]
        self.assertEqual(len(actions), 2)

    def test_compaction_preserves_capture(self):
        self.read()
        before = self.engine.store.nodes("codex")
        handle(self.engine, self.native(event="PreCompact"))
        self.assertEqual(self.engine.store.nodes("codex"), before)

    def test_installer_preserves_settings_and_is_idempotent(self):
        install(self.root, "codex")
        target = self.root / ".codex" / "hooks.json"
        config = target.with_name("config.toml")
        self.assertIn("hooks = true", config.read_text())
        config.write_text("[features]\nhooks = true\n# custom\n")
        data = json.loads(target.read_text())
        data["custom"] = True
        target.write_text(json.dumps(data))
        install(self.root, "codex")
        self.assertEqual(json.loads(target.read_text()), data)
        self.assertIn("# custom", config.read_text())
        self.assertIn("codex-hook", data["hooks"]["PreToolUse"][0]["hooks"][0]["command"])
