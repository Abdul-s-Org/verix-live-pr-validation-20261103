# Security

Verix is a development candidate. Hooks and self-reported receipts are not a security boundary or proof of code correctness. Capture can be bypassed, and unseen dependencies remain unknown.

## Implemented boundaries

- Repository-relative paths reject traversal, protected Git metadata, symlinks, and Windows junctions. Root aliases such as macOS `/var` are accepted without following links below the repository boundary.
- SQLite records metadata, hashes, claims, and audit inputs; source bodies are not persisted. Runtime files belong under ignored `.verix/`. Local protection depends on operating-system file permissions/ACLs.
- Receipt exports omit claim text and approval assertions; excluded evidence prevents export. Paths/hashes remain potentially sensitive. Receipts are schema-validated but are not signed attestations.
- Verification commands come only from explicitly configured local policy and require explicit invocation. They run without a shell and with a timeout, using the developer's privileges. Never put secrets in command arguments or policy files.
- PR analysis loads policy from the base revision and never executes PR-provided verification commands. Analysis uses read-only GitHub permissions; optional commenting runs separately, skips forks, and ignores stale revisions.

Automated regressions cover malformed receipts, untrusted PR policies, duplicate/concurrent hooks, capture races, rollback, and comment content filtering. They do not replace an independent security review before a private-repository pilot.

## Reporting

Do not put credentials, private source code, or sensitive session data in public issues or fixtures. Use GitHub private vulnerability reporting if enabled, or contact a repository maintainer privately before public disclosure.
