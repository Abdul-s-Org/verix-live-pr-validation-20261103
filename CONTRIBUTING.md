# Contributing to Verix

Verix is a local-first stale-assumption guard built around deterministic evidence and policy decisions. Contributions should improve capture, correctness, integration reliability, or reproducible evaluation. Read [AGENTS.md](AGENTS.md), [release status](docs/release-status.md), and the relevant product requirements before making a substantial change.

## Set up development

Use Python 3.12+, Git, and Node.js. Python runs the application and tests; Node.js runs the mocked GitHub workflow JavaScript tests. GitHub's Linux, macOS, and Windows runners provide these tools.

```sh
git clone https://github.com/abdulwasea89/Verix.git
cd Verix
```

On Linux/macOS:

```sh
python3 -m venv .venv
. .venv/bin/activate
```

On Windows PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Install the package and development dependencies:

```sh
python -m pip install -e '.[dev]'
```

## Find the right code

| Location | Responsibility |
| --- | --- |
| `src/verix/engine/` | Git access, fingerprints, SQLite, graph analysis, and policy |
| `src/verix/hooks/` | Claude Code capture and settings installation |
| `src/verix/cli.py`, `src/verix/receipts.py` | Commands and metadata interchange |
| `src/verix/benchmark.py`, `src/verix/scenarios.json` | Fixture execution, scoring, and draft labels |
| `tests/` | Unit, subprocess integration, property, race, and workflow tests |
| `scripts/` | Installed-wheel and performance acceptance checks |
| `.github/workflows/` | Platform CI and reusable PR checks |
| `docs/` | Operations, schemas, release acceptance, and product references |

## Make a focused change

- Find every caller before changing shared behavior. Reuse existing helpers and keep validation at filesystem, policy, receipt, and subprocess boundaries.
- Use four-space indentation, `snake_case` functions/modules, and `PascalCase` classes. Ruff owns formatting; the configured line length is 100.
- Add a regression test for a bug or meaningful behavior change. Name tests `test_*.py` and `test_<behavior>`; use temporary Git repositories and synthetic data.
- Preserve deterministic decisions and replayable audit inputs. Changes to policy, receipt, report, or storage contracts must update validation, schemas, callers, tests, and documentation together.
- Do not alter benchmark labels or risk levels merely to improve scores. Keep evidence, hypotheses, and unreviewed results clearly distinguished.

## Check your work

```sh
ruff check .
ruff format --check .
python -m pytest --cov=verix.engine --cov-report=term-missing --cov-fail-under=80
```

To apply formatting, run `ruff format .`. Hypothesis exercises policy and graph properties. Node.js tests mock GitHub APIs and never post comments. CI requires at least 80% engine statement coverage; a passing percentage does not replace tests for the changed behavior.

For packaging, installation, benchmark, or hot-path changes, also run:

```sh
python -m build
python scripts/smoke_install.py
python scripts/check_performance.py
```

Use a clean `dist/` directory containing one wheel for the smoke check. The scripts install into a temporary environment and report synthetic measurements. CI uploads per-platform benchmark, installation, and latency artifacts. Follow up on failures across all three operating systems.

## Submit changes

Use scoped, imperative commit subjects consistent with history, for example `fix: reject stale hook evidence` or `test: cover receipt validation`. Keep commits focused and push only work you have verified. Never force-push a shared branch or bypass protection.

Pull requests should state the problem, the resulting behavior, linked issues or requirement IDs, and checks performed. Document schema/configuration changes, platform limitations, and measured performance changes. Include screenshots only for visible UI changes.

Keep `.verix/`, local Claude settings, credentials, private source, and real customer session data out of Git. Report vulnerabilities through [SECURITY.md](SECURITY.md). Paid agent trials, publishing releases, and changes to hosted services require explicit authorization; synthetic tests do not satisfy external release gates.
