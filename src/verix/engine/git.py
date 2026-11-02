"""Git access and content fingerprints without shell interpretation."""

import ast
import hashlib
import os
from pathlib import Path, PurePosixPath
import subprocess


class VerixError(Exception):
    """An actionable input or operational error."""


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def equivalent(left: dict, right: dict, ignore_python_formatting: bool = False) -> bool:
    if left.get("mode") != right.get("mode"):
        return False
    if left.get("sha256") == right.get("sha256"):
        return True
    return bool(
        ignore_python_formatting
        and left.get("python_ast_sha256")
        and left.get("python_ast_sha256") == right.get("python_ast_sha256")
    )


def fingerprint(content: bytes, mode: str, path: str, python_formatting: bool) -> dict:
    result = {"sha256": digest(content), "mode": mode}
    if python_formatting and path.endswith(".py") and len(content) <= 1_000_000:
        try:
            tree = ast.parse(content, type_comments=True)
            result["python_ast_sha256"] = digest(ast.dump(tree, include_attributes=False).encode())
        except (SyntaxError, ValueError, RecursionError):
            pass  # Unparseable or oversized files retain exact-byte comparison.
    return result


class Repository:
    def __init__(self, path: str | Path):
        self.root = Path(path).resolve()
        self.root = Path(self.git("rev-parse", "--show-toplevel").decode().strip()).resolve()

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
        if path.anchor and not path.is_absolute():
            raise VerixError("Drive-relative and root-relative paths are not supported")
        if ".." in path.parts:
            raise VerixError("Path must stay inside the repository")
        if path.is_absolute():
            try:
                path = path.relative_to(self.root)
            except ValueError as exc:
                # macOS exposes /var through /private/var; preserve paths below that alias.
                for parent in reversed(path.parents):
                    try:
                        matches = parent.samefile(self.root)
                    except OSError:
                        matches = False
                    if matches:
                        path = path.relative_to(parent)
                        break
                else:
                    raise VerixError("Path is outside the repository") from exc
        name = path.as_posix()
        if (
            not name
            or name == "."
            or ".." in path.parts
            or any(os.path.normcase(part) == ".git" for part in path.parts)
        ):
            raise VerixError("Path must name a file inside the repository")
        current = self.root
        for part in path.parts:
            current /= part
            if current.is_symlink() or current.is_junction():
                raise VerixError("Symlink evidence is not supported")
        return str(PurePosixPath(name))

    def fingerprint(
        self, path: str, revision: str | None = None, *, python_formatting: bool = False
    ) -> dict:
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
            return fingerprint(
                self.git("cat-file", "blob", blob.decode()), mode.decode(), path, python_formatting
            )
        target = self.root / path
        try:
            before = target.stat()
            if not target.is_file():
                raise VerixError("Evidence must be a regular file")
            content = target.read_bytes()
            after = target.stat()
            if (before.st_mtime_ns, before.st_size) != (after.st_mtime_ns, after.st_size):
                raise VerixError("File changed during capture; retry the read")
            mode = "100755" if os.access(target, os.X_OK) else "100644"
            if os.name == "nt":
                entry = self.git("ls-files", "--stage", "-z", "--", path)
                mode = entry.split(b" ", 1)[0].decode() if entry else "100644"
            return fingerprint(content, mode, path, python_formatting)
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
