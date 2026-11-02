# Verix

Verix records observed coding-agent reads and explicit claims, detects changed evidence, and reports assumptions that need rechecking. The deterministic Python engine works locally with Git and SQLite. LLMs and hosted services are not required.

**Status:** development implementation targeting V1, not a production release. Independent benchmark review, real-agent trials, live GitHub integration, and clean-machine acceptance checks remain outstanding. See [release status](docs/release-status.md).

## Install and develop

Use Python 3.12 or newer and Git. CI tests Linux, macOS, and Windows. On Linux/macOS:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
verix --help
python -m pytest --cov=verix.engine --cov-fail-under=80
ruff check .
ruff format --check .
python -m build
```

On Windows PowerShell, create and activate the environment with `py -3.12 -m venv .venv` and `.venv\Scripts\Activate.ps1`, then run the same `python -m pip`, pytest, Ruff, and build commands above. The CI Windows engine/CLI checks do not substitute for real Claude Code hook-shell validation.

The runtime dependency is PyYAML. With that available, `PYTHONPATH=src python3 -m unittest discover -s tests -v` runs the local tests without installing the development toolchain; Hypothesis tests are skipped when unavailable.

## Local workflow

Run inside an existing Git repository with at least one commit:

```sh
verix init
verix session start --agent manual
# Use the returned session ID for SESSION below.
verix read app/auth.py --session SESSION
verix claim add 'Authentication uses JWT' --session SESSION --evidence app/auth.py
verix session complete --session SESSION --ack-limitations
verix check --session SESSION --path app/middleware.py
verix report --session SESSION --json
```

After evidence changes, inspect the current file and explicitly reaffirm the relevant claim using `verix verify CLAIM_ID --session SESSION --reaffirm`. This records a revision-bound acknowledgement, not proof that the claim is true. Configured tests require both `--check NAME` and `--reaffirm`. A later evidence or revision change reopens successful verification.

`verix check` exits `0` for allow, `10` for verify, `20` for block, and `30` for unresolved. Operational errors exit `1`; argument errors exit `2`. Advisory hook/CI integrations do not block on policy findings. A local `check` always exposes its verdict through its exit status.

## Agent and PR integration

`verix init --hooks` merges handlers into `.claude/settings.local.json`, preserving other settings. Hooks capture Read/Edit/Write activity and persist across compaction. Only full read responses matching exact current bytes are complete evidence; partial or unfamiliar response shapes stay unknown. Bash, other tools, and bypassed hooks are outside capture coverage. Session completeness requires explicit operator acknowledgement.

Export with `verix receipt export --session SESSION > .verix-receipt.json`, review its metadata, and commit the receipt with the PR. Claim text and local verification approvals are omitted. CI needs refreshed observations and newly registered claims to show renewed evidence; it does not trust exported approval assertions.

See [configuration and CI](docs/usage.md) for policy examples and workflow setup. See [benchmark protocol](benchmark/README.md) before interpreting `verix bench run` output.

## Layout

- `src/verix/engine/`: Git fingerprints, SQLite, evidence propagation, and policy.
- `src/verix/hooks/`: Claude Code adapter.
- `tests/`: unit, integration, and optional property tests.
- `docs/`: product PDFs, operational guidance, and JSON schemas.
- `benchmark/`: benchmark protocol; packaged scenarios live in `src/verix/scenarios.json`.

Read [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md) before contributing. Verix cannot establish that a PR is correct; receipts are self-reported and hooks are not a security boundary.
