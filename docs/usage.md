# Configuration and operations

## Repository policy

`verix init` creates `.verix.yml` only when absent. Keep it in version control. Runtime state is ignored under `.verix/state.sqlite3`; never commit that database. Local Claude settings should also stay untracked.

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

The highest matching risk wins; unmatched paths are medium. Path patterns use Python fnmatch semantics, including `*` matching `/`. Blocking is explicit opt-in. Review configured commands as code before running verification: they execute without a shell but with your local privileges. Timeouts are 60 seconds and output is discarded to avoid persisting secrets.

Current checks conservatively consider all claims/decisions/actions in a session, rather than infer which claims a target file depends on. Use separate sessions for unrelated work. Alternative evidence sources require `claim add --alternative`; without it all listed sources are required. Use repeated `--parent` arguments for transitive relationships. No automatic semantic inference is performed.

A claim without evidence is unknown. `session complete --ack-limitations` acknowledges the operator's capture assessment; it does not prove hidden dependencies are covered. Low-risk unknown evidence may be allowed by policy with an explicit incomplete input in the decision; medium/high risk remains unresolved.

## Optional Python formatting normalization

`ignore_python_formatting: true` retains exact content hashes and additionally records a Python AST digest when capturing a `.py` file. If bytes change but the parsed structure and Git mode match, the observation remains supported under that policy. It ignores whitespace and ordinary comments, but preserves docstrings and type comments. Invalid syntax, files above 1 MB, and other languages fall back to exact hashes. Enabling the option requires fresh reads; old receipts without AST digests remain conservative. The option is off by default because source-sensitive tooling can depend on formatting. This does not prove semantic correctness.

Successful verifications are bound to the complete policy hash as well as evidence/revisions. Editing the policy expires those approvals.

## Receipts and PR checks

Receipts contain paths, hashes, revisions, graph links, and placeholder claim text. Paths and repository metadata may still be sensitive: inspect the export and use exclusions. Receipt schema validation rejects unknown fields and cyclic/missing references. No cryptographic authenticity is claimed. Use a fresh checkout for each import/CI run; imports never overwrite existing sessions or nodes.

After Verix's reusable workflow is available on GitHub, a consumer repository can add:

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

Pin both references to a reviewed Verix commit for production. The workflow installs trusted Verix code separately from PR data, evaluates the policy from the PR base revision, analyzes exact base/head commits, and uploads a JSON artifact. It never runs PR verification commands. Missing receipts produce unresolved results. Same-repository PRs receive one updated comment; forks receive an artifact and job summary without requiring write access.

Configure branch protection to require the check and require an up-to-date branch. Configure merge-queue support separately before relying on a merge queue; this implementation handles pull_request runs only. A result does not authorize a later base/head revision.

## Troubleshooting and recovery

- Missing Git/commits: install Git, initialize the repository, and create a first commit.
- Missing revisions: fetch the required history; shallow clones cannot analyze unavailable objects.
- Unknown evidence: capture a full file read, register a new evidence-backed claim, and inspect session completeness.
- Malformed policy: fix the reported field or YAML line; configuration errors do not become successful checks.
- Locked SQLite: finish other writers and retry. Do not delete the database while a process is using it.
- Corrupt/unsupported database: preserve a backup and investigate. There is no destructive automatic reset or downgrade.
- Repeated receipt import: use a fresh analysis checkout; receipt IDs intentionally cannot overwrite prior evidence.
- Hook failure: inspect stderr. The adapter exits 2 on operational failures, so a protected edit can be held even in advisory mode; policy findings remain advisory unless blocking was configured.

Keep a private backup of `.verix/` if audit history matters. SQLite schema version 1 is supported; future schema migrations must be added before changing it. Do not manually edit audit records. `verix replay AUDIT_ID` reruns the saved policy inputs, not Git commands or tests.

## Integration contracts

The Claude adapter follows the official [hook reference](https://code.claude.com/docs/en/hooks), using command hooks and `PreToolUse` deny output. It deliberately treats unrecognized Read responses as incomplete. Validate against a real Claude Code session before rollout.

Workflow isolation follows GitHub's [secure-use guidance](https://docs.github.com/en/actions/reference/security/secure-use). The job status supplies the PR check; no separate GitHub App or Check Runs API is needed for this release.
