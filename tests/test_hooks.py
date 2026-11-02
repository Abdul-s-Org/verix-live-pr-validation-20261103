"""Hook contracts, capture races, and concurrent delivery against real local SQLite."""

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from verix.engine.git import VerixError
from verix.engine.service import Engine
from verix.hooks.claude import handle, install


class HookTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        for args in (
            ("init", "-q"),
            ("config", "user.name", "Test"),
            ("config", "user.email", "test@example.invalid"),
        ):
            subprocess.run(["git", "-C", str(self.root), *args], check=True, capture_output=True)
        (self.root / "a.py").write_text("VALUE = 1\n", newline="\n")
        for args in (("add", "a.py"), ("commit", "-qm", "base")):
            subprocess.run(["git", "-C", str(self.root), *args], check=True, capture_output=True)
        self.engine = Engine(self.root)
        self.addCleanup(self.engine.store.db.close)
        self.payload = {
            "session_id": "session",
            "tool_use_id": "read",
            "tool_name": "Read",
            "hook_event_name": "PreToolUse",
            "tool_input": {"file_path": str(self.root / "a.py")},
        }

    def test_parallel_duplicate_delivery_is_atomic(self):
        handle(self.engine, self.payload)
        post = {
            **self.payload,
            "hook_event_name": "PostToolUse",
            "tool_response": {"file": {"content": "VALUE = 1\n"}},
        }

        def deliver(_):
            engine = Engine(self.root)
            try:
                return handle(engine, post)
            finally:
                engine.store.db.close()

        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(deliver, range(4)))
        self.assertTrue(all(result == results[0] for result in results))
        self.assertEqual(len(self.engine.store.nodes("session")), 1)

    def test_race_between_post_read_validation_and_persistence_is_rejected(self):
        handle(self.engine, self.payload)
        observe = self.engine.observe

        def changed(*args, **kwargs):
            (self.root / "a.py").write_text("VALUE = 2\n")
            return observe(*args, **kwargs)

        post = {
            **self.payload,
            "hook_event_name": "PostToolUse",
            "tool_response": {"file": {"content": "VALUE = 1\n"}},
        }
        with patch.object(self.engine, "observe", side_effect=changed):
            with self.assertRaisesRegex(VerixError, "changed before capture"):
                handle(self.engine, post)
        self.assertEqual(self.engine.store.nodes("session"), {})

    def test_partial_read_stays_unknown_and_compaction_preserves_evidence(self):
        pre = {**self.payload, "tool_input": {**self.payload["tool_input"], "limit": 1}}
        handle(self.engine, pre)
        post = {
            **pre,
            "hook_event_name": "PostToolUse",
            "tool_response": {"file": {"content": "VALUE = 1\n"}},
        }
        observation = handle(self.engine, post)["observation"]
        handle(self.engine, {"session_id": "session", "hook_event_name": "PreCompact"})
        self.assertEqual(self.engine.analyze("session")["states"][observation], "unknown")

    def test_install_rejects_bad_settings_without_overwriting(self):
        directory = self.root / ".claude"
        directory.mkdir()
        target = directory / "settings.local.json"
        for data in ([], {"hooks": []}, {"hooks": {"SessionStart": {}}}):
            before = json.dumps(data)
            target.write_text(before)
            with self.assertRaises(VerixError):
                install(self.root)
            self.assertEqual(target.read_text(), before)

    def test_two_sessions_hold_stale_edit_until_read_and_reaffirm(self):
        self.engine.policy["mode"] = "blocking"
        self.engine.policy["risk"] = {"a.py": "high"}
        handle(self.engine, self.payload)
        handle(
            self.engine,
            {
                **self.payload,
                "hook_event_name": "PostToolUse",
                "tool_response": {"file": {"content": "VALUE = 1\n"}},
            },
        )
        claim = self.engine.claim("session", "Module exports VALUE", ["a.py"], [])
        other = self.engine.start("agent-b")
        self.engine.observe(other, "a.py")
        self.engine.claim(other, "Change VALUE to 2", ["a.py"], [])
        with self.engine.store.transaction():
            self.engine.store.db.execute("UPDATE sessions SET incomplete=0")
        write = {
            "session_id": other,
            "tool_use_id": "write",
            "tool_name": "Write",
            "hook_event_name": "PreToolUse",
            "tool_input": {"file_path": "a.py"},
        }
        result = handle(self.engine, write)
        self.assertIn("Verix allow", result["hookSpecificOutput"]["additionalContext"])
        (self.root / "a.py").write_text("VALUE = 2\n", newline="\n")
        handle(self.engine, {**write, "hook_event_name": "PostToolUse"})
        edit = {
            "session_id": "session",
            "tool_use_id": "edit",
            "tool_name": "Edit",
            "hook_event_name": "PreToolUse",
            "tool_input": {"file_path": "a.py"},
        }
        self.assertEqual(
            handle(self.engine, edit)["hookSpecificOutput"]["permissionDecision"], "deny"
        )
        reread = {**self.payload, "tool_use_id": "reread"}
        handle(self.engine, reread)
        handle(
            self.engine,
            {
                **reread,
                "hook_event_name": "PostToolUse",
                "tool_response": {"file": {"content": "VALUE = 2\n"}},
            },
        )
        # A fresh read alone cannot attest that the old claim is true.
        self.assertEqual(self.engine.analyze("session")["states"][claim], "suspect")
        self.engine.verify("session", claim, reaffirm=True)
        result = handle(self.engine, {**edit, "tool_use_id": "edit-after-review"})
        self.assertIn("Verix allow", result["hookSpecificOutput"]["additionalContext"])
