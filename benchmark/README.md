# Deterministic fixture benchmark

Run `verix bench run > benchmark-results.json` to evaluate the 30 packaged scenarios. Each creates an isolated temporary Git repository, captures declared reads and claims, applies a seeded change, and evaluates no guard, file hashes, and Verix. The benchmark never executes fixture source code or commands from fixture JSON.

## Fixture protocol

`src/verix/scenarios.json` contains six renamed/removed-symbol cases, six behavior changes, five schema/configuration changes, four dependency-contract changes, five unrelated changes, two formatting-only changes, and two hidden dependencies. These are small illustrative repositories, not production incidents. Dependency cases include pinned-manifest and vendored API changes; they do not install dependency versions.

Each case contains:

- `id` and `family`: unique name and protocol category.
- `files`: initial repository-relative paths mapped to UTF-8 content.
- `changes`: paths mapped to new content; `null` means deletion. Renames use a deletion and an addition.
- `reads`: initial files captured before applying the changes.
- `claims`: ordered `{id, text, evidence, parents}` records. Parents must precede children; empty support deliberately represents unknown evidence.
- `expected_affected`: independently reviewable claim IDs that require rechecking; labels are never derived from Verix output.
- `action`: `{path, risk, valid}` for the proposed action. `valid` is a ground-truth label, independent of the verdict.

Validate a custom suite with `verix bench run --scenarios path/to/scenarios.json`. Suites must retain all 30 cases and the family counts. Validation runs before Git or filesystem mutation. Absolute/traversal/reserved paths, file/directory conflicts, duplicate IDs/JSON fields, missing evidence, cycles, invalid labels, and no-op changes are rejected.

Fixture commit identities and timestamps are fixed. Git signing and hooks are disabled inside fixtures; runtime databases are excluded from commits. Output contains reproducible before/after SHAs, expected and predicted claim IDs, evidence states, changed read paths, decisions, and per-scenario wall time including fixture setup. Output schema is now version 2; the earlier `before`/`after` fixture format is replaced by explicit file maps.

## Conditions and scoring

No guard flags nothing and allows every action. The hash baseline independently compares captured files against current fingerprints and flags claims directly citing changed files; it does not read Verix's states or propagate parent links. Both guard conditions apply the same risk rules. Verix uses its actual policy decision in explicit blocking mode. Keep `changed_reads` alongside claim metrics when comparing file-level approaches.

Recall is `TP / (TP + FN)` and precision is `TP / (TP + FP)`. Unknown affected claims count as misses, not successful detections. False-block rate is valid actions receiving `block` divided by all valid actions. `unresolved` decisions are counted separately. Unsafe-allow rate is invalid labeled actions receiving `allow` divided by all invalid labeled actions; this measures decisions, not observed agent execution. Undefined ratios are `null`.

Current high-risk fixtures expose false blocks on both formatting-only cases: 2 of 7 valid actions. This exceeds the PRD's under-10% false-block target. Do not weaken labels, lower risk solely to improve scores, or treat fixture results as release evidence. File-hash detection cannot establish semantic equivalence.

## Review and release gate

Labels remain **draft** until an independent reviewer checks every claim, evidence link, action-validity label, and seeded change. Review hidden-dependency and benign cases especially carefully. Compare the documented direct-evidence baseline with a realistic existing tool before claiming a transitive advantage.

Published evaluation additionally requires pinned model/prompt/tool versions, five real-agent runs per scenario/condition, reviewed raw logs, task completion, recovery, unsafe actions, and actual latency/token/cost overhead. None are measured by this fixture runner. Targets remain recall at least 80%, false blocks below 10%, and a meaningful transitive advantage. If hashing captures at least 75% of what Verix catches, revisit whether the graph is justified.
