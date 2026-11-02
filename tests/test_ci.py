"""Receipt PR analysis on exact commits, including untrusted PR policy and missing data."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from verix.engine.service import Engine
from verix import receipts

SOURCE = str(Path(__file__).resolve().parents[1] / "src")


class CiTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "repo"
        self.root.mkdir()
        self.git("init", "-q")
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.invalid")
        (self.root / "source.py").write_text("VALUE = 1\n", newline="\n")
        (self.root / ".verix.yml").write_text("mode: blocking\nrisk: {'*': high}\n", newline="\n")
        self.git("add", "source.py", ".verix.yml")
        self.git("commit", "-qm", "base")
        self.base = self.git("rev-parse", "HEAD")
        engine = Engine(self.root)
        try:
            session = engine.start("ci-test")
            engine.observe(session, "source.py")
            engine.claim(session, "Source contract", ["source.py"], [])
            with engine.store.transaction():
                engine.store.db.execute("UPDATE sessions SET incomplete=0 WHERE id=?", (session,))
            self.receipt = receipts.export(engine, session)
        finally:
            engine.store.db.close()

    def git(self, *args):
        return subprocess.run(
            ["git", "-C", str(self.root), *args], check=True, capture_output=True, text=True
        ).stdout.strip()

    def analyze(self, expected):
        self.git("add", "-A", "--", "source.py", ".verix.yml", "receipt.json")
        self.git("commit", "-qm", "PR")
        head = self.git("rev-parse", "HEAD")
        with tempfile.TemporaryDirectory() as directory:
            subprocess.run(["git", "clone", "-q", str(self.root), directory], check=True)
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "verix",
                    "--repo",
                    directory,
                    "ci",
                    "--receipt",
                    "receipt.json",
                    "--base",
                    self.base,
                    "--head",
                    head,
                ],
                env={**os.environ, "PYTHONPATH": SOURCE},
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, expected, result.stderr + result.stdout)
            data = json.loads(result.stdout)
            self.assertEqual(data["analyzed_head"], head)
            self.assertEqual(data["analyzed_base"], self.base)
            return data

    def test_current_receipt_allows_without_executing_pr_commands(self):
        marker = Path(self.temporary.name) / "must-not-exist"
        command = [sys.executable, "-c", f"from pathlib import Path; Path({str(marker)!r}).touch()"]
        (self.root / ".verix.yml").write_text(
            json.dumps({"mode": "advisory", "checks": {"evil": command}})
        )
        (self.root / "receipt.json").write_text(json.dumps(self.receipt))
        self.assertEqual(self.analyze(0)["verdict"], "allow")
        self.assertFalse(marker.exists())

    def test_stale_receipt_blocks_despite_pr_policy_downgrade(self):
        (self.root / "source.py").write_text("VALUE = 2\n", newline="\n")
        (self.root / ".verix.yml").write_text("mode: advisory\n")
        (self.root / "receipt.json").write_text(json.dumps(self.receipt))
        result = self.analyze(20)
        self.assertEqual(result["verdict"], "block")
        self.assertEqual(result["mode"], "blocking")

    def test_malformed_receipt_is_unresolved(self):
        (self.root / "receipt.json").write_text("{invalid")
        self.assertEqual(self.analyze(30)["verdict"], "unresolved")

    def test_missing_receipt_is_unresolved(self):
        # Commit an unrelated file so the PR exists, while keeping the receipt absent.
        self.git("commit", "--allow-empty", "-qm", "PR without receipt")
        head = self.git("rev-parse", "HEAD")
        with tempfile.TemporaryDirectory() as directory:
            subprocess.run(["git", "clone", "-q", str(self.root), directory], check=True)
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "verix",
                    "--repo",
                    directory,
                    "ci",
                    "--receipt",
                    "missing.json",
                    "--base",
                    self.base,
                    "--head",
                    head,
                ],
                env={**os.environ, "PYTHONPATH": SOURCE},
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 30, result.stderr)
            self.assertEqual(json.loads(result.stdout)["verdict"], "unresolved")
