"""Strict metadata-only receipt interchange. Receipts are self-reported, not trusted attestations."""

import json
from pathlib import Path

from verix.engine.git import VerixError

MAX_BYTES = 2_000_000


def validate(data: dict) -> dict:
    if not isinstance(data, dict) or set(data) != {"schema_version", "session", "nodes"}:
        raise VerixError("Invalid receipt fields")
    session = data["session"]
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise VerixError("Unsupported receipt schema")
    if not isinstance(session, dict) or set(session) != {"id", "base", "agent", "incomplete"}:
        raise VerixError("Invalid receipt session")
    if any(not isinstance(session[k], str) or not session[k] for k in ("id", "base", "agent")):
        raise VerixError("Invalid session identifiers")
    if type(session["incomplete"]) is not int or session["incomplete"] not in (0, 1):
        raise VerixError("Invalid capture completeness")
    nodes = data["nodes"]
    if not isinstance(nodes, dict) or len(nodes) > 10000:
        raise VerixError("Invalid or oversized evidence graph")
    parents = {}
    for key, node in nodes.items():
        if not isinstance(key, str) or not isinstance(node, dict) or node.get("id") != key:
            raise VerixError("Invalid node identifier")
        kind = node.get("kind")
        if kind == "observation":
            required = {"id", "kind", "path", "revision", "fingerprint", "complete"}
            if set(node) != required or type(node["complete"]) is not bool:
                raise VerixError("Invalid observation")
            if any(not isinstance(node[k], str) or not node[k] for k in ("path", "revision")):
                raise VerixError("Invalid observation path or revision")
            fp = node["fingerprint"]
            if (
                not isinstance(fp, dict)
                or not {"sha256", "mode"} <= set(fp)
                or set(fp) - {"sha256", "mode", "python_ast_sha256"}
            ):
                raise VerixError("Invalid fingerprint")
            if "python_ast_sha256" in fp:
                value = fp["python_ast_sha256"]
                if (
                    not isinstance(value, str)
                    or len(value) != 64
                    or any(c not in "0123456789abcdef" for c in value)
                ):
                    raise VerixError("Invalid Python AST hash")
            h = fp["sha256"]
            if (
                not isinstance(h, str)
                or len(h) != 64
                or any(c not in "0123456789abcdef" for c in h)
            ):
                raise VerixError("Invalid content hash")
            if fp["mode"] not in ("100644", "100755"):
                raise VerixError("Invalid file mode")
            parents[key] = []
        elif kind in ("claim", "decision", "action"):
            fields = {"id", "kind", "text", "groups"} | (
                {"executed"} if kind == "action" else set()
            )
            if kind == "action" and type(node.get("executed")) is not bool:
                raise VerixError("Invalid action execution state")
            if set(node) != fields or not isinstance(node["text"], str):
                raise VerixError("Invalid claim fields")
            groups = node["groups"]
            if not isinstance(groups, list) or any(
                not isinstance(g, list) or not g for g in groups
            ):
                raise VerixError("Invalid evidence groups")
            sources = [p for group in groups for p in group]
            if any(not isinstance(p, str) or p not in nodes for p in sources):
                raise VerixError("Unknown evidence reference")
            parents[key] = sources
        else:
            raise VerixError("Unknown node kind")
    # Kahn's algorithm rejects cycles without recursion on untrusted input.
    done = set()
    while len(done) < len(nodes):
        ready = {
            key for key, sources in parents.items() if key not in done and set(sources) <= done
        }
        if not ready:
            raise VerixError("Receipt contains a cycle")
        done |= ready
    return data


def read(path: Path) -> dict:
    if path.is_symlink() or path.stat().st_size > MAX_BYTES:
        raise VerixError("Receipt is a symlink or exceeds 2 MB")
    try:
        return validate(json.loads(path.read_text()))
    except (ValueError, RecursionError) as exc:
        raise VerixError("Invalid receipt JSON") from exc


def export(engine, session: str) -> dict:
    nodes = engine.store.nodes(session)
    for node in nodes.values():
        node.pop("verification", None)
        if node["kind"] == "observation" and engine.policy["exclude"]:
            from verix.engine.policy import excluded

            if excluded(engine.policy, node["path"]):
                raise VerixError("Receipt includes excluded evidence; start a clean session")
    # Claim text is intentionally omitted to avoid exporting secrets from free-form text.
    for key, node in nodes.items():
        if node["kind"] != "observation":
            node["text"] = f"Claim {key} (text kept locally)"
    return validate({"schema_version": 1, "session": engine.store.session(session), "nodes": nodes})


def ingest(engine, data: dict) -> str:
    data = validate(data)
    session = data["session"]
    engine.repo.revision(session["base"])
    for node in data["nodes"].values():
        if node["kind"] == "observation":
            engine.repo.path(node["path"])
            engine.repo.revision(node["revision"])
    with engine.store.transaction():
        if engine.store.db.execute(
            "SELECT 1 FROM sessions WHERE id=?", (session["id"],)
        ).fetchone():
            raise VerixError("Receipt session already exists; use a fresh analysis directory")
        engine.store.db.execute(
            "INSERT INTO sessions VALUES(?,?,?,?)",
            tuple(session[k] for k in ("id", "base", "agent", "incomplete")),
        )
        for key, node in data["nodes"].items():
            engine.store.add(
                session["id"],
                node["kind"],
                key,
                {k: v for k, v in node.items() if k not in ("id", "kind")},
            )
        for key, node in data["nodes"].items():
            for parent in set(p for group in node.get("groups", []) for p in group):
                engine.store.db.execute("INSERT INTO edges VALUES(?,?)", (parent, key))
    return session["id"]
