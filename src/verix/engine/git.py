"""Git access and content fingerprints without shell interpretation."""

import ast
import hashlib
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess

WINDOWS = os.name == "nt"


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
        self._startup_revision = None
        try:
            discovery = (
                self.git("rev-parse", "--show-toplevel", "--verify", "HEAD^{commit}")
                .decode()
                .splitlines()
            )
        except VerixError:
            discovery = []
        if len(discovery) == 2:
            root, self._startup_revision = discovery
        else:
            # Empty repositories and unusual path names retain ordinary Git discovery.
            root = self.git("rev-parse", "--show-toplevel").decode().strip()
        self.root = Path(root).resolve()

    def git(self, *args: str) -> bytes:
        try:
            return subprocess.run(
                ["git", "--literal-pathspecs", "-C", str(self.root), *args],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                check=True,
                timeout=10,
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
            or any(part.casefold() == ".git" for part in path.parts)
        ):
            raise VerixError("Path must name a file inside the repository")
        current = self.root
        for part in path.parts:
            current /= part
            try:
                info = current.lstat()
            except FileNotFoundError:
                continue
            # Windows directory junctions use the mount-point reparse tag.
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_reparse_tag", 0) == 0xA0000003:
                raise VerixError("Symlink evidence is not supported")
        return str(PurePosixPath(name))

    def fingerprint(
        self,
        path: str,
        revision: str | None = None,
        *,
        python_formatting: bool = False,
        index_modes: dict | None = None,
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
            if not stat.S_ISREG(before.st_mode):
                raise VerixError("Evidence must be a regular file")
            content = target.read_bytes()
            after = target.stat()
            if any(
                getattr(before, key) != getattr(after, key)
                for key in ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns", "st_mode")
            ):
                raise VerixError("File changed during capture; retry the read")
            if index_modes is not None:
                mode = index_modes.get(os.path.normcase(path), "100644")
            elif WINDOWS:
                entry = self.git("ls-files", "--stage", "-z", "--", path)
                mode = entry.split(b" ", 1)[0].decode() if entry else "100644"
            else:
                mode = "100755" if before.st_mode & stat.S_IXUSR else "100644"
            return fingerprint(content, mode, path, python_formatting)
        except FileNotFoundError:
            return {"sha256": None, "mode": None}

    def index_snapshot(self) -> tuple | None:
        # Linked worktrees and custom indexes retain the full Git-based recheck.
        if not (self.root / ".git").is_dir() or any(
            key in os.environ
            for key in ("GIT_INDEX_FILE", "GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR")
        ):
            return None
        try:
            with (self.root / ".git" / "index").open("rb") as source:
                before = os.fstat(source.fileno())
                content = source.read()
                after = os.fstat(source.fileno())
            fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
            if any(getattr(before, key) != getattr(after, key) for key in fields):
                raise VerixError("Git index changed while reading its snapshot; retry")
            return digest(content), *(getattr(after, key) for key in fields)
        except FileNotFoundError:
            return None

    def index_modes(self, paths: list[str] | None = None) -> dict:
        if paths == []:
            return {}
        args = ["ls-files", "--stage", "-z"]
        if paths is not None:
            args.extend(["--", *paths])
        modes = {}
        for entry in self.git(*args).split(b"\0"):
            if not entry:
                continue
            metadata, path = entry.split(b"\t", 1)
            mode, _, stage = metadata.split()
            if stage != b"0":
                raise VerixError("Resolve Git index conflicts before checking evidence")
            modes[os.path.normcase(os.fsdecode(path))] = mode.decode()
        if WINDOWS and paths is not None:
            missing = {os.path.normcase(path) for path in paths} - modes.keys()
            if missing:
                # Literal Git filters can miss case variants on a case-insensitive filesystem.
                modes.update(
                    {key: mode for key, mode in self.index_modes().items() if key in missing}
                )
        return modes

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
