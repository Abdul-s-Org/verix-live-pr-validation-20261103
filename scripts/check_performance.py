"""Measure the local hook process on a 5,000-file synthetic repository; no model calls."""

import json
import io
import math
import os
from pathlib import Path
import pstats
import statistics
import subprocess
import sys
import tempfile
import time

from verix.engine.service import Engine

with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)

    def git(*args):
        subprocess.run(
            [
                "git",
                "-C",
                directory,
                "-c",
                "commit.gpgsign=false",
                "-c",
                "core.autocrlf=false",
                *args,
            ],
            check=True,
            capture_output=True,
            # Fixture setup is outside hook timings and can be slow on shared Windows runners.
            timeout=180,
        )

    git("init", "-q", "--template=")
    git("config", "user.name", "Verix performance fixture")
    git("config", "user.email", "benchmark@example.invalid")
    files = root / "files"
    files.mkdir()
    for number in range(5000):
        (files / f"module_{number}.py").write_text(f"VALUE = {number}\n", newline="\n")
    (root / ".verix.yml").write_text("mode: blocking\nrisk: {'*': high}\n", newline="\n")
    git("add", "files", ".verix.yml")
    git("commit", "-qm", "performance fixture")
    engine = Engine(root)
    try:
        session = engine.start("simulated-hook-performance")
        for number in range(10):
            path = f"files/module_{number}.py"
            engine.observe(session, path)
            engine.claim(session, f"Module {number} defines VALUE", [path], [])
        with engine.store.transaction():
            engine.store.db.execute("UPDATE sessions SET incomplete=0 WHERE id=?", (session,))
    finally:
        engine.store.db.close()
    timings = []
    for number in range(20):
        payload = {
            "session_id": session,
            "hook_event_name": "PreToolUse",
            "tool_name": "Edit",
            "tool_use_id": f"sample-{number}",
            "tool_input": {"file_path": str(files / "module_0.py")},
        }
        started = time.monotonic()
        result = subprocess.run(
            [sys.executable, "-m", "verix", "--repo", directory, "hook"],
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            check=True,
            timeout=10,
        )
        timings.append(time.monotonic() - started)
        context = json.loads(result.stdout)["hookSpecificOutput"]
        assert "Verix allow" in context["additionalContext"], result.stdout
    median = statistics.median(timings)
    p95 = sorted(timings)[math.ceil(0.95 * len(timings)) - 1]
    payload["tool_use_id"] = "profile-sample"
    profile_path = root / "hook-profile.pstats"
    profiled = subprocess.run(
        [
            sys.executable,
            "-m",
            "cProfile",
            "-o",
            str(profile_path),
            "-m",
            "verix",
            "--repo",
            directory,
            "hook",
        ],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=True,
        timeout=10,
    )
    assert "Verix allow" in json.loads(profiled.stdout)["hookSpecificOutput"]["additionalContext"]
    profile_text = io.StringIO()
    pstats.Stats(str(profile_path), stream=profile_text).sort_stats("cumulative").print_stats(40)
    report = {
        "files": 5000,
        "observations": 10,
        "samples": len(timings),
        "python": sys.version,
        "platform": sys.platform,
        "median_seconds": median,
        "p95_seconds": p95,
        "targets_met": median <= 0.3 and p95 <= 1,
        "profile_top": profile_text.getvalue(),
        "limits": "Simulated hook command process; excludes actual agent transport and model latency.",
    }
    output_directory = (
        Path(os.environ["RUNNER_TEMP"])
        if "RUNNER_TEMP" in os.environ
        else Path(tempfile.mkdtemp(prefix="verix-performance-results-"))
    )
    target = output_directory / "verix-performance.json"
    target.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
