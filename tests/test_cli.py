import os
import subprocess
import sys
import unittest
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


if __name__ == "__main__":
    unittest.main()
