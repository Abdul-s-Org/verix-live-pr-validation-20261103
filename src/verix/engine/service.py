"""Local evidence lifecycle and revision-bound action decisions."""

import json
import subprocess
from uuid import uuid4

from verix.engine import policy
from verix.engine.git import WINDOWS, Repository, VerixError, equivalent
from verix.engine.store import Store


def identifier() -> str:
    return uuid4().hex


class Engine:
    def __init__(self, root, policy_data=None):
        self.repo = Repository(root)
        self.policy = (
            policy.load(self.repo.root / ".verix.yml") if policy_data is None else policy_data
        )
        self.store = Store(self.repo.root)

    def fingerprint(self, path, revision=None, index_modes=None):
        return self.repo.fingerprint(
            path,
            revision,
            python_formatting=self.policy.get("ignore_python_formatting", False),
            index_modes=index_modes,
        )

    def start(self, agent: str, session: str | None = None) -> str:
        session = session or identifier()
        with self.store.transaction():
            if self.store.db.execute("SELECT 1 FROM sessions WHERE id=?", (session,)).fetchone():
                return session
            self.store.db.execute(
                "INSERT OR IGNORE INTO sessions(id,base,agent) VALUES(?,?,?)",
                (session, self.repo.revision(), agent),
            )
        return session

    def observe(
        self,
        session: str,
        path: str,
        complete: bool = True,
        *,
        expected=None,
        expected_revision=None,
    ) -> str:
        path = self.repo.path(path)
        if policy.excluded(self.policy, path):
            raise VerixError("Evidence path excluded by policy")
        base = self.repo.revision()
        fingerprint = self.fingerprint(path)
        if fingerprint["sha256"] is None:
            raise VerixError("Cannot capture missing file")
        if base != self.repo.revision() or (expected_revision and expected_revision != base):
            raise VerixError("Revision changed during capture; retry")
        if expected is not None and not equivalent(fingerprint, expected):
            raise VerixError("Read evidence changed before capture; retry")
        node = identifier()
        with self.store.transaction():
            self.store.add(
                session,
                "observation",
                node,
                {"path": path, "revision": base, "fingerprint": fingerprint, "complete": complete},
            )
        return node

    def claim(
        self,
        session: str,
        text: str,
        paths: list[str],
        parents: list[str],
        alternative: bool = False,
        kind: str = "claim",
    ) -> str:
        if kind not in ("claim", "decision", "action") or not text.strip():
            raise VerixError("A nonempty claim, decision, or action is required")
        nodes = self.store.nodes(session)
        sources = list(parents)
        for path in paths:
            path = self.repo.path(path)
            observations = [
                key
                for key, value in nodes.items()
                if value["kind"] == "observation" and value["path"] == path
            ]
            if not observations:
                raise VerixError(f"No captured read for {path}; run verix read first")
            # SQLite insertion order is the capture order; UUID ordering is not chronological.
            rows = self.store.db.execute(
                "SELECT id FROM nodes WHERE session=? ORDER BY rowid DESC", (session,)
            )
            sources.append(next(row[0] for row in rows if row[0] in observations))
        if any(parent not in nodes for parent in sources):
            raise VerixError("Parent evidence must belong to this session")
        node = identifier()
        groups = [[source] for source in sources] if alternative else ([sources] if sources else [])
        with self.store.transaction():
            self.store.add(
                session,
                kind,
                node,
                {
                    "text": text,
                    "groups": groups,
                    **({"executed": False} if kind == "action" else {}),
                },
            )
            for source in set(sources):
                self.store.db.execute("INSERT INTO edges VALUES(?,?)", (source, node))
        return node

    def analyze(self, session: str, head: str | None = None) -> dict:
        nodes = self.store.nodes(session)
        startup_revision = self.repo._startup_revision if head is None else None
        self.repo._startup_revision = None
        revision = startup_revision or self.repo.revision(head or "HEAD")
        states, reasons, fingerprints = {}, {}, {}
        observed_paths = sorted(
            {node["path"] for node in nodes.values() if node["kind"] == "observation"}
        )
        index_snapshot = self.repo.index_snapshot() if WINDOWS and not head else None
        index_modes = self.repo.index_modes(observed_paths) if WINDOWS and not head else None

        def visit(node, trail):
            if node in states:
                return states[node]
            if node in trail or node not in nodes:
                raise VerixError("Invalid evidence graph: cycle or missing node")
            value = nodes[node]
            if value["kind"] == "observation":
                current = self.fingerprint(value["path"], revision if head else None, index_modes)
                fingerprints[node] = current
                if not value["complete"]:
                    state = "unknown"
                else:
                    state = (
                        "valid"
                        if equivalent(
                            value["fingerprint"],
                            current,
                            self.policy.get("ignore_python_formatting", False),
                        )
                        else "suspect"
                    )
                reasons[node] = [
                    {
                        "path": value["path"],
                        "read_revision": value["revision"],
                        "current_revision": revision,
                        "recorded": value["fingerprint"],
                        "current": current,
                    }
                ]
            else:
                groups = value["groups"]
                group_states = []
                reason = []
                for group in groups:
                    members = [visit(parent, trail | {node}) for parent in group]
                    group_states.append(
                        "invalid"
                        if "invalid" in members
                        else "unknown"
                        if "unknown" in members
                        else "suspect"
                        if "suspect" in members
                        else "valid"
                    )
                    for parent in group:
                        reason.extend(reasons[parent])
                state = (
                    "valid"
                    if "valid" in group_states
                    else (
                        "unknown"
                        if not group_states or "unknown" in group_states
                        else "suspect"
                        if "suspect" in group_states
                        else "invalid"
                    )
                )
                verification = value.get("verification")
                if verification and verification["state"] == "invalid":
                    state = "invalid"
                elif (
                    verification
                    and verification["revision"] == revision
                    and verification.get("policy_hash") == policy.policy_hash(self.policy)
                ):
                    bound = verification["fingerprints"]
                    if bound == {key: fingerprints[key] for key in bound}:
                        state = verification["state"]
                reasons[node] = reason
            states[node] = state
            return state

        # Verification snapshots bind all observations, including unrelated ones.
        for node, value in nodes.items():
            if value["kind"] == "observation":
                visit(node, set())
        for node in nodes:
            visit(node, set())
        if revision != self.repo.revision(head or "HEAD"):
            if startup_revision is not None:
                return self.analyze(session, head)
            raise VerixError("Revision changed during analysis; retry")
        if index_modes is not None:
            changed = (
                index_snapshot != self.repo.index_snapshot()
                if index_snapshot is not None
                else index_modes != self.repo.index_modes(observed_paths)
            )
            if changed:
                raise VerixError("Git index changed during analysis; retry")
        return {
            "schema_version": 1,
            "session": session,
            "revision": revision,
            "states": states,
            "reasons": reasons,
            "fingerprints": fingerprints,
            "nodes": nodes,
            "coverage": "Observed and declared evidence only; hidden dependencies unknown",
        }

    def check(self, session: str, path: str, action: str = "edit", head: str | None = None) -> dict:
        if action not in ("edit", "write", "merge"):
            raise VerixError("Unsupported protected action")
        path = self.repo.path(path)
        report = self.analyze(session, head)
        states = [
            state
            for node, state in report["states"].items()
            if report["nodes"][node]["kind"] != "observation"
            and not report["nodes"][node].get("executed", False)
        ]
        level = policy.risk(self.policy, path)
        incomplete = bool(self.store.session(session)["incomplete"])
        inputs = {"states": states, "level": level, "incomplete": incomplete}
        verdict = policy.evaluate(**inputs)
        decision = {
            "schema_version": 1,
            "session": session,
            "path": path,
            "action": action,
            "inputs": inputs,
            "verdict": verdict,
            "mode": self.policy["mode"],
            "policy": self.policy,
            "policy_hash": policy.policy_hash(self.policy),
            "bound_revision": report["revision"],
            "fingerprints": report["fingerprints"],
            "reasons": report["reasons"],
            "required_checks": [
                f"verix verify {node} --session {session} --reaffirm"
                for node, state in report["states"].items()
                if state != "valid" and report["nodes"][node]["kind"] != "observation"
            ],
            "limits": "Session-wide checks; unseen dependencies and bypassed tools are not covered",
        }
        with self.store.transaction():
            decision["audit_id"] = self.store.audit(decision)
        return decision

    def verify(
        self, session: str, node: str, reaffirm: bool = False, check: str | None = None
    ) -> dict:
        report = self.analyze(session)
        value = report["nodes"].get(node)
        if not value or value["kind"] == "observation":
            raise VerixError("Verification requires a claim, decision, or action")
        if not reaffirm and not check:
            raise VerixError("Explicit --reaffirm or configured --check is required")
        # A mapped test supplies evidence, not an automatic semantic proof of every claim.
        if check and not reaffirm:
            raise VerixError("A mapped check also requires explicit --reaffirm of this claim")
        if check:
            command = self.policy["checks"].get(check)
            if command is None:
                raise VerixError("Unknown configured verification check")
            try:
                result = subprocess.run(
                    command,
                    cwd=self.repo.root,
                    timeout=60,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise VerixError("Verification failed to run or timed out") from exc
            state = "valid" if result.returncode == 0 else "invalid"
        else:
            state = "valid"
        after = self.analyze(session)
        if (
            after["revision"] != report["revision"]
            or after["fingerprints"] != report["fingerprints"]
        ):
            raise VerixError("Evidence changed during verification; retry")
        if report["states"][node] == "unknown":
            raise VerixError(
                "Cannot verify incomplete evidence; capture full reads and register a new claim"
            )
        value = {k: v for k, v in value.items() if k not in ("id", "kind")}
        value["verification"] = {
            "state": state,
            "policy_hash": policy.policy_hash(self.policy),
            "revision": report["revision"],
            "fingerprints": report["fingerprints"],
        }
        with self.store.transaction():
            self.store.update(node, value)
            self.store.audit({"kind": "verification", "node": node, **value["verification"]})
        return {"node": node, "state": state}

    def replay(self, audit: int) -> dict:
        row = self.store.db.execute("SELECT data FROM audit WHERE id=?", (audit,)).fetchone()
        if not row:
            raise VerixError("Unknown audit decision")
        data = json.loads(row[0])
        if "inputs" not in data:
            raise VerixError("Audit entry is not a policy decision")
        verdict = policy.evaluate(**data["inputs"])
        return {"verdict": verdict, "matches": verdict == data["verdict"], "decision": data}
