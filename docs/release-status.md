# V1 implementation and acceptance status

Version remains `0.1.0` while release acceptance is open. This is a working development candidate, not a claim that every product gate has passed.

## Milestone handoff

| Milestone | Implemented and automated | Remaining acceptance |
| --- | --- | --- |
| 1. Foundation | Package, CLI, lint/format, coverage, wheel/sdist builds, clean-environment install, Linux/macOS/Windows Actions matrix | Latest commit must pass all three hosted jobs |
| 2. Benchmark | 30 distinct fixtures, validated file/claim/action definitions, reproducible commits, independently calculated baseline, raw results and metrics | Independent label review and realistic baseline review |
| 3. Persistence | SQLite schema version 1, transactional writes, nested rollback, isolation, audit records | Future schema changes require explicit migrations |
| 4. Capture/detection | Exact reads, optional Python AST digest, changes/renames/deletions/mode checks, root aliases, path/symlink protections | Actual-agent capture coverage must be measured |
| 5. Impact engine | Transitive suspicion, unrelated controls, explicit alternative evidence groups, unknown evidence | Real repository dependency coverage is unproven |
| 6. Policy/verification | Validated policy, allow/verify/block/unresolved, explicit reaffirmation/checks, revision/content/policy-bound approvals, deterministic replay | Human confirmation remains a trust input |
| 7. CLI/hooks | Session lifecycle, Read/Edit/Write capture, idempotent settings merge, compaction persistence, concurrent-event/race regressions | Real Claude Code sessions and Windows hook-shell validation |
| 8. PR integration | Trusted-base policy, untrusted receipts, exact SHAs, fork permission isolation, one-comment update, stale-run suppression, JSON artifacts | Live same-repository/fork PR permissions and branch protection |
| 9. Evaluation/release | Installed-wheel benchmark smoke check and installation timing, 5,000-file simulated hook latency check, operational/security documentation | Reviewed real-agent trials, customer validation, final release decision |

## Verified automated evidence

The path-fix CI run passed all Linux, macOS, and Windows jobs: [run 41518933457](https://github.com/abdulwasea89/Verix/actions/runs/41518933457). Each job includes tests, coverage, lint/format, package building, and installed-wheel benchmark execution. Follow-up commits add further hook, PR, and performance checks; inspect their own runs before relying on them.

The local suite has 60 tests plus parameterized subtests. Engine statement coverage is 94.47% on Python 3.14, exceeding the 80% threshold. Workflow JavaScript tests execute under Node.js with mocked GitHub APIs; they do not post comments. The CI matrix supplies Node.js.

The latency optimization passed all three hosted platforms in [run 41524531590](https://github.com/abdulwasea89/Verix/actions/runs/41524531590). Windows measured a 297 ms median and 313 ms p95 across the same 20 samples on a 5,000-file fixture, meeting the proposed 300 ms / 1 s targets on that runner. The earlier measurements were 672 ms and then 391 ms median. The final optimization removes redundant filesystem calls and guards the batched index modes with content and file-identity snapshots. Tests reject concurrent index rewrites even when original bytes are restored; linked worktrees and custom Git layouts retain full Git-based checks.

These measurements cover simulated hook command processes, not actual Claude Code transport. They are hardware/runner dependent, not a service-level guarantee. CI uploads each platform's own measurements and explicitly reports target misses. Follow-up commits must be evaluated against their own results.

## Benchmark limits

Default exact-byte blocking produces two false blocks among seven valid fixture actions. `verix bench run --ignore-python-formatting` applies the same explicit normalization to both guard conditions and avoids those two false blocks, while preserving the affected detections and hidden-dependency misses. Normalization is off by default and cannot prove correctness. Independent review and real-agent trials remain required.

## Deferred external gates

The user has deferred paid real-agent trials until implementation, commits/pushes, and automated checks are reported complete. Do not spend on the planned minimum 450 trials without a subsequent instruction. Independently reviewed labels, live PR rollout, branch protection, customer interviews, design partners, and a final release decision cannot be replaced with synthetic tests.

No subscriptions, hosted history, dashboard, LLM claim extraction, Codex integration, or automatic release publishing are included in this V1 scope.
