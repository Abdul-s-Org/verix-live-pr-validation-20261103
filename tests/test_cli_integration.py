import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SOURCE = str(Path(__file__).resolve().parents[1] / "src")


class IntegrationTests(unittest.TestCase):
    def test_local_workflow_and_ci_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            def git(*args):
                return subprocess.run(
                    ["git", "-C", directory, *args], check=True, capture_output=True, text=True
                ).stdout.strip()

            def cli(*args, code=0):
                result = subprocess.run(
                    [sys.executable, "-m", "verix", "--repo", directory, *args],
                    env={**os.environ, "PYTHONPATH": SOURCE},
                    text=True,
                    capture_output=True,
                )
                self.assertEqual(result.returncode, code, result.stderr + result.stdout)
                return json.loads(result.stdout)

            git("init", "-q")
            git("config", "user.name", "Test")
            git("config", "user.email", "test@example.invalid")
            (root / "auth.py").write_text('AUTH = "jwt"\n')
            git("add", "auth.py")
            git("commit", "-qm", "base")
            base = git("rev-parse", "HEAD")
            cli("init", "--hooks")
            session = cli("session", "start")["session"]
            cli("read", "auth.py", "--session", session)
            claim = cli("claim", "add", "Uses JWT", "--session", session, "--evidence", "auth.py")[
                "claim"
            ]
            cli("session", "complete", "--session", session, "--ack-limitations")
            self.assertEqual(
                cli("check", "--session", session, "--path", "auth.py")["verdict"], "allow"
            )
            (root / "auth.py").write_text('AUTH = "session"\n')
            self.assertEqual(
                cli("check", "--session", session, "--path", "auth.py", code=10)["verdict"],
                "verify",
            )
            receipt = cli("receipt", "export", "--session", session)
            (root / "receipt.json").write_text(json.dumps(receipt))
            git("add", "auth.py", "receipt.json")
            git("commit", "-qm", "PR")
            head = git("rev-parse", "HEAD")
            # Analyze in a fresh worktree, as on an ephemeral CI runner.
            with tempfile.TemporaryDirectory() as fresh:
                subprocess.run(["git", "clone", "-q", directory, fresh], check=True)
                result = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "verix",
                        "--repo",
                        fresh,
                        "ci",
                        "--receipt",
                        "receipt.json",
                        "--base",
                        base,
                        "--head",
                        head,
                    ],
                    env={**os.environ, "PYTHONPATH": SOURCE},
                    text=True,
                    capture_output=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout)["verdict"], "verify")
            cli("verify", claim, "--session", session, "--reaffirm")
            self.assertEqual(
                cli("report", "--session", session, "--json")["states"][claim], "valid"
            )

    def test_bad_arguments_and_operational_error(self):
        for args, expected in ((["unknown"], 2), (["--repo", "/does-not-exist", "init"], 1)):
            result = subprocess.run(
                [sys.executable, "-m", "verix", *args],
                env={**os.environ, "PYTHONPATH": SOURCE},
                capture_output=True,
            )
            self.assertEqual(result.returncode, expected)
