"""Git access and content fingerprints without shell interpretation."""

import hashlib
import os
from pathlib import Path, PurePosixPath
import subprocess


class VerixError(Exception):
    """An actionable input or operational error."""


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


class Repository:
    def __init__(self, path: str | Path):
        self.root = Path(path).resolve()
        self.root = Path(self.git("rev-parse", "--show-toplevel").decode().strip())

    def git(self, *args: str) -> bytes:
        try:
            return subprocess.run(
                ["git", "-C", str(self.root), *args], capture_output=True, check=True, timeout=10
            ).stdout
        except (OSError, subprocess.SubprocessError) as exc:
            raise VerixError(
                f"Git operation failed: {args[0]}; check repository and revisions"
            ) from exc

    def revision(self, ref: str = "HEAD") -> str:
        if ref.startswith("-"):
            raise VerixError("Invalid revision")
        return self.git("rev-parse", "--verify", f"{ref}^{{commit}}").decode().strip()

    def path(self, value: str) -> str:
        path = Path(value)
        if path.is_absolute():
            try:
                path = path.relative_to(self.root)
            except ValueError as exc:
                raise VerixError("Path is outside the repository") from exc
        name = path.as_posix()
        if not name or name == "." or ".." in path.parts or ".git" in path.parts:
            raise VerixError("Path must name a file inside the repository")
        current = self.root
        for part in path.parts:
            current /= part
            if current.is_symlink():
                raise VerixError("Symlink evidence is not supported")
        return str(PurePosixPath(name))

    def fingerprint(self, path: str, revision: str | None = None) -> dict:
        path = self.path(path)
        if revision is not None:
            sha = self.revision(revision)
            entry = self.git("ls-tree", "-z", sha, "--", path)
            if not entry:
                return {"sha256": None, "mode": None}
            metadata, _ = entry.split(b"\t", 1)
            mode, kind, blob = metadata.split()
            if kind != b"blob" or mode == b"120000":
                raise VerixError("Only regular files can be evidence")
            return {
                "sha256": digest(self.git("cat-file", "blob", blob.decode())),
                "mode": mode.decode(),
            }
        target = self.root / path
        try:
            before = target.stat()
            if not target.is_file():
                raise VerixError("Evidence must be a regular file")
            content = target.read_bytes()
            after = target.stat()
            if (before.st_mtime_ns, before.st_size) != (after.st_mtime_ns, after.st_size):
                raise VerixError("File changed during capture; retry the read")
            return {
                "sha256": digest(content),
                "mode": "100755" if os.access(target, os.X_OK) else "100644",
            }
        except FileNotFoundError:
            return {"sha256": None, "mode": None}

    def changes(self, base: str, head: str) -> list[dict]:
        base, head = self.revision(base), self.revision(head)
        parts = self.git("diff", "--name-status", "-z", "-M", base, head, "--").split(b"\0")
        result = []
        index = 0
        while index < len(parts) and parts[index]:
            status = parts[index].decode()
            old = os.fsdecode(parts[index + 1])
            index += 2
            new = None
            if status.startswith(("R", "C")):
                new = os.fsdecode(parts[index])
                index += 1
            result.append({"status": status, "path": old, "new_path": new})
        return result
