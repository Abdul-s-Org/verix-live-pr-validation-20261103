from contextlib import redirect_stderr, redirect_stdout
import io
import os
import subprocess
import sys
import unittest
from unittest.mock import patch

from verix.cli import main, parser
from pathlib import Path


class CliTests(unittest.TestCase):
    def test_help_runs_from_source(self):
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [sys.executable, "-m", "verix", "--help"],
            env={**os.environ, "PYTHONPATH": str(root / "src")},
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertIn("Detect stale coding-agent assumptions", result.stdout)

    def test_hook_parser_matches_full_validation(self):
        for args in (["hook"], ["--repo", "project", "hook"], ["codex-hook"]):
            self.assertEqual(
                vars(parser(hook_only=True).parse_args(args)), vars(parser().parse_args(args))
            )
        for fast in (False, True):
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                parser(hook_only=fast).parse_args(["hook", "--unexpected"])
            self.assertEqual(error.exception.code, 2)

    def test_hook_text_does_not_change_command_routing(self):
        for args, fast in (
            (["hook"], True),
            (["codex-hook"], True),
            (["--repo", "project", "hook"], True),
            (["claim", "add", "--session", "session", "hook"], False),
        ):
            with (
                patch.object(sys, "argv", ["verix", *args]),
                patch("verix.cli.parser", wraps=parser) as build,
                patch("verix.cli.Engine"),
                patch("verix.cli.run", return_value={}),
                redirect_stdout(io.StringIO()),
            ):
                main()
                build.assert_called_once_with(hook_only=fast)


if __name__ == "__main__":
    unittest.main()
