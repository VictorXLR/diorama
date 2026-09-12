"""A confined, read/write/search/exec view over one repository.

Every path the agent touches goes through :meth:`Workspace.resolve`, which
rejects anything that escapes the configured root (``..``, absolute paths,
symlinks that point outside).  This is the single security boundary for the
code-facing tools.
"""

from __future__ import annotations

import asyncio
import difflib
import fnmatch
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

DEFAULT_MAX_READ_BYTES = 400_000
DEFAULT_MAX_OUTPUT_BYTES = 40_000
DEFAULT_EXEC_TIMEOUT = 120.0
DEFAULT_SEARCH_RESULTS = 100

# Directories that are never worth walking.  Kept intentionally small: real
# ignore rules come from ``.gitignore`` files, this is just the safety net.
ALWAYS_IGNORED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
    ".nox",
    "dist",
    "build",
    "coverage",
    "htmlcov",
    ".next",
    ".nuxt",
    ".turbo",
    ".stryker-tmp",
    ".diorama",
    ".idea",
    ".vscode",
}
ALWAYS_IGNORED_SUFFIXES = (".egg-info", ".pyc", ".pyo", ".so", ".dylib", ".dll")


class WorkspaceError(RuntimeError):
    """Raised when a filesystem operation is unsafe or impossible."""


@dataclass
class _IgnoreRule:
    pattern: str
    negated: bool
    directory_only: bool


class _IgnoreMatcher:
    """Minimal ``.gitignore`` matcher (gitignore semantics, best effort)."""

    def __init__(self, rules: Sequence[_IgnoreRule]) -> None:
        self.rules = list(rules)

    def add_file(self, gitignore: Path) -> None:
        try:
            text = gitignore.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            negated = line.startswith("!")
            if negated:
                line = line[1:]
            directory_only = line.endswith("/")
            line = line.rstrip("/")
            if line:
                self.rules.append(_IgnoreRule(pattern=line, negated=negated, directory_only=directory_only))

    def ignores(self, rel_path: str, *, is_dir: bool) -> bool:
        rel_path = rel_path.replace(os.sep, "/")
        name = rel_path.rsplit("/", 1)[-1]
        ignored = False
        for rule in self.rules:
            if rule.directory_only and not is_dir:
                # A dir-only rule still hides files *under* that dir; handled by the walk.
                pass
            if self._matches(rule, rel_path, name):
                ignored = not rule.negated
        return ignored

    @staticmethod
    def _matches(rule: _IgnoreRule, rel_path: str, name: str) -> bool:
        pattern = rule.pattern
        if "/" in pattern:
            # Anchored to the repo root unless it starts with ``**``.
            if pattern.startswith("**/"):
                return fnmatch.fnmatch(rel_path, pattern) or fnmatch.fnmatch(rel_path, pattern[3:])
            return fnmatch.fnmatch(rel_path, pattern) or fnmatch.fnmatch(rel_path, f"**/{pattern}")
        return fnmatch.fnmatch(name, pattern)


@dataclass
class Workspace:
    """Confined operations over ``root``."""

    root: Path
    max_read_bytes: int = DEFAULT_MAX_READ_BYTES
    max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES
    exec_timeout: float = DEFAULT_EXEC_TIMEOUT
    allow_exec: bool = True
    _ignores: Optional[_IgnoreMatcher] = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self.root = Path(self.root).expanduser().resolve()
        if not self.root.is_dir():
            raise WorkspaceError(f"Workspace root does not exist or is not a directory: {self.root}")

    # ------------------------------------------------------------------ paths

    def relative(self, path: Path) -> str:
        try:
            return path.relative_to(self.root).as_posix()
        except ValueError:
            return path.as_posix()

    def resolve(self, relative: str, *, must_exist: bool = False) -> Path:
        """Resolve ``relative`` inside the root, refusing escapes."""
        if relative is None:
            relative = "."
        raw = str(relative).strip()
        candidate = Path(raw)
        if candidate.is_absolute():
            raise WorkspaceError(f"Absolute paths are not allowed: {raw!r}")
        resolved = (self.root / candidate).resolve()
        if resolved != self.root and self.root not in resolved.parents:
            raise WorkspaceError(f"Path escapes the workspace root: {raw!r}")
        if must_exist and not resolved.exists():
            raise WorkspaceError(f"No such path in the workspace: {raw!r}")
        return resolved

    # --------------------------------------------------------------- ignores

    def _matcher(self) -> _IgnoreMatcher:
        if self._ignores is None:
            matcher = _IgnoreMatcher([])
            for gitignore in self._iter_gitignores():
                matcher.add_file(gitignore)
            self._ignores = matcher
        return self._ignores

    def _iter_gitignores(self) -> Iterable[Path]:
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [d for d in dirnames if d not in ALWAYS_IGNORED_DIRS]
            if ".gitignore" in filenames:
                yield Path(dirpath) / ".gitignore"

    def is_ignored(self, path: Path, *, is_dir: bool) -> bool:
        rel = self.relative(path)
        if rel in {"", "."}:
            return False
        parts = rel.split("/")
        for part in parts[:-1]:
            if part in ALWAYS_IGNORED_DIRS or part.endswith(ALWAYS_IGNORED_SUFFIXES):
                return True
        name = parts[-1]
        if is_dir and (name in ALWAYS_IGNORED_DIRS or name.endswith(ALWAYS_IGNORED_SUFFIXES)):
            return True
        if not is_dir and name.endswith(ALWAYS_IGNORED_SUFFIXES):
            return True
        return self._matcher().ignores(rel, is_dir=is_dir)

    # ------------------------------------------------------------- reading

    def list_dir(self, relative: str = ".", *, recursive: bool = False, max_entries: int = 2000) -> Dict[str, Any]:
        base = self.resolve(relative, must_exist=True)
        if base.is_file():
            return {"path": self.relative(base), "entries": [{"name": base.name, "type": "file", "size": base.stat().st_size}]}
        entries: List[Dict[str, Any]] = []

        def record(path: Path) -> None:
            is_dir = path.is_dir()
            entry: Dict[str, Any] = {"name": path.name, "path": self.relative(path), "type": "dir" if is_dir else "file"}
            if not is_dir:
                try:
                    entry["size"] = path.stat().st_size
                except OSError:
                    pass
            entries.append(entry)

        if recursive:
            for dirpath, dirnames, filenames in os.walk(base):
                dirnames[:] = sorted(
                    d for d in dirnames if not self.is_ignored(Path(dirpath) / d, is_dir=True)
                )
                for name in sorted(filenames):
                    file_path = Path(dirpath) / name
                    if self.is_ignored(file_path, is_dir=False):
                        continue
                    record(file_path)
                    if len(entries) >= max_entries:
                        break
                if len(entries) >= max_entries:
                    break
        else:
            for child in sorted(base.iterdir(), key=lambda p: (p.is_file(), p.name)):
                if self.is_ignored(child, is_dir=child.is_dir()):
                    continue
                record(child)
        truncated = len(entries) > max_entries
        return {"path": self.relative(base), "entries": entries[:max_entries], "truncated": truncated}

    def read_file(self, relative: str, *, start_line: Optional[int] = None, end_line: Optional[int] = None) -> Dict[str, Any]:
        path = self.resolve(relative, must_exist=True)
        if path.is_dir():
            raise WorkspaceError(f"{relative!r} is a directory; use list_dir.")
        size = path.stat().st_size
        if size > self.max_read_bytes:
            raise WorkspaceError(
                f"{relative!r} is {size} bytes, larger than the {self.max_read_bytes}-byte read limit."
            )
        raw = path.read_bytes()
        if b"\x00" in raw[:4096]:
            raise WorkspaceError(f"{relative!r} looks like a binary file.")
        text = raw.decode("utf-8", errors="replace")
        lines = text.splitlines()
        total = len(lines)
        start = max(1, start_line or 1)
        end = min(total, end_line or total)
        selected = lines[start - 1 : end]
        numbered = "\n".join(f"{start + i}\t{line}" for i, line in enumerate(selected))
        return {
            "path": self.relative(path),
            "startLine": start,
            "endLine": end,
            "totalLines": total,
            "content": numbered,
        }

    # ------------------------------------------------------------ searching

    def search(
        self,
        pattern: str,
        *,
        glob: Optional[str] = None,
        case_sensitive: bool = True,
        max_results: int = DEFAULT_SEARCH_RESULTS,
        context_lines: int = 0,
    ) -> Dict[str, Any]:
        try:
            regex = re.compile(pattern, 0 if case_sensitive else re.IGNORECASE)
        except re.error as exc:
            raise WorkspaceError(f"Invalid search pattern: {exc}") from exc

        matches: List[Dict[str, Any]] = []
        files_scanned = 0
        truncated = False
        for path in self._walk_files():
            rel = self.relative(path)
            if glob and not (fnmatch.fnmatch(path.name, glob) or fnmatch.fnmatch(rel, glob)):
                continue
            files_scanned += 1
            try:
                if path.stat().st_size > self.max_read_bytes:
                    continue
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if "\x00" in text[:4096]:
                continue
            lines = text.splitlines()
            for index, line in enumerate(lines):
                if regex.search(line):
                    entry: Dict[str, Any] = {"path": rel, "line": index + 1, "text": line[:300]}
                    if context_lines:
                        lo = max(0, index - context_lines)
                        hi = min(len(lines), index + context_lines + 1)
                        entry["context"] = lines[lo:hi]
                    matches.append(entry)
                    if len(matches) >= max_results:
                        truncated = True
                        break
            if truncated:
                break
        return {
            "pattern": pattern,
            "glob": glob,
            "filesScanned": files_scanned,
            "matchCount": len(matches),
            "truncated": truncated,
            "matches": matches,
        }

    def iter_files(self) -> Iterable[Path]:
        """Yield every non-ignored file under the root, in sorted order."""
        return self._walk_files()

    def _walk_files(self) -> Iterable[Path]:
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = sorted(
                d for d in dirnames if not self.is_ignored(Path(dirpath) / d, is_dir=True)
            )
            for name in sorted(filenames):
                path = Path(dirpath) / name
                if self.is_ignored(path, is_dir=False):
                    continue
                yield path

    # ------------------------------------------------------------- writing

    def write_file(self, relative: str, content: str) -> Dict[str, Any]:
        path = self.resolve(relative)
        if path.is_dir():
            raise WorkspaceError(f"{relative!r} is a directory.")
        previous = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return {
            "path": self.relative(path),
            "created": previous == "" and not content == "",
            "bytesWritten": len(content.encode("utf-8")),
            "diff": self._diff(previous, content, self.relative(path)),
        }

    def edit_file(
        self,
        relative: str,
        edits: Sequence[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Apply exact-string replacements to a file, returning a unified diff."""
        path = self.resolve(relative, must_exist=True)
        if path.is_dir():
            raise WorkspaceError(f"{relative!r} is a directory.")
        original = path.read_text(encoding="utf-8", errors="replace")
        updated = original
        applied = 0
        for edit in edits:
            old = edit.get("oldString")
            new = edit.get("newString")
            if not isinstance(old, str) or not isinstance(new, str):
                raise WorkspaceError("Each edit needs string 'oldString' and 'newString'.")
            if old == new:
                raise WorkspaceError("An edit's oldString and newString are identical.")
            count = updated.count(old)
            if count == 0:
                raise WorkspaceError(f"oldString not found in {relative}: {old[:80]!r}")
            if count > 1 and not edit.get("replaceAll"):
                raise WorkspaceError(
                    f"oldString appears {count} times in {relative}; add context or set replaceAll."
                )
            updated = updated.replace(old, new) if edit.get("replaceAll") else updated.replace(old, new, 1)
            applied += 1
        path.write_text(updated, encoding="utf-8")
        return {
            "path": self.relative(path),
            "editsApplied": applied,
            "bytesWritten": len(updated.encode("utf-8")),
            "diff": self._diff(original, updated, self.relative(path)),
        }

    @staticmethod
    def _diff(before: str, after: str, path: str) -> str:
        diff = difflib.unified_diff(
            before.splitlines(),
            after.splitlines(),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
            lineterm="",
        )
        return "\n".join(diff)

    # ---------------------------------------------------------- execution

    async def run(
        self,
        command: str,
        *,
        cwd: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        if not self.allow_exec:
            raise WorkspaceError("Command execution is disabled for this workspace.")
        workdir = self.resolve(cwd or ".", must_exist=True)
        if not workdir.is_dir():
            raise WorkspaceError(f"cwd is not a directory: {cwd!r}")
        limit = timeout or self.exec_timeout
        try:
            process = await asyncio.create_subprocess_shell(
                command,
                cwd=str(workdir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as exc:
            raise WorkspaceError(f"Could not start command: {exc}") from exc

        timed_out = False
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=limit)
        except asyncio.TimeoutError:
            timed_out = True
            process.kill()
            stdout, stderr = await process.communicate()

        return {
            "command": command,
            "cwd": self.relative(workdir),
            "exitCode": process.returncode,
            "timedOut": timed_out,
            "stdout": _clip(stdout.decode("utf-8", errors="replace"), self.max_output_bytes),
            "stderr": _clip(stderr.decode("utf-8", errors="replace"), self.max_output_bytes),
        }


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... (truncated at {limit} chars)"
