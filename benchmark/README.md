# Deterministic fixture benchmark

Run `verix bench run` to execute the 30 packaged draft scenarios. Each creates an isolated temporary Git repository, captures evidence, applies a seeded change, and compares no guard, direct file-hash claim flagging, and transitive Verix flagging. JSON output includes per-condition counts, recall, precision, false-block rate, and per-scenario elapsed time.

Cases: six file renames, six behavior changes, five configuration changes, four API/dependency-contract changes, five unrelated changes, two formatting-only changes, and two hidden dependencies. The dependency cases simulate changed contracts; they do not install real dependency versions. Scenarios currently use a simple two-claim chain. False-block measurements use medium-risk checks; they must not be interpreted as general blocking-mode performance.

## Required independent review

Packaged definitions in `src/verix/scenarios.json` are draft fixtures, not independently reviewed ground truth. Before release, reviewers must replace redundant synthetic examples with representative repository tasks, label the affected claims independently, and review benign cases. The file-hash baseline currently flags direct evidence only; compare against a realistic baseline before using it for a product decision.

The fixture runner does not run coding agents. The published evaluation must additionally pin model versions, prompts, tool/hook versions, and seed commits; pause the agent, apply each change, resume it, and perform at least five runs per scenario/condition. Publish raw logs with sensitive data removed and measure unsafe actions, completion, recovery, latency, tokens, and cost. Record unknown/unresolved results separately from correct detections.

Targets from the PRD: deterministic recall at least 80%, false blocks below 10%, and a meaningful transitive advantage. If simple hashing captures at least 75% of what Verix catches, revisit whether the graph is justified. These are release gates, not current real-world claims.
