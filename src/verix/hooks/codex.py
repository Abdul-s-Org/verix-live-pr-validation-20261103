"""Narrow Codex adapter: exact cat reads and native apply_patch proposals."""

from pathlib import Path
import shlex
import re

from verix.engine.git import VerixError
from verix.hooks.claude import handle as capture


def _unsupported(engine, session, event, message):
    engine.store.db.execute("UPDATE sessions SET incomplete=1 WHERE id=?", (session,))
    output = {"hookEventName": event, "additionalContext": message}
    if event == "PreToolUse" and engine.policy["mode"] == "blocking":
        output = {
            "hookEventName": event,
            "permissionDecision": "deny",
            "permissionDecisionReason": message,
        }
    return {"hookSpecificOutput": output}


def handle(engine, payload):
    if not isinstance(payload, dict):
        raise VerixError("Hook input must be a JSON object")
    session, event = payload.get("session_id"), payload.get("hook_event_name")
    if not isinstance(session, str) or not session:
        raise VerixError("Hook requires session_id")
    if event not in ("SessionStart", "PreCompact", "PreToolUse", "PostToolUse"):
        raise VerixError("Unsupported hook event")
    cwd = payload.get("cwd")
    if not isinstance(cwd, str) or Path(cwd).resolve() != engine.repo.root:
        raise VerixError("Codex hook cwd must be the repository root")
    with engine.store.transaction():
        engine.start("codex", session)
        if event in ("SessionStart", "PreCompact"):
            return {
                "hookSpecificOutput": {
                    "hookEventName": event,
                    "additionalContext": "Verix captures exact cat reads and apply_patch only. Register claims and explicitly "
                    "acknowledge completeness; other tools leave capture incomplete.",
                }
            }
        inputs, tool = payload.get("tool_input"), payload.get("tool_name")
        if not isinstance(inputs, dict) or not isinstance(payload.get("tool_use_id"), str):
            raise VerixError("Malformed hook tool input")
        command = inputs.get("command")
        if not isinstance(command, str):
            return _unsupported(engine, session, event, "Verix: unsupported tool input")
        if tool == "Bash":
            # shortcut: only literal full-file cat is captured; add native readers after live tests.
            if not any(c in command for c in "\n\r$`;|&<>*?[]{}~\\#()"):
                words = shlex.split(command)
                paths = words[2:] if words[:2] == ["cat", "--"] else words[1:]
                if words[:1] == ["cat"] and len(paths) == 1 and not paths[0].startswith("-"):
                    translated = {
                        **payload,
                        "tool_name": "Read",
                        "tool_input": {"file_path": paths[0]},
                    }
                    if event == "PreToolUse":
                        engine.store.db.execute(
                            "UPDATE sessions SET incomplete=1 WHERE id=?", (session,)
                        )
                    else:
                        translated["tool_response"] = {
                            "file": {"content": payload.get("tool_response")}
                        }
                    capture(engine, translated)
                    return {}
        elif tool == "apply_patch":
            lines = command.splitlines()
            if not lines or lines[0] != "*** Begin Patch" or lines[-1] != "*** End Patch":
                raise VerixError("Malformed Codex patch")
            paths = [
                line.split(": ", 1)[1]
                for line in lines
                if line.startswith(
                    ("*** Update File: ", "*** Add File: ", "*** Delete File: ", "*** Move to: ")
                )
            ]
            if not paths or any(not path or path != path.strip() for path in paths):
                raise VerixError("Codex patch requires unambiguous target paths")
            paths = list(dict.fromkeys(engine.repo.path(path) for path in paths))
            if event == "PostToolUse":
                response = payload.get("tool_response")
                if not isinstance(response, str) or not re.fullmatch(
                    r"Exit code: 0\nWall time: [0-9]+(?:\.[0-9]+)? seconds\n"
                    r"Output:\nSuccess\. Updated the following files:\n.+",
                    response,
                    re.DOTALL,
                ):
                    return _unsupported(engine, session, event, "Verix: patch success unconfirmed")
            results = [
                capture(
                    engine,
                    {
                        **payload,
                        "tool_name": "Edit",
                        "tool_input": {"file_path": path},
                        "tool_use_id": f"{payload['tool_use_id']}:{index}",
                    },
                )
                for index, path in enumerate(paths)
            ]
            for result in results:
                if result.get("hookSpecificOutput", {}).get("permissionDecision") == "deny":
                    return result
            return results[0] if event == "PreToolUse" else {}
        return _unsupported(
            engine,
            session,
            event,
            "Verix: unsupported command; capture is incomplete. Use literal cat or native apply_patch.",
        )
