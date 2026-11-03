"""Conservative Claude Code adapter: exact full-file reads only become complete evidence."""

import json
from pathlib import Path
import shlex
import sys
import tempfile

from verix.engine.git import VerixError, digest


def install(root, agent="claude-code"):
    codex = agent == "codex"
    directory = root / (".codex" if codex else ".claude")
    if directory.is_symlink() or directory.is_junction():
        raise VerixError("Agent configuration directory cannot be a symlink")
    directory.mkdir(exist_ok=True)
    config = directory / "config.toml"
    if codex and config.is_symlink():
        raise VerixError("Agent configuration cannot be a symlink")
    target = directory / ("hooks.json" if codex else "settings.local.json")
    if target.is_symlink():
        raise VerixError("Agent settings cannot be a symlink")
    data = json.loads(target.read_text()) if target.exists() else {}
    if not isinstance(data, dict) or not isinstance(data.get("hooks", {}), dict):
        raise VerixError("Agent settings and hooks must be JSON objects")
    hooks = data.setdefault("hooks", {})
    subcommand = "codex-hook" if codex else "hook"
    command = f"{shlex.quote(sys.executable)} -m verix {subcommand}"
    for event, matcher in (
        ("SessionStart", None),
        ("PreToolUse", None if codex else "Read|Edit|Write"),
        ("PostToolUse", None if codex else "Read|Edit|Write"),
        ("PreCompact", None),
    ):
        handler = {"type": "command", "command": command, "timeout": 5}
        entry = {"hooks": [handler]}
        if matcher:
            entry["matcher"] = matcher
        entries = hooks.setdefault(event, [])
        if not isinstance(entries, list):
            raise VerixError(f"Agent {event} hooks must be a list")
        if entry not in entries:
            entries.append(entry)
    with tempfile.NamedTemporaryFile(dir=directory, suffix=".json", delete=False) as output:
        temporary = Path(output.name)
    try:
        temporary.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    if codex and not config.exists():
        with config.open("x", encoding="utf-8") as output:
            output.write("[features]\nhooks = true\n")


def handle(engine, payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise VerixError("Hook input must be a JSON object")
    with engine.store.transaction():
        return _handle(engine, payload)


def _handle(engine, payload: dict) -> dict:
    event = payload.get("hook_event_name")
    session = payload.get("session_id")
    if not isinstance(session, str) or not session:
        raise VerixError("Hook requires session_id")
    if event not in ("SessionStart", "PreToolUse", "PostToolUse", "PreCompact"):
        raise VerixError("Unsupported hook event")
    engine.start("claude-code", session)
    if event in ("SessionStart", "PreCompact"):
        return {
            "session": session,
            "note": "Capture persists locally; session completeness requires explicit acknowledgement",
        }
    tool = payload.get("tool_name")
    inputs = payload.get("tool_input")
    event_id = payload.get("tool_use_id")
    if not isinstance(inputs, dict) or not isinstance(event_id, str):
        raise VerixError("Malformed hook tool input")
    path = engine.repo.path(inputs.get("file_path", ""))
    key = f"{session}:{event}:{event_id}"
    previous = engine.store.db.execute("SELECT data FROM events WHERE id=?", (key,)).fetchone()
    if previous:
        return json.loads(previous[0])
    result = {}
    if event == "PreToolUse" and tool == "Read":
        result = {
            "path": path,
            "fingerprint": engine.repo.fingerprint(path),
            "revision": engine.repo.revision(),
            "partial": "offset" in inputs or "limit" in inputs,
        }
    elif event == "PostToolUse" and tool == "Read":
        pre = engine.store.db.execute(
            "SELECT data FROM events WHERE id=?", (f"{session}:PreToolUse:{event_id}",)
        ).fetchone()
        response = payload.get("tool_response", {})
        file = response.get("file", {}) if isinstance(response, dict) else {}
        content = file.get("content") if isinstance(file, dict) else None
        before = json.loads(pre[0]) if pre else None
        current = engine.repo.fingerprint(path)
        complete = bool(
            before
            and not before["partial"]
            and isinstance(content, str)
            and before["fingerprint"] == current
            and before["revision"] == engine.repo.revision()
            and digest(content.encode()) == current["sha256"]
        )
        result = {
            "observation": engine.observe(
                session,
                path,
                complete=complete,
                expected=current,
                expected_revision=before["revision"] if complete else None,
            )
        }
    elif event == "PreToolUse" and tool in ("Edit", "Write"):
        result = engine.check(session, path, tool.lower())
        action_id = engine.claim(
            session,
            f"Proposed {tool} of {path}",
            [],
            [
                key
                for key, value in engine.store.nodes(session).items()
                if value["kind"] in ("claim", "decision")
            ],
            kind="action",
        )
        engine.store.db.execute(
            "INSERT INTO events VALUES(?,?,?)",
            (f"action:{session}:{event_id}", session, json.dumps({"node": action_id})),
        )
        if engine.policy["mode"] == "blocking" and result["verdict"] != "allow":
            result = {
                "hookSpecificOutput": {
                    "hookEventName": event,
                    "permissionDecision": "deny",
                    "permissionDecisionReason": f"Verix {result['verdict']}: {path}. Inspect verix report --session {session}; reverify current evidence.",
                }
            }
        else:
            result = {
                "hookSpecificOutput": {
                    "hookEventName": event,
                    "additionalContext": f"Verix {result['verdict']} for {path}; inspect the local report.",
                }
            }
    elif event == "PostToolUse" and tool in ("Edit", "Write"):
        row = engine.store.db.execute(
            "SELECT data FROM events WHERE id=?", (f"action:{session}:{event_id}",)
        ).fetchone()
        if row:
            node_id = json.loads(row[0])["node"]
            node = engine.store.nodes(session)[node_id]
            engine.store.update(
                node_id,
                {k: v for k, v in {**node, "executed": True}.items() if k not in ("id", "kind")},
            )
        result = {"executed": path, "tool": tool}
    else:
        raise VerixError("Unsupported hook tool")
    with engine.store.transaction():
        engine.store.db.execute(
            "INSERT INTO events VALUES(?,?,?)", (key, session, json.dumps(result))
        )
    return result
