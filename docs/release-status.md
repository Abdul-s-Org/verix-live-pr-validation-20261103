# V1 implementation and release status

## Implemented candidate

Local sessions and exact file fingerprints; SQLite schema versioning and transactional writes; explicit claims and parent links; alternative evidence groups; four evidence states; conservative session-wide policy decisions; explicit revision-bound reaffirmation and configured checks; saved decision replay; CLI and metadata-only receipts; Claude command-hook adapter; synthetic benchmark; reusable PR workflow; Python CI and wheel build.

## Evidence gathered locally

All 29 tests pass on Python 3.14, including Hypothesis property tests. `python -m pytest --cov=verix.engine --cov-report=term-missing --cov-fail-under=80` reports 96.11% engine statement coverage. Ruff lint and formatting checks pass. Tests cover temporary repositories, propagation, invalid receipts, policy errors, rollback, revision changes, and simulated hooks. The built wheel's installed CLI can execute the fixture benchmark. Python 3.12 and macOS remain CI validation targets.

## Release blockers

- Independently reviewed benchmark scenarios, realistic baseline comparison, and five real-agent runs per scenario/condition; current fixtures are deliberately limited.
- Real Claude Code contract and performance validation, including partial/binary reads and parallel tool calls.
- Hosted GitHub workflow checks on same-repository and fork PRs, comment update behavior, and branch protection configuration.
- Clean Linux/macOS installation timings and hook median/p95 latency measurements.
- Recovery/security review before private-repository pilots, plus customer interviews and design-partner validation.

Version remains `0.1.0` until these gates pass. No subscriptions, dashboard, hosted history, automatic claim extraction, Codex hooks, or semantic-diff optimization are included.
