"""Transactional local storage. No file bodies are persisted."""

from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
from uuid import uuid4

from verix.engine.git import VerixError

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY, base TEXT NOT NULL, agent TEXT NOT NULL,
 incomplete INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS nodes(id TEXT PRIMARY KEY, session TEXT NOT NULL REFERENCES sessions(id),
 kind TEXT NOT NULL CHECK(kind IN ('observation','claim','decision','action')), data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS edges(parent TEXT REFERENCES nodes(id), child TEXT REFERENCES nodes(id),
 PRIMARY KEY(parent,child), CHECK(parent != child));
CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY, session TEXT REFERENCES sessions(id), data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY, data TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS nodes_session ON nodes(session);
PRAGMA user_version=1;
"""


class Store:
    def __init__(self, root: Path):
        folder = root / ".verix"
        if folder.is_symlink() or folder.is_junction():
            raise VerixError("Runtime directory cannot be a symlink")
        folder.mkdir(mode=0o700, exist_ok=True)
        target = folder / "state.sqlite3"
        if target.is_symlink():
            raise VerixError("Database cannot be a symlink")
        self.db = sqlite3.connect(target, timeout=5)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        current = self.db.execute("PRAGMA user_version").fetchone()[0]
        if current == 0:
            self.db.executescript("BEGIN IMMEDIATE;" + SCHEMA + "COMMIT;")
        elif current != 1:
            self.db.close()
            raise VerixError("Unsupported database schema; use a compatible Verix version")
        target.chmod(0o600)

    @contextmanager
    def transaction(self):
        nested = self.db.in_transaction
        savepoint = "verix_" + uuid4().hex
        try:
            self.db.execute(f"SAVEPOINT {savepoint}" if nested else "BEGIN IMMEDIATE")
            try:
                yield
            except BaseException:
                if nested:
                    self.db.execute(f"ROLLBACK TO {savepoint}")
                    self.db.execute(f"RELEASE {savepoint}")
                else:
                    self.db.rollback()
                raise
            else:
                if nested:
                    self.db.execute(f"RELEASE {savepoint}")
                else:
                    self.db.commit()
        except sqlite3.Error as exc:
            raise VerixError(f"Database operation failed: {exc}") from exc

    def session(self, session: str):
        row = self.db.execute("SELECT * FROM sessions WHERE id=?", (session,)).fetchone()
        if row is None:
            raise VerixError("Unknown session; run verix session start")
        return dict(row)

    def nodes(self, session: str) -> dict:
        self.session(session)
        return {
            row["id"]: {"id": row["id"], "kind": row["kind"], **json.loads(row["data"])}
            for row in self.db.execute(
                "SELECT * FROM nodes WHERE session=? ORDER BY id", (session,)
            )
        }

    def add(self, session: str, kind: str, node: str, data: dict):
        self.session(session)
        self.db.execute(
            "INSERT INTO nodes VALUES(?,?,?,?)", (node, session, kind, json.dumps(data))
        )

    def update(self, node: str, data: dict):
        self.db.execute("UPDATE nodes SET data=? WHERE id=?", (json.dumps(data), node))

    def audit(self, data: dict) -> int:
        return self.db.execute(
            "INSERT INTO audit(data) VALUES(?)", (json.dumps(data, sort_keys=True),)
        ).lastrowid
