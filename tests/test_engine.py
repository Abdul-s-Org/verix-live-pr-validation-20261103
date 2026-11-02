import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from verix.engine.git import VerixError
from verix.engine import policy
from verix.engine.service import Engine
from verix.hooks.claude import handle, install
from verix import receipts


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.git("init", "-q")
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.invalid")
        self.write("a.py", "VALUE = 1\n")
        self.write("b.py", "OTHER = 1\n")
        self.git("add", ".")
        self.git("commit", "-qm", "base")
        self.engine = Engine(self.root)
        self.addCleanup(self.engine.store.db.close)
        self.session = self.engine.start("test")

    def git(self, *args):
        return (
            subprocess.run(["git", "-C", str(self.root), *args], check=True, capture_output=True)
            .stdout.decode()
            .strip()
        )

    def write(self, name, content):
        (self.root / name).write_text(content, newline="\n")

    def claim(self, path="a.py", parents=None, alternative=False):
        paths = [path] if path else []
        for item in paths:
            self.engine.observe(self.session, item)
        return self.engine.claim(self.session, "Contract", paths, parents or [], alternative)

    def complete(self):
        with self.engine.store.transaction():
            self.engine.store.db.execute(
                "UPDATE sessions SET incomplete=0 WHERE id=?", (self.session,)
            )

    def test_transitive_propagation_and_unrelated_evidence(self):
        root = self.claim()
        child = self.claim(None, [root])
        leaf = self.claim(None, [child])
        unrelated = self.claim("b.py")
        self.write("a.py", "VALUE = 2\n")
        states = self.engine.analyze(self.session)["states"]
        self.assertEqual([states[n] for n in (root, child, leaf)], ["suspect"] * 3)
        self.assertEqual(states[unrelated], "valid")

    def test_alternative_evidence_requires_explicit_group(self):
        a, b = self.claim(), self.claim("b.py")
        alternative = self.claim(None, [a, b], True)
        conjunction = self.claim(None, [a, b])
        self.write("a.py", "VALUE = 2\n")
        states = self.engine.analyze(self.session)["states"]
        self.assertEqual(states[alternative], "valid")
        self.assertEqual(states[conjunction], "suspect")

    def test_unknown_claim_and_session_completeness(self):
        self.claim()
        self.assertEqual(self.engine.check(self.session, "a.py")["verdict"], "unresolved")
        self.complete()
        self.assertEqual(self.engine.check(self.session, "a.py")["verdict"], "allow")
        self.claim(None)
        self.assertEqual(self.engine.check(self.session, "a.py")["verdict"], "unresolved")

    def test_policy_risk_and_replay(self):
        self.claim()
        self.complete()
        self.engine.policy["risk"] = {"a.py": "high"}
        self.write("a.py", "VALUE = 2\n")
        decision = self.engine.check(self.session, "a.py")
        self.assertEqual(decision["verdict"], "block")
        self.assertTrue(self.engine.replay(decision["audit_id"])["matches"])

    def test_reaffirm_is_revision_and_content_bound(self):
        claim = self.claim()
        self.write("a.py", "VALUE = 2\n")
        with self.assertRaises(VerixError):
            self.engine.verify(self.session, claim)
        self.engine.verify(self.session, claim, reaffirm=True)
        self.assertEqual(self.engine.analyze(self.session)["states"][claim], "valid")
        self.write("a.py", "VALUE = 3\n")
        self.assertEqual(self.engine.analyze(self.session)["states"][claim], "suspect")

    def test_failed_test_invalidates_and_timeout_does_not_reaffirm(self):
        import sys

        claim = self.claim()
        self.engine.policy["checks"] = {"fail": [sys.executable, "-c", "raise SystemExit(1)"]}
        self.assertEqual(self.engine.verify(self.session, claim, True, "fail")["state"], "invalid")
        self.complete()
        self.assertEqual(self.engine.check(self.session, "a.py")["verdict"], "block")
        self.engine.policy["checks"]["bad"] = ["/does/not/exist"]
        with self.assertRaises(VerixError):
            self.engine.verify(self.session, claim, True, "bad")

    def test_foreign_session_parent_rejected(self):
        parent = self.claim()
        other = self.engine.start("other")
        with self.assertRaises(VerixError):
            self.engine.claim(other, "bad", [], [parent])

    def test_change_detection_rename_delete_and_mode(self):
        base = self.engine.repo.revision()
        self.git("mv", "a.py", "renamed file.py")
        (self.root / "b.py").unlink()
        self.git("add", "-A", "--", "b.py", "renamed file.py")
        self.git("commit", "-qm", "changes")
        changes = self.engine.repo.changes(base, "HEAD")
        self.assertTrue(
            any(c["status"].startswith("R") and c["new_path"] == "renamed file.py" for c in changes)
        )
        self.assertTrue(any(c["status"] == "D" for c in changes))
        self.assertIsNone(self.engine.repo.fingerprint("a.py")["sha256"])
        self.assertIsNotNone(self.engine.repo.fingerprint("a.py", base)["sha256"])

    def test_path_boundaries_and_exclusions(self):
        for value in ("../outside", ".git/config", ".GIT/config", "/", "."):
            with self.assertRaises(VerixError):
                self.engine.repo.path(value)
        self.write(".env", "SECRET=hidden")
        with self.assertRaises(VerixError):
            self.engine.observe(self.session, ".env")

    def test_database_rollback_and_schema_rejection(self):
        with self.assertRaises(VerixError):
            with self.engine.store.transaction():
                self.engine.store.add(self.session, "claim", "temporary", {})
                self.engine.store.add("missing", "claim", "bad", {})
        self.assertNotIn("temporary", self.engine.store.nodes(self.session))
        self.engine.store.db.execute("PRAGMA user_version=99")
        from verix.engine.store import Store

        with self.assertRaises(VerixError):
            Store(self.root)

    def test_receipt_roundtrip_and_metadata_only(self):
        claim = self.claim()
        self.engine.verify(self.session, claim, reaffirm=True)
        receipt = receipts.export(self.engine, self.session)
        self.assertNotIn("verification", receipt["nodes"][claim])
        self.assertNotIn("Contract", json.dumps(receipt))
        engine = self.engine
        other = self.engine.start("other")
        with self.assertRaises(VerixError):
            receipts.ingest(engine, receipt)
        receipt["session"]["id"] = other + "-import"
        for key, node in list(receipt["nodes"].items()):
            # A clean importing database is required; IDs cannot overwrite local evidence.
            self.engine.store.db.execute("DELETE FROM edges WHERE parent=? OR child=?", (key, key))
            self.engine.store.db.execute("DELETE FROM nodes WHERE id=?", (key,))
        self.engine.store.db.commit()
        imported = receipts.ingest(engine, receipt)
        self.assertEqual(self.engine.analyze(imported)["states"][claim], "valid")

    def test_receipt_rejects_cycle_unknown_fields_and_invalid_hash(self):
        claim = self.claim()
        receipt = receipts.export(self.engine, self.session)
        broken = copy.deepcopy(receipt)
        broken["nodes"][claim]["groups"] = [[claim]]
        with self.assertRaises(VerixError):
            receipts.validate(broken)
        broken = copy.deepcopy(receipt)
        broken["file_body"] = "secret"
        with self.assertRaises(VerixError):
            receipts.validate(broken)
        broken = copy.deepcopy(receipt)
        observation = next(n for n in broken["nodes"].values() if n["kind"] == "observation")
        observation["fingerprint"]["sha256"] = "invalid"
        with self.assertRaises(VerixError):
            receipts.validate(broken)

    def test_hook_install_preserves_settings_and_is_idempotent(self):
        directory = self.root / ".claude"
        directory.mkdir()
        target = directory / "settings.local.json"
        target.write_text(json.dumps({"permissions": {"allow": ["Read"]}}))
        install(self.root)
        first = target.read_text()
        install(self.root)
        self.assertEqual(target.read_text(), first)
        self.assertEqual(json.loads(first)["permissions"], {"allow": ["Read"]})

    def test_hook_full_partial_and_duplicate_reads(self):
        payload = {
            "session_id": "hook-session",
            "tool_name": "Read",
            "tool_use_id": "read-1",
            "tool_input": {"file_path": str(self.root / "a.py")},
            "hook_event_name": "PreToolUse",
        }
        handle(self.engine, payload)
        payload.update(
            hook_event_name="PostToolUse", tool_response={"file": {"content": "VALUE = 1\n"}}
        )
        first = handle(self.engine, payload)
        self.assertEqual(handle(self.engine, payload), first)
        nodes = self.engine.store.nodes("hook-session")
        self.assertTrue(nodes[first["observation"]]["complete"])
        payload.update(tool_use_id="read-2", tool_response={"file": {"content": "partial"}})
        second = handle(self.engine, payload)
        self.assertFalse(self.engine.store.nodes("hook-session")[second["observation"]]["complete"])

    def test_hook_blocks_high_risk_stale_edit(self):
        self.engine.policy["mode"] = "blocking"
        self.engine.policy["risk"] = {"a.py": "high"}
        self.claim()
        self.complete()
        self.write("a.py", "VALUE = 2\n")
        result = handle(
            self.engine,
            {
                "session_id": self.session,
                "tool_use_id": "edit-1",
                "hook_event_name": "PreToolUse",
                "tool_name": "Edit",
                "tool_input": {"file_path": "a.py"},
            },
        )
        self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_policy_validation_and_risk_precedence(self):
        path = self.root / ".verix.yml"
        for text in (
            "unknown: true",
            "mode: invalid",
            "risk: []",
            "checks: {a: echo}",
            "exclude: hi",
            "mode: [",
        ):
            path.write_text(text)
            with self.assertRaises(VerixError):
                policy.load(path)
        path.write_text("risk: {'*.py': low, 'a.*': high}\n")
        self.assertEqual(policy.risk(policy.load(path), "a.py"), "high")

    def test_operational_errors_and_unknown_replay(self):
        for ref in ("-bad", "missing-revision"):
            with self.assertRaises(VerixError):
                self.engine.repo.revision(ref)
        with self.assertRaises(VerixError):
            self.engine.observe(self.session, "missing.py")
        with self.assertRaises(VerixError):
            self.engine.store.session("missing")
        with self.assertRaises(VerixError):
            self.engine.replay(999)
        with self.engine.store.transaction():
            event = self.engine.store.audit({"kind": "not-a-decision"})
        with self.assertRaises(VerixError):
            self.engine.replay(event)
        with self.assertRaises(VerixError):
            self.engine.check(self.session, "a.py", action="delete")
        with self.assertRaises(VerixError):
            self.engine.claim(self.session, "", [], [])
        with self.assertRaises(VerixError):
            self.engine.claim(self.session, "missing", ["missing.py"], [])

    def test_verification_rejects_incomplete_and_changed_evidence(self):
        from unittest.mock import patch

        observation = self.engine.observe(self.session, "a.py", complete=False)
        claim = self.engine.claim(self.session, "Partial", [], [observation])
        with self.assertRaises(VerixError):
            self.engine.verify(self.session, claim, reaffirm=True)
        full = self.claim()
        with self.assertRaises(VerixError):
            self.engine.verify(self.session, full, check="anything")
        with self.assertRaises(VerixError):
            self.engine.verify(self.session, full, reaffirm=True, check="missing")
        self.engine.policy["checks"]["race"] = ["configured-test"]

        def change(*args, **kwargs):
            self.write("a.py", "changed during check")
            return subprocess.CompletedProcess(args[0], 0)

        original = subprocess.run

        def selectively_change(command, **kwargs):
            return (
                change(command, **kwargs)
                if command == ["configured-test"]
                else original(command, **kwargs)
            )

        with patch("verix.engine.service.subprocess.run", side_effect=selectively_change):
            with self.assertRaises(VerixError):
                self.engine.verify(self.session, full, True, "race")

    def test_file_mode_and_binary_changes(self):
        self.write("binary", "before")
        (self.root / "binary").write_bytes(b"\x00before")
        self.engine.observe(self.session, "binary")
        (self.root / "binary").write_bytes(b"\x00after")
        report = self.engine.analyze(self.session)
        self.assertIn("suspect", report["states"].values())
        base = self.engine.repo.fingerprint("a.py")
        if os.name != "nt":
            (self.root / "a.py").chmod(0o755)
            self.assertNotEqual(self.engine.repo.fingerprint("a.py"), base)
        else:
            self.assertEqual(base["mode"], "100644")

    def test_policy_full_validation(self):
        path = self.root / ".verix.yml"
        for text in (
            "version: 99",
            "[]",
            "checks: {a: []}",
            "risk: {a: invalid}",
            "exclude: [1]",
            "checks: {a: [1]}",
        ):
            path.write_text(text)
            with self.assertRaises(VerixError):
                policy.load(path)
        for states, level, incomplete, expected in (
            (["valid"], "low", False, "allow"),
            (["suspect"], "medium", False, "verify"),
            (["unknown"], "low", True, "allow"),
            ([], "high", True, "unresolved"),
            (["invalid"], "low", False, "block"),
        ):
            self.assertEqual(policy.evaluate(states, level, incomplete), expected)

    def test_executed_actions_are_retained_and_post_events_deduplicate(self):
        self.claim()
        payload = {
            "session_id": self.session,
            "tool_use_id": "executed-edit",
            "hook_event_name": "PreToolUse",
            "tool_name": "Edit",
            "tool_input": {"file_path": "a.py"},
        }
        handle(self.engine, payload)
        payload["hook_event_name"] = "PostToolUse"
        first = handle(self.engine, payload)
        self.assertEqual(first, handle(self.engine, payload))
        actions = [
            n for n in self.engine.store.nodes(self.session).values() if n["kind"] == "action"
        ]
        self.assertTrue(actions[0]["executed"])
        receipts.validate(receipts.export(self.engine, self.session))

    def test_nested_transactions_rollback_outer_changes(self):
        with self.assertRaises(RuntimeError):
            with self.engine.store.transaction():
                self.engine.observe(self.session, "a.py")
                raise RuntimeError("interrupt outer operation")
        self.assertEqual(self.engine.store.nodes(self.session), {})

    def test_policy_defaults_are_not_shared_and_duplicate_keys_fail(self):
        first = policy.load(self.root / "absent")
        first["risk"]["a.py"] = "high"
        self.assertEqual(policy.load(self.root / "absent")["risk"], {})
        path = self.root / ".verix.yml"
        path.write_text("mode: advisory\nmode: blocking\n")
        with self.assertRaisesRegex(VerixError, "line 2"):
            policy.load(path)

    def test_root_alias_is_accepted_but_nested_symlinks_are_not(self):
        with tempfile.TemporaryDirectory() as directory:
            alias = Path(directory) / "root-alias"
            try:
                alias.symlink_to(self.root, target_is_directory=True)
                (self.root / "nested").symlink_to(self.root, target_is_directory=True)
                (self.root / "link").symlink_to(self.root / "a.py")
            except OSError as exc:
                self.skipTest(f"Symlink creation unavailable: {exc}")
            self.assertEqual(self.engine.repo.path(str(alias / "a.py")), "a.py")
            for path in (alias / "link", alias / "nested" / "a.py", self.root / "link"):
                with self.subTest(path=path), self.assertRaises(VerixError):
                    self.engine.repo.path(str(path))

    def test_tracked_file_mode_matches_git_on_every_platform(self):
        self.assertEqual(
            self.engine.repo.fingerprint("a.py"), self.engine.repo.fingerprint("a.py", "HEAD")
        )

    def test_python_formatting_is_explicit_and_keeps_behavior_changes_suspect(self):
        self.engine.policy["ignore_python_formatting"] = True
        claim = self.claim()
        self.write("a.py", "# comment\nVALUE=1\n")
        self.assertEqual(self.engine.analyze(self.session)["states"][claim], "valid")
        receipts.validate(receipts.export(self.engine, self.session))
        self.engine.policy["ignore_python_formatting"] = False
        self.assertEqual(self.engine.analyze(self.session)["states"][claim], "suspect")
        self.engine.policy["ignore_python_formatting"] = True
        self.write("a.py", "VALUE = 2\n")
        self.assertEqual(self.engine.analyze(self.session)["states"][claim], "suspect")
        self.write("a.py", "VALUE = (\n")
        self.assertEqual(self.engine.analyze(self.session)["states"][claim], "suspect")

    def test_python_normalization_preserves_docstrings_and_type_comments(self):
        from verix.engine.git import fingerprint, equivalent

        for before, after in (
            (b'"before"\nx=1\n', b'"after"\nx=1\n'),
            (b"x=1 # type: int\n", b"x=1 # type: str\n"),
        ):
            left = fingerprint(before, "100644", "a.py", True)
            right = fingerprint(after, "100644", "a.py", True)
            self.assertFalse(equivalent(left, right, True))
        a = fingerprint(b"X = 1\n", "100644", "a.py", True)
        b = fingerprint(b"X=1\n", "100755", "a.py", True)
        self.assertFalse(equivalent(a, b, True))
        self.assertNotIn("python_ast_sha256", fingerprint(b"x=1", "100644", "a.txt", True))

    def test_successful_verification_expires_after_policy_change(self):
        claim = self.claim()
        self.write("a.py", "VALUE = 2\n")
        self.engine.verify(self.session, claim, reaffirm=True)
        self.assertEqual(self.engine.analyze(self.session)["states"][claim], "valid")
        self.engine.policy["mode"] = "blocking"
        self.assertEqual(self.engine.analyze(self.session)["states"][claim], "suspect")

    def test_verification_with_unrelated_observations_is_order_independent(self):
        claim = self.claim()
        self.claim("b.py")
        self.write("a.py", "VALUE = 2\n")
        self.engine.verify(self.session, claim, reaffirm=True)
        # Force claims before observations to expose ordering-dependent replay failures.
        nodes = self.engine.store.nodes(self.session)
        ordered = dict(sorted(nodes.items(), key=lambda item: item[1]["kind"] == "observation"))
        from unittest.mock import patch

        with patch.object(self.engine.store, "nodes", return_value=ordered):
            self.assertEqual(self.engine.analyze(self.session)["states"][claim], "valid")

    def test_windows_mode_reads_are_batched_and_index_races_rejected(self):
        from unittest.mock import patch

        self.claim()
        self.claim("b.py")
        with patch("verix.engine.service.WINDOWS", True):
            with patch.object(
                self.engine.repo, "index_modes", wraps=self.engine.repo.index_modes
            ) as modes:
                self.engine.analyze(self.session)
                self.assertEqual(modes.call_count, 1)
            original = self.engine.repo.fingerprint

            def mutate_index(*args, **kwargs):
                self.git("update-index", "--chmod=+x", "a.py")
                return original(*args, **kwargs)

            with patch.object(self.engine.repo, "fingerprint", side_effect=mutate_index):
                with self.assertRaisesRegex(VerixError, "index changed"):
                    self.engine.analyze(self.session)

    def test_index_rewrite_is_detected_even_when_bytes_are_restored(self):
        from unittest.mock import patch

        self.claim()
        index = self.root / ".git" / "index"
        original_bytes = index.read_bytes()
        original_modes = self.engine.repo.index_modes

        def transient_modes():
            self.git("update-index", "--chmod=+x", "a.py")
            result = original_modes()
            index.write_bytes(original_bytes)
            return result

        with (
            patch("verix.engine.service.WINDOWS", True),
            patch.object(self.engine.repo, "index_modes", side_effect=transient_modes),
        ):
            with self.assertRaisesRegex(VerixError, "index changed"):
                self.engine.analyze(self.session)
        self.assertEqual(index.read_bytes(), original_bytes)

    def test_custom_indexes_keep_full_mode_revalidation(self):
        from unittest.mock import patch

        self.claim()
        with patch.dict(os.environ, {"GIT_INDEX_FILE": "custom-index"}):
            self.assertIsNone(self.engine.repo.index_snapshot())
        with (
            patch("verix.engine.service.WINDOWS", True),
            patch.object(self.engine.repo, "index_snapshot", return_value=None),
        ):
            before = self.engine.repo.index_modes()
            changed = {**before, "a.py": "100755"}
            with patch.object(self.engine.repo, "index_modes", side_effect=[before, changed]):
                with self.assertRaisesRegex(VerixError, "index changed"):
                    self.engine.analyze(self.session)

    def test_linked_worktrees_keep_full_mode_revalidation(self):
        with tempfile.TemporaryDirectory() as parent:
            target = Path(parent) / "worktree"
            self.git("worktree", "add", "--detach", str(target), "HEAD")
            other = Engine(target)
            try:
                self.assertIsNone(other.repo.index_snapshot())
                session = other.start("worktree-test")
                other.observe(session, "a.py")
                other.claim(session, "Contract", ["a.py"], [])
                self.assertTrue(
                    all(s == "valid" for s in other.analyze(session)["states"].values())
                )
            finally:
                other.store.db.close()
                self.git("worktree", "remove", "--force", str(target))

    def test_resuming_session_preserves_base_without_redundant_git_call(self):
        from unittest.mock import patch

        base = self.engine.store.session(self.session)["base"]
        with patch.object(
            self.engine.repo, "revision", side_effect=AssertionError("Unexpected Git call")
        ):
            self.assertEqual(self.engine.start("test", self.session), self.session)
        self.assertEqual(self.engine.store.session(self.session)["base"], base)


if __name__ == "__main__":
    unittest.main()
