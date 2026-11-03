"""Command-line entry points for the local guard and receipt-based CI."""

import argparse
import json
from pathlib import Path
import sqlite3
import sys

from verix.engine.git import VerixError
from verix.engine.service import Engine
from verix import receipts

EXIT = {"allow": 0, "verify": 10, "block": 20, "unresolved": 30}


def parser(hook_only=False):
    p = argparse.ArgumentParser(prog="verix", description="Detect stale coding-agent assumptions.")
    p.add_argument("--version", action="version", version="%(prog)s 0.1.0")
    p.add_argument("--repo", default=".")
    commands = p.add_subparsers(dest="command")
    commands.add_parser("hook")
    commands.add_parser("codex-hook")
    if hook_only:
        return p
    init = commands.add_parser("init")
    init.add_argument("--hooks", action="store_true")
    init.add_argument("--agent", choices=["claude-code", "codex"], default="claude-code")
    session = commands.add_parser("session").add_subparsers(dest="operation", required=True)
    start = session.add_parser("start")
    start.add_argument("--agent", default="manual")
    complete = session.add_parser("complete")
    complete.add_argument("--session", required=True)
    complete.add_argument("--ack-limitations", action="store_true", required=True)
    read = commands.add_parser("read")
    read.add_argument("path")
    read.add_argument("--session", required=True)
    claim = (
        commands.add_parser("claim")
        .add_subparsers(dest="operation", required=True)
        .add_parser("add")
    )
    claim.add_argument("text")
    claim.add_argument("--session", required=True)
    claim.add_argument("--evidence", action="append", default=[])
    claim.add_argument("--parent", action="append", default=[])
    claim.add_argument("--alternative", action="store_true")
    for name in ("report", "analyze", "check"):
        sub = commands.add_parser(name)
        sub.add_argument("--session", required=True)
        sub.add_argument("--head")
        sub.add_argument("--json", action="store_true")
        if name == "analyze":
            sub.add_argument("--base")
        if name == "check":
            sub.add_argument("--action", choices=["edit", "write", "merge"], default="edit")
            sub.add_argument("--path", required=True)
    verify = commands.add_parser("verify")
    verify.add_argument("node")
    verify.add_argument("--session", required=True)
    verify.add_argument("--reaffirm", action="store_true")
    verify.add_argument("--check")
    replay = commands.add_parser("replay")
    replay.add_argument("id", type=int)
    receipt = commands.add_parser("receipt").add_subparsers(dest="operation", required=True)
    export = receipt.add_parser("export")
    export.add_argument("--session", required=True)
    import_ = receipt.add_parser("import")
    import_.add_argument("file", type=Path)
    ci = commands.add_parser("ci")
    ci.add_argument("--receipt", required=True)
    ci.add_argument("--base", required=True)
    ci.add_argument("--head", required=True)
    bench = (
        commands.add_parser("bench")
        .add_subparsers(dest="operation", required=True)
        .add_parser("run")
    )
    bench.add_argument("--scenarios", type=Path)
    bench.add_argument("--ignore-python-formatting", action="store_true")
    return p


def run(args, engine):
    if args.command == "init":
        target = engine.repo.root / ".verix.yml"
        if not target.exists():
            with target.open("x") as output:
                output.write(
                    "version: 1\nmode: advisory\nrisk:\n  'auth/*': high\nexclude: ['.env*', '.verix/*']\nchecks: {}\n"
                )
        if args.hooks:
            from verix.hooks.claude import install

            install(engine.repo.root, args.agent)
        return {"initialized": str(engine.repo.root), "hooks": args.hooks}
    if args.command == "session":
        if args.operation == "start":
            return {"session": engine.start(args.agent)}
        engine.store.session(args.session)
        with engine.store.transaction():
            engine.store.db.execute("UPDATE sessions SET incomplete=0 WHERE id=?", (args.session,))
            engine.store.audit({"kind": "completeness_acknowledged", "session": args.session})
        return {
            "session": args.session,
            "limits": "Completeness is self-reported; hidden dependencies unknown",
        }
    if args.command == "read":
        return {"observation": engine.observe(args.session, args.path)}
    if args.command == "claim":
        return {
            "claim": engine.claim(
                args.session, args.text, args.evidence, args.parent, args.alternative
            )
        }
    if args.command in ("report", "analyze"):
        result = engine.analyze(args.session, args.head)
        if args.command == "analyze" and args.base:
            result["changes"] = engine.repo.changes(args.base, args.head or "HEAD")
        return result
    if args.command == "check":
        result = engine.check(args.session, args.path, args.action, args.head)
        print(json.dumps(result, indent=2))
        return EXIT[result["verdict"]]
    if args.command == "verify":
        return engine.verify(args.session, args.node, args.reaffirm, args.check)
    if args.command == "replay":
        return engine.replay(args.id)
    if args.command == "receipt":
        if args.operation == "export":
            return receipts.export(engine, args.session)
        return {"session": receipts.ingest(engine, receipts.read(args.file))}
    if args.command in ("hook", "codex-hook"):
        if args.command == "codex-hook":
            from verix.hooks.codex import handle
        else:
            from verix.hooks.claude import handle

        raw = sys.stdin.read(2_000_001)
        if len(raw) > 2_000_000:
            raise VerixError("Hook input exceeds 2 MB")
        payload = json.loads(raw)
        return handle(engine, payload)
    raise VerixError("Unsupported command")


def ci(args):
    from verix.engine.git import Repository

    repo = Repository(args.repo)
    base, head = repo.revision(args.base), repo.revision(args.head)
    # Only the base revision supplies policy. Never execute checks from a PR policy.
    from verix.engine import policy
    import tempfile

    raw = repo.git("ls-tree", base, "--", ".verix.yml")
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / "policy.yml"
        if raw:
            path.write_bytes(repo.git("show", f"{base}:.verix.yml"))
        engine = Engine(repo.root, policy_data=policy.load(path))
    try:
        receipt_path = engine.repo.path(args.receipt)
        raw = engine.repo.git("show", f"{head}:{receipt_path}")
        if len(raw) > receipts.MAX_BYTES:
            raise VerixError("Receipt exceeds 2 MB")
        data = receipts.validate(json.loads(raw))
        session = receipts.ingest(engine, data)
        if not engine.repo.git("merge-base", "--is-ancestor", data["session"]["base"], head) == b"":
            raise VerixError("Receipt base is not an ancestor of PR head")
        changed = engine.repo.changes(base, head)
        paths = [change["new_path"] or change["path"] for change in changed] or ["PR"]
        protected = max(
            paths, key=lambda p: {"low": 0, "medium": 1, "high": 2}[policy.risk(engine.policy, p)]
        )
        result = engine.check(session, protected, "merge", head)
        # Separate target-branch drift from the PR's own changes.
        result["base_analysis"] = engine.analyze(session, base)
        base_states = [
            state
            for key, state in result["base_analysis"]["states"].items()
            if result["base_analysis"]["nodes"][key]["kind"] != "observation"
        ]
        result["inputs"]["states"] += base_states
        result["verdict"] = policy.evaluate(**result["inputs"])
        with engine.store.transaction():
            result["audit_id"] = engine.store.audit(result)
        result["analyzed_base"] = base
        result["analyzed_head"] = head
        result.pop("policy", None)
        result.pop("base_analysis", None)
        result["limits"] = (
            "Self-reported receipt; not an attestation. Require an up-to-date branch before merge."
        )
    except (VerixError, ValueError) as exc:
        result = {
            "schema_version": 1,
            "verdict": "unresolved",
            "error": str(exc),
            "mode": engine.policy["mode"],
            "analyzed_base": base,
            "analyzed_head": head,
        }
    engine.store.db.close()
    print(json.dumps(result, indent=2))
    return 0 if engine.policy["mode"] == "advisory" else EXIT[result["verdict"]]


def main() -> None:
    argv = sys.argv[1:]
    hooks = ("hook", "codex-hook")
    hook_only = (len(argv) == 1 and argv[0] in hooks) or (
        len(argv) == 3 and argv[0] == "--repo" and argv[2] in hooks
    )
    p = parser(hook_only=hook_only)
    args = p.parse_args()
    if not args.command:
        p.print_help()
        return
    try:
        if args.command == "bench":
            from verix.benchmark import run as benchmark

            result = benchmark(args.scenarios, args.ignore_python_formatting)
        elif args.command == "ci":
            raise SystemExit(ci(args))
        else:
            engine = Engine(args.repo)
            try:
                result = run(args, engine)
            finally:
                engine.store.db.close()
        if isinstance(result, int):
            raise SystemExit(result)
        if args.command in ("report", "analyze") and not args.json:
            print(f"Session {result['session']} at {result['revision']}")
            for node, state in result["states"].items():
                value = result["nodes"][node]
                label = value.get("text", value.get("path", node))
                print(f"{state.upper():10} {node} {label}")
            print(result["coverage"])
        else:
            print(json.dumps(result, indent=2))
    except (VerixError, OSError, ValueError, TypeError, sqlite3.Error, RecursionError) as exc:
        if args.command in ("hook", "codex-hook"):
            # Failure is visible; malformed policy cannot silently disable protected-edit enforcement.
            print(f"Verix operational error: {exc}", file=sys.stderr)
            raise SystemExit(2) from exc
        print(f"Verix error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
