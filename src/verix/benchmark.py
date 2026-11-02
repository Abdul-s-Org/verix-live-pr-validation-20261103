"""Reproducible deterministic fixture benchmark; not a substitute for real-agent trials."""

import json
from pathlib import Path
import subprocess
import tempfile
import time

from verix.engine.git import VerixError
from verix.engine.service import Engine


def run(scenarios: Path | None = None) -> dict:
    if scenarios is None:
        scenarios = Path(__file__).parent / "scenarios.json"
    cases = json.loads(scenarios.read_text())
    if len(cases) != 30 or len({c["id"] for c in cases}) != 30:
        raise VerixError("Benchmark requires 30 uniquely identified scenarios")
    totals = {
        condition: {"tp": 0, "fp": 0, "fn": 0, "valid_actions": 0, "false_blocks": 0}
        for condition in ("no_guard", "file_hash", "verix")
    }
    results = []
    for case in cases:
        start = time.monotonic()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            def git(*args):
                return subprocess.run(
                    ["git", "-C", directory, *args], check=True, capture_output=True
                ).stdout

            git("init", "-q")
            git("config", "user.name", "Verix benchmark")
            git("config", "user.email", "benchmark@example.invalid")
            (root / "source.py").write_text(case["before"])
            git("add", "source.py")
            git("commit", "-qm", "fixture before")
            engine = Engine(root)
            try:
                session = engine.start("benchmark")
                if case["family"] != "hidden":
                    engine.observe(session, "source.py")
                claim = engine.claim(
                    session,
                    "Source contract",
                    [] if case["family"] == "hidden" else ["source.py"],
                    [],
                )
                child = engine.claim(session, "Plan depends on source contract", [], [claim])
                with engine.store.transaction():
                    engine.store.db.execute(
                        "UPDATE sessions SET incomplete=0 WHERE id=?", (session,)
                    )
                if case["family"] == "rename":
                    git("mv", "source.py", "renamed.py")
                elif case["family"] == "irrelevant":
                    (root / "notes.md").write_text(case["after"])
                else:
                    (root / "source.py").write_text(case["after"])
                git("add", ".", ":!.verix")
                git("commit", "-qm", "fixture after")
                report = engine.analyze(session)
                expected = {claim, child} if case["affected"] else set()
                predicted = {key for key in (claim, child) if report["states"][key] == "suspect"}
                direct = {claim} if report["states"][claim] == "suspect" else set()
                decision = engine.check(session, "source.py")
                for condition, flags in (
                    ("no_guard", set()),
                    ("file_hash", direct),
                    ("verix", predicted),
                ):
                    metric = totals[condition]
                    metric["tp"] += len(flags & expected)
                    metric["fp"] += len(flags - expected)
                    metric["fn"] += len(expected - flags)
                    if not case["affected"]:
                        metric["valid_actions"] += 1
                        metric["false_blocks"] += int(
                            condition == "verix" and decision["verdict"] == "block"
                        )
                results.append(
                    {
                        "id": case["id"],
                        "family": case["family"],
                        "states": [report["states"][key] for key in (claim, child)],
                        "seconds": time.monotonic() - start,
                    }
                )
            finally:
                engine.store.db.close()
    for metric in totals.values():
        metric["recall"] = (
            metric["tp"] / (metric["tp"] + metric["fn"]) if metric["tp"] + metric["fn"] else None
        )
        metric["precision"] = (
            metric["tp"] / (metric["tp"] + metric["fp"]) if metric["tp"] + metric["fp"] else None
        )
        metric["false_block_rate"] = (
            metric["false_blocks"] / metric["valid_actions"] if metric["valid_actions"] else None
        )
    return {
        "schema_version": 1,
        "label_status": "draft; independent review required",
        "conditions": totals,
        "scenarios": results,
        "limits": "Synthetic two-claim fixtures; file-hash baseline flags direct claims only. No agent trials, recovery or completion measurements. Not release evidence.",
    }
