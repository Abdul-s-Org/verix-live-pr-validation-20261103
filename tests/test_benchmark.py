import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from verix import benchmark
from verix.engine.git import VerixError
from verix.engine.service import Engine

SCENARIOS = Path(benchmark.__file__).with_name("scenarios.json")


class BenchmarkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = benchmark.load(SCENARIOS)
        cls.report = benchmark.run()

    def test_complete_protocol_and_unrelated_claims(self):
        self.assertEqual(len(self.report["scenarios"]), 30)
        self.assertEqual(self.report["schema_version"], 2)
        self.assertIn("draft", self.report["label_status"])
        for result in self.report["scenarios"]:
            self.assertEqual(result["states"]["unrelated"], "valid")
            self.assertEqual(len(result["before_sha"]), 40)
            self.assertNotEqual(result["before_sha"], result["after_sha"])
            if result["family"] in ("rename", "behavior", "config", "dependency"):
                self.assertEqual(
                    result["conditions"]["verix"]["flags"], ["contract", "edit", "plan"]
                )
                self.assertEqual(result["conditions"]["file_hash"]["flags"], ["contract"])
                self.assertEqual(result["conditions"]["verix"]["verdict"], "block")
            elif result["family"] == "irrelevant":
                self.assertEqual(result["conditions"]["verix"]["flags"], [])
                self.assertEqual(result["conditions"]["verix"]["verdict"], "allow")
            elif result["family"] == "hidden":
                self.assertEqual(result["states"]["contract"], "unknown")
                self.assertEqual(result["conditions"]["verix"]["verdict"], "unresolved")

    def test_metrics_include_benign_blocks_and_unknown_misses(self):
        totals = self.report["conditions"]
        self.assertEqual(totals["verix"]["tp"], 63)
        self.assertEqual(totals["verix"]["fn"], 6)
        self.assertEqual(totals["verix"]["false_blocks"], 2)
        self.assertEqual(totals["verix"]["valid_actions"], 7)
        self.assertEqual(totals["verix"]["unresolved_actions"], 2)
        self.assertEqual(totals["no_guard"]["unsafe_allows"], 23)
        self.assertAlmostEqual(totals["verix"]["false_block_rate"], 2 / 7)
        self.assertIsNone(benchmark.summarize([])["verix"]["recall"])

    def test_hash_baseline_does_not_use_verix_states(self):
        analyze = Engine.analyze

        def suppress_flags(engine, session, head=None):
            report = analyze(engine, session, head)
            report["states"] = {key: "valid" for key in report["states"]}
            return report

        with patch.object(Engine, "analyze", autospec=True, side_effect=suppress_flags):
            result = benchmark._run_case(self.cases[0])
        self.assertEqual(result["conditions"]["verix"]["flags"], [])
        self.assertEqual(result["conditions"]["file_hash"]["flags"], ["contract"])

    def test_fixture_commits_are_reproducible(self):
        first = self.report["scenarios"][0]
        repeated = benchmark._run_case(self.cases[0])
        self.assertEqual(first["before_sha"], repeated["before_sha"])
        self.assertEqual(first["after_sha"], repeated["after_sha"])

    def test_invalid_fixtures_rejected_before_running_git(self):
        mutations = [
            lambda cases: cases.pop(),
            lambda cases: cases[0].update(id=cases[1]["id"]),
            lambda cases: cases[0].update(family="unsupported"),
            lambda cases: cases[0].update(files={"../outside": "bad"}),
            lambda cases: cases[0].update(files={".git/config": "bad"}),
            lambda cases: cases[0].update(files={"/absolute": "bad"}),
            lambda cases: cases[0].update(files={"C:/outside": "bad"}),
            lambda cases: cases[0].update(files={"folder\\outside": "bad"}),
            lambda cases: cases[0].update(files={"./alias": "bad"}),
            lambda cases: cases[0].update(changes={"loader.py": 42}),
            lambda cases: cases[0].update(changes={"loader.py": cases[0]["files"]["loader.py"]}),
            lambda cases: cases[0].update(reads=["absent"]),
            lambda cases: cases[0]["claims"][0].update(parents=["edit"]),
            lambda cases: cases[0]["claims"][0].update(evidence=["absent"]),
            lambda cases: cases[0].update(expected_affected=["absent"]),
            lambda cases: cases[0]["action"].update(valid="true"),
            lambda cases: cases[0]["files"].update({"a": "file", "a/b/c": "child"}),
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "scenarios.json"
            for mutation in mutations:
                cases = copy.deepcopy(self.cases)
                mutation(cases)
                path.write_text(json.dumps(cases))
                with self.subTest(mutation=mutation), patch("subprocess.run") as git:
                    with self.assertRaises(VerixError):
                        benchmark.run(path)
                    git.assert_not_called()

    def test_load_errors_are_actionable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "scenarios.json"
            for value in ("not JSON", '{"duplicate": 1, "duplicate": 2}', "null"):
                path.write_text(value)
                with self.assertRaises(VerixError):
                    benchmark.load(path)
            path.unlink()
            with self.assertRaises(VerixError):
                benchmark.load(path)
