"""Assert that a built wheel installs and runs outside the source checkout on each OS."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import venv

wheels = list(Path("dist").glob("*.whl"))
assert len(wheels) == 1, "Build exactly one wheel before the installation smoke check"
started = time.monotonic()
with tempfile.TemporaryDirectory(dir=os.environ.get("RUNNER_TEMP")) as directory:
    root = Path(directory)
    venv.create(root / "env", with_pip=True)
    python = root / "env" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    subprocess.run([str(python), "-m", "pip", "install", str(wheels[0].resolve())], check=True)
    installed_seconds = time.monotonic() - started
    assert installed_seconds < 600, "Installation exceeded the ten-minute target"
    for argument in ("--help", "--version"):
        subprocess.run([str(python), "-m", "verix", argument], cwd=root, check=True)
    output = subprocess.run(
        [str(python), "-m", "verix", "bench", "run"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    report = json.loads(output)
    assert report["schema_version"] == 2 and len(report["scenarios"]) == 30
    report["installation_seconds"] = installed_seconds
    report["installation_and_benchmark_seconds"] = time.monotonic() - started
    output_directory = (
        Path(os.environ["RUNNER_TEMP"])
        if "RUNNER_TEMP" in os.environ
        else Path(tempfile.mkdtemp(prefix="verix-install-results-"))
    )
    target = output_directory / "verix-benchmark.json"
    target.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Installed wheel smoke check passed; report: {target}")
