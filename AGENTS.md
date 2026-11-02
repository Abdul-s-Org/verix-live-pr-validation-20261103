# Repository Guidelines

## Project Structure

Verix is a Python CLI for detecting stale coding-agent evidence. `src/verix/engine/` owns Git access, fingerprints, SQLite, evidence propagation, and policy. `src/verix/hooks/` contains the Claude Code adapter. CLI commands, receipts, and the benchmark live in `src/verix/`; packaged scenarios are in `scenarios.json`.

Use `tests/` for unit, integration, property, race, and workflow tests. `scripts/` contains installation/performance checks; `.github/workflows/` runs Linux, macOS, and Windows CI. Keep operational documentation and JSON schemas in `docs/`. Product PDFs describe intent; `docs/release-status.md` distinguishes implementation from accepted release evidence.

## Development and Checks

Use Python 3.12+, Git, and Node.js for workflow JavaScript tests. Install with `python -m pip install -e '.[dev]'` inside a virtual environment.

```sh
ruff check .
ruff format --check .
python -m pytest --cov=verix.engine --cov-report=term-missing --cov-fail-under=80
python -m build
```

For packaging or performance changes, also run `python scripts/smoke_install.py` with one wheel in `dist/`, and `python scripts/check_performance.py`. Inspect hosted checks and artifacts across all three operating systems.

## Implementation Rules

Choose the smallest complete change. Inspect every caller before fixing shared behavior; reuse existing helpers and avoid unnecessary dependencies or abstractions. Use four-space indentation, `snake_case`, `PascalCase` classes, and Ruff's 100-column configuration.

Add meaningful regression tests named `test_*.py`. Use temporary repositories and synthetic inputs. Preserve validation, error handling, deterministic verdicts, revision/content/policy binding, and audit replay. Never trade those guarantees for latency. Contract changes must update schemas, validation, callers, tests, and docs together.

## Commits and Release Discipline

Use scoped imperative subjects such as `fix: reject stale evidence`. After authorized implementation, run relevant checks, commit focused changes, and push to the requested branch. Respect branch protection and never force-push shared history.

Keep runtime databases, local settings, secrets, private source, and customer data out of commits. Benchmark labels remain drafts until independently reviewed. Report measured latency and failures honestly; passing automated tests does not close real-agent, live-integration, or customer-validation gates. Paid agent trials and release publishing require subsequent explicit authorization.
