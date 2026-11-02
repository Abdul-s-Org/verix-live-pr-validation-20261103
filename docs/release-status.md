# V1 implementation and release status

## Implemented candidate

Local sessions and exact file fingerprints; SQLite schema versioning and transactional writes; explicit claims and parent links; alternative evidence groups; four evidence states; conservative session-wide policy decisions; explicit revision-bound reaffirmation and configured checks; saved decision replay; CLI and metadata-only receipts; Claude command-hook adapter; synthetic benchmark; reusable PR workflow; Python CI and wheel build.

## Evidence gathered locally

The previous implementation passed 29 tests on Python 3.14, including Hypothesis property tests. The benchmark milestone adds six tests covering the complete suite, independent baseline calculation, metrics, reproducibility, and invalid fixtures. `python -m pytest --cov=verix.engine --cov-report=term-missing --cov-fail-under=80` reports 96.11% engine statement coverage. Ruff lint and formatting checks pass. Tests cover temporary repositories, propagation, invalid receipts, policy errors, rollback, revision changes, and simulated hooks. The built wheel's installed CLI can execute the fixture benchmark. The earlier Linux/Python 3.12 CI job passed; its macOS job remains queued. CI now also runs the benchmark from the installed wheel and uploads per-platform results.

## Benchmark milestone

Replaced the repeated two-claim examples with 30 distinct multi-file fixtures, three-level dependency chains, and unrelated controls. Inputs are validated before fixture creation; labels remain separate from engine results. Hash-baseline results are calculated directly from fingerprints, and raw per-case decisions/commit IDs are emitted. Blocking-mode scoring exposes two false blocks among seven valid actions, so the false-block release gate currently fails. Independent label review and real-agent trials are still required before this milestone's acceptance gate can close.

## Cross-platform CI fixes

The macOS `/var` versus `/private/var` repository alias failure is fixed in shared path validation, with a regression test that also rejects nested symlinks. The Actions matrix includes Linux, macOS, and Windows, with a portable installed-wheel smoke check. Windows fingerprints use Git's tracked executable mode rather than POSIX permission inference. Hosted results for this change must pass before cross-platform acceptance is claimed.

## Release blockers

- Independently reviewed benchmark scenarios, realistic baseline comparison, and five real-agent runs per scenario/condition; current fixtures are deliberately limited.
- Real Claude Code contract and performance validation, including partial/binary reads and parallel tool calls.
- Hosted GitHub workflow checks on same-repository and fork PRs, comment update behavior, and branch protection configuration.
- Clean Linux/macOS installation timings and hook median/p95 latency measurements.
- Recovery/security review before private-repository pilots, plus customer interviews and design-partner validation.

Version remains `0.1.0` until these gates pass. No subscriptions, dashboard, hosted history, automatic claim extraction, Codex hooks, or semantic-diff optimization are included.
