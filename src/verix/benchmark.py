"""Reproducible fixture evaluation with an independently computed hash-only baseline."""

from collections import Counter
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import subprocess
import tempfile
import time

from verix.engine.git import VerixError, equivalent
from verix.engine.policy import evaluate
from verix.engine.service import Engine

FAMILIES = {
    "rename": 6,
    "behavior": 6,
    "config": 5,
    "dependency": 4,
    "irrelevant": 5,
    "formatting": 2,
    "hidden": 2,
}


def _path(value):
    if not isinstance(value, str) or not value or "\0" in value:
        raise VerixError("Scenario paths must be nonempty strings")
    path = PurePosixPath(value)
    if (
        PureWindowsPath(value).drive
        or "\\" in value
        or str(path) != value
        or path.is_absolute()
        or any(part in ("..", ".git", ".verix") for part in path.parts)
        or str(path) == "."
    ):
        raise VerixError("Scenario path must stay inside the fixture repository")
    return value


def validate(cases) -> list[dict]:
    if not isinstance(cases, list) or len(cases) != 30:
        raise VerixError("Benchmark requires 30 scenarios")
    ids = set()
    for case in cases:
        fields = {
            "id",
            "family",
            "files",
            "changes",
            "reads",
            "claims",
            "expected_affected",
            "action",
        }
        if not isinstance(case, dict) or set(case) != fields:
            raise VerixError("Scenario fields must match the documented fixture format")
        if not isinstance(case["id"], str) or not case["id"] or case["id"] in ids:
            raise VerixError("Scenario IDs must be unique nonempty strings")
        ids.add(case["id"])
        if not isinstance(case["family"], str) or case["family"] not in FAMILIES:
            raise VerixError("Unknown scenario family")
        for field in ("files", "changes"):
            if not isinstance(case[field], dict) or not case[field]:
                raise VerixError(f"Scenario {field} must be a nonempty file mapping")
            for path, content in case[field].items():
                _path(path)
                if not isinstance(content, str) and not (field == "changes" and content is None):
                    raise VerixError("File content must be text; deletion uses null")
        if not any(case["files"].get(path) != text for path, text in case["changes"].items()):
            raise VerixError("Scenario changes must actually change a file")
        reads = case["reads"]
        if not isinstance(reads, list) or any(
            not isinstance(p, str) or p not in case["files"] for p in reads
        ):
            raise VerixError("Every read must name an initial fixture file")
        if len(reads) != len(set(reads)):
            raise VerixError("Duplicate fixture reads")
        if not isinstance(case["claims"], list) or not case["claims"]:
            raise VerixError("Scenario requires explicit claims")
        known = set()
        for claim in case["claims"]:
            if not isinstance(claim, dict) or set(claim) != {"id", "text", "evidence", "parents"}:
                raise VerixError("Invalid scenario claim fields")
            if (
                any(not isinstance(claim[k], str) or not claim[k] for k in ("id", "text"))
                or claim["id"] in known
            ):
                raise VerixError("Claim IDs must be unique and claim text nonempty")
            if not isinstance(claim["evidence"], list) or any(
                not isinstance(p, str) or p not in reads for p in claim["evidence"]
            ):
                raise VerixError("Claim evidence must have been read")
            if not isinstance(claim["parents"], list) or any(
                not isinstance(p, str) or p not in known for p in claim["parents"]
            ):
                raise VerixError("Claim parents must precede their children; cycles are forbidden")
            known.add(claim["id"])
        labels = case["expected_affected"]
        if not isinstance(labels, list) or any(
            not isinstance(p, str) or p not in known for p in labels
        ):
            raise VerixError("Ground truth must name defined claims")
        if len(labels) != len(set(labels)):
            raise VerixError("Duplicate ground-truth labels")
        action = case["action"]
        if not isinstance(action, dict) or set(action) != {"path", "risk", "valid"}:
            raise VerixError("Invalid scenario action")
        _path(action["path"])
        if action["risk"] not in ("low", "medium", "high") or type(action["valid"]) is not bool:
            raise VerixError("Action requires a supported risk and boolean validity label")
        # Reject conflicting file/directory definitions before touching the filesystem.
        paths = list(case["files"]) + list(case["changes"])
        if any(str(parent) in paths for p in paths for parent in PurePosixPath(p).parents):
            raise VerixError("Fixture file paths cannot also be directories")
    if Counter(c["family"] for c in cases) != Counter(FAMILIES):
        raise VerixError("Scenario family counts must match the 30-case protocol")
    return cases


def load(path: Path) -> list[dict]:
    def unique(pairs):
        data = {}
        for key, value in pairs:
            if key in data:
                raise VerixError(f"Duplicate JSON field: {key}")
            data[key] = value
        return data

    try:
        if path.stat().st_size > 2_000_000:
            raise VerixError("Scenario file exceeds 2 MB")
        return validate(json.loads(path.read_text(), object_pairs_hook=unique))
    except (OSError, ValueError, RecursionError) as exc:
        raise VerixError(f"Cannot read benchmark scenarios: {exc}") from exc


def _run_case(case, ignore_python_formatting=False):
    start = time.monotonic()
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)

        def git(*args):
            try:
                return subprocess.run(
                    [
                        "git",
                        "-C",
                        directory,
                        "-c",
                        "commit.gpgsign=false",
                        "-c",
                        f"core.hooksPath={root / 'disabled-hooks'}",
                        "-c",
                        "core.autocrlf=false",
                        *args,
                    ],
                    check=True,
                    capture_output=True,
                    timeout=10,
                    env={
                        **os.environ,
                        "GIT_AUTHOR_DATE": "2000-01-01T00:00:00+00:00",
                        "GIT_COMMITTER_DATE": "2000-01-01T00:00:00+00:00",
                    },
                ).stdout
            except (OSError, subprocess.SubprocessError) as exc:
                raise VerixError(f"Fixture Git operation failed in {case['id']}") from exc

        def write(files):
            for path, content in files.items():
                target = root / path
                if content is None:
                    target.unlink(missing_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(content, encoding="utf-8", newline="\n")

        git("init", "-q", "--template=")
        git("config", "user.name", "Verix benchmark")
        git("config", "user.email", "benchmark@example.invalid")
        write(case["files"])
        git("add", "--", *case["files"])
        git("commit", "-qm", "fixture before")
        engine = Engine(root)
        try:
            engine.policy["ignore_python_formatting"] = ignore_python_formatting
            session = engine.start("benchmark")
            recorded = {}
            for path in case["reads"]:
                engine.observe(session, path)
                recorded[path] = engine.repo.fingerprint(
                    path, python_formatting=ignore_python_formatting
                )
            claims = {}
            for claim in case["claims"]:
                claims[claim["id"]] = engine.claim(
                    session, claim["text"], claim["evidence"], [claims[p] for p in claim["parents"]]
                )
            with engine.store.transaction():
                engine.store.db.execute("UPDATE sessions SET incomplete=0 WHERE id=?", (session,))
            write(case["changes"])
            # Explicit paths keep runtime databases out of fixture commits.
            git("add", "--all", "--", *case["changes"])
            git("commit", "-qm", "fixture after")
            changed_reads = {
                path
                for path, original in recorded.items()
                if not equivalent(
                    original,
                    engine.repo.fingerprint(path, python_formatting=ignore_python_formatting),
                    ignore_python_formatting,
                )
            }
            baseline = {
                claim["id"]
                for claim in case["claims"]
                if changed_reads.intersection(claim["evidence"])
            }
            engine.policy["mode"] = "blocking"
            engine.policy["risk"] = {case["action"]["path"]: case["action"]["risk"]}
            report = engine.analyze(session)
            states = {name: report["states"][key] for name, key in claims.items()}
            decision = engine.check(session, case["action"]["path"])
            return {
                "id": case["id"],
                "family": case["family"],
                "before_sha": engine.store.session(session)["base"],
                "after_sha": report["revision"],
                "expected_affected": case["expected_affected"],
                "action": case["action"],
                "states": states,
                "changed_reads": sorted(changed_reads),
                "conditions": {
                    "no_guard": {"flags": [], "verdict": "allow"},
                    "file_hash": {
                        "flags": sorted(baseline),
                        "verdict": evaluate(
                            ["suspect"] if baseline else ["valid"], case["action"]["risk"], False
                        ),
                    },
                    "verix": {
                        "flags": sorted(
                            name for name, state in states.items() if state == "suspect"
                        ),
                        "verdict": decision["verdict"],
                    },
                },
                "seconds": time.monotonic() - start,
            }
        finally:
            engine.store.db.close()


def summarize(results):
    totals = {}
    for condition in ("no_guard", "file_hash", "verix"):
        metric = dict.fromkeys(
            (
                "tp",
                "fp",
                "fn",
                "valid_actions",
                "false_blocks",
                "invalid_actions",
                "unsafe_allows",
                "unresolved_actions",
            ),
            0,
        )
        for case in results:
            flags = set(case["conditions"][condition]["flags"])
            expected = set(case["expected_affected"])
            verdict = case["conditions"][condition]["verdict"]
            metric["tp"] += len(flags & expected)
            metric["fp"] += len(flags - expected)
            metric["fn"] += len(expected - flags)
            metric["valid_actions"] += int(case["action"]["valid"])
            metric["false_blocks"] += int(case["action"]["valid"] and verdict == "block")
            metric["invalid_actions"] += int(not case["action"]["valid"])
            metric["unsafe_allows"] += int(not case["action"]["valid"] and verdict == "allow")
            metric["unresolved_actions"] += int(verdict == "unresolved")
        for name, numerator, denominator in (
            ("recall", metric["tp"], metric["tp"] + metric["fn"]),
            ("precision", metric["tp"], metric["tp"] + metric["fp"]),
            ("false_block_rate", metric["false_blocks"], metric["valid_actions"]),
            ("unsafe_allow_rate", metric["unsafe_allows"], metric["invalid_actions"]),
        ):
            metric[name] = numerator / denominator if denominator else None
        totals[condition] = metric
    return totals


def run(scenarios: Path | None = None, ignore_python_formatting: bool = False) -> dict:
    cases = load(scenarios or Path(__file__).parent / "scenarios.json")
    results = [_run_case(case, ignore_python_formatting) for case in cases]
    return {
        "schema_version": 2,
        "ignore_python_formatting": ignore_python_formatting,
        "label_status": "draft; independent review required",
        "conditions": summarize(results),
        "scenarios": results,
        "limits": "Synthetic fixtures, opt-in blocking, no real-agent trials. Hash baseline flags direct evidence only and does not propagate dependencies. Not release evidence.",
    }
