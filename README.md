# Verix

[![CI](https://github.com/abdulwasea89/Verix/actions/workflows/ci.yml/badge.svg)](https://github.com/abdulwasea89/Verix/actions/workflows/ci.yml)

**Find the assumptions that went stale while your coding agent was working.**

Verix connects an agent's observed file reads to explicit claims, compares that evidence with the current repository, and tells you what needs rechecking. It runs locally with Python, Git, and SQLite. No account, model API key, or hosted service is required.

**Release status:** `0.1.0`, a development candidate. Automated CI covers Linux, macOS, and Windows. Real-agent evaluation and release acceptance are tracked in [release status](docs/release-status.md).

## Why Verix

An agent reads your authentication module and plans work assuming it uses JWT. While it works, another change introduces server-side sessions. The resulting pull request can merge without a text conflict even though its assumptions need another look.

Verix records the supporting evidence, flags the changed source, and follows the affected claim through dependent decisions and proposed edits. A changed file makes a claim **suspect**, not automatically false.

## What is included

- Exact content fingerprints, Git revisions, and file modes, including uncommitted local changes.
- Explicit claims, transitive dependencies, and independently declared alternative evidence.
- Repository policies with advisory or blocking behavior and per-path risk levels.
- Revision-, evidence-, and policy-bound verification with replayable decision history.
- Claude Code capture plus an experimental Codex adapter for exact `cat` reads and native patches.
- Metadata-only session receipts and a reusable GitHub Actions PR workflow.
- A reproducible 30-case fixture benchmark with raw results and baseline comparisons.

## Installation

Requirements: Python 3.12 or newer and Git on your PATH. Install from the repository; no PyPI release is advertised.

```sh
git clone https://github.com/abdulwasea89/Verix.git
cd Verix
```

Create and activate a virtual environment:

**Linux / macOS**

```sh
python3 -m venv .venv
. .venv/bin/activate
```

**Windows PowerShell**

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Then install and verify:

```sh
python -m pip install .
verix --version
verix --help
```

For reproducible team installations, check out a reviewed commit before installing. Contributor tooling and tests are described in [CONTRIBUTING.md](CONTRIBUTING.md).

## Quick start

From the Git repository you want to check, with at least one existing commit:

```sh
verix init
verix session start --agent manual
```

Add these entries to your project's `.gitignore` to keep local state out of commits;
`verix init` does not edit that file:

```gitignore
.verix/
.claude/settings.local.json
```

Copy the returned session ID. Replace `SESSION_ID` below and choose an existing file in your project:

```sh
verix read README.md --session SESSION_ID
verix claim add 'README describes the project setup' --session SESSION_ID --evidence README.md
verix session complete --session SESSION_ID --ack-limitations
verix check --session SESSION_ID --path README.md
verix report --session SESSION_ID
```

Use `--repo PATH` before the command to check a repository from another directory. Add `--json` to `report` for machine-readable output.

Completing a session acknowledges your capture assessment. It does not establish that every relevant dependency was observed.

### When evidence changes

Inspect the current source and its diff. If the claim still holds, explicitly reaffirm it:

```sh
verix verify CLAIM_ID --session SESSION_ID --reaffirm
```

For a configured verification command, add `--check CHECK_NAME`. Commands execute only when explicitly requested and require reaffirmation too. If an assumption is false, start a fresh session with corrected claims rather than reaffirming it. A subsequent evidence, revision, or policy change expires successful verification.

## Configuration

`verix init` creates `.verix.yml`. Keep it in version control:

```yaml
version: 1
mode: advisory
risk:
  'app/auth/*': high
  'migrations/*': high
  'docs/*': low
exclude:
  - '.env*'
  - '.verix/*'
  - 'secrets/*'
ignore_python_formatting: false
checks:
  auth: ['python', '-m', 'pytest', 'tests/test_auth.py']
```

The highest matching risk wins; unmatched paths are medium risk. Blocking requires `mode: blocking`. Optional Python formatting normalization compares parsed syntax while retaining raw hashes; it is off by default. See [configuration and operations](docs/usage.md) for matching rules, verification behavior, and recovery.

| Exit code | `verix check` result |
| --- | --- |
| `0` | Allow |
| `10` | Verify |
| `20` | Block |
| `30` | Unresolved |
| `1` | Operational error |
| `2` | Invalid command arguments |

Local `check` exposes its verdict through the exit code. Advisory hook/CI integrations do not block on policy findings; operational failures are surfaced separately.

## Claude Code integration

```sh
verix init --hooks
```

This merges handlers into `.claude/settings.local.json` without replacing existing settings. The hook's `session_id` identifies the session to use when registering claims. Capture persists across compaction. Only full Read responses matching exact observed bytes become complete evidence; partial or unfamiliar responses remain unknown.

Claims are explicit in this release. Reads through Bash, unsupported tools, or bypassed hooks are outside capture coverage. Windows CLI/engine checks run in CI; the actual Windows Claude Code hook shell still requires live validation.

## Codex integration (experimental)

```sh
verix init --hooks --agent codex
```

This merges `.codex/hooks.json`. Start Codex from the repository root, enable its hooks feature, and review/trust the hooks through `/hooks`. Existing Codex configuration is preserved. See [Codex setup and live evidence](docs/codex.md).

The adapter captures single literal `cat path` reads and checks every native `apply_patch` target. Register claims explicitly. Every read or unsupported command makes session capture incomplete; after reviewing evidence, use `verix session complete --session SESSION_ID --ack-limitations`. In blocking mode unsupported commands are denied. Start in advisory mode: this narrow adapter does not cover ordinary unrestricted shell workflows.

## Pull request checks

Export and inspect a receipt, then include it in your branch. This redirection example works in Bash and PowerShell 7:

```sh
verix receipt export --session SESSION_ID > .verix-receipt.json
```

Receipts omit file bodies, claim text, and local approval assertions. Paths and hashes can still be sensitive. CI needs refreshed reads and newly registered claims to represent renewed evidence; it does not accept exported approval assertions as proof.

Add a consumer workflow:

```yaml
name: Verix
on: [pull_request]
permissions:
  contents: read
  actions: read
  pull-requests: write
jobs:
  check:
    uses: abdulwasea89/Verix/.github/workflows/verix-pr.yml@main
    with:
      receipt: .verix-receipt.json
      tool-ref: main
```

Pin both `main` references to the same reviewed Verix commit for production use. Analysis uses base-branch policy and exact base/head commits, without executing PR commands. Same-repository PRs can receive one updated comment; forks receive job summaries and artifacts. Require the check and an up-to-date branch in your merge policy. [Operational details](docs/usage.md) cover permissions and limits.

## Evaluation and project links

```sh
verix bench run
verix bench run --ignore-python-formatting
```

These run synthetic fixtures, not paid agents. Labels remain drafts pending independent review. Exact-byte mode still flags the benign formatting fixtures; the explicit normalization mode handles those cases. Do not interpret fixture scores as measured real-world reliability.

- [Benchmark protocol](benchmark/README.md)
- [Release acceptance](docs/release-status.md)
- [Contributing](CONTRIBUTING.md)
- [Agent instructions](AGENTS.md)
- [Security and reporting](SECURITY.md)
- [Product plan](docs/verix_prd.pdf) and [problem research](docs/verix_prob.pdf)

Verix checks observed and declared evidence. It cannot prove a claim or pull request correct. Receipts are self-reported, and hooks are not a security boundary. The dashboard, hosted subscriptions, automatic LLM extraction, and integrations beyond Claude Code and the experimental Codex adapter are outside this release.
