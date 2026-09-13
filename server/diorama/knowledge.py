"""The durable knowledge base: what Diorama has learned about repositories.

Sessions are conversations; this is memory.  Every analysis the system runs
(structural graph, API connectivity, architecture) is recorded here keyed by
repository identity and a content signature, so:

  * re-querying an unchanged repo is answered from the store, not recomputed,
  * the history of what a repo looked like over time is preserved forever,
  * the CLI and the web UI read the same records.

Storage is SQLite at ``~/.diorama/knowledge.db`` by default (override with
``DIORAMA_KB``; set ``DIORAMA_KB=off`` to disable).
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("diorama.knowledge")

DEFAULT_KB_PATH = Path.home() / ".diorama" / "knowledge.db"

# Files larger than this are fingerprinted by (path, size) instead of content.
_MAX_HASH_BYTES = 1_000_000

_SCHEMA = """
CREATE TABLE IF NOT EXISTS repositories (
    repo_id TEXT PRIMARY KEY,
    root TEXT NOT NULL,
    name TEXT NOT NULL,
    git_remote TEXT,
    last_commit TEXT,
    last_indexed_at REAL NOT NULL,
    signature TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS analyses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    commit_hash TEXT,
    signature TEXT NOT NULL,
    payload TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_analyses_repo_kind ON analyses(repo_id, kind, created_at);
CREATE TABLE IF NOT EXISTS file_hashes (
    repo_id TEXT NOT NULL,
    path TEXT NOT NULL,
    hash TEXT NOT NULL,
    PRIMARY KEY (repo_id, path)
);
CREATE TABLE IF NOT EXISTS artifacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_id TEXT NOT NULL,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    payload TEXT NOT NULL,
    created_at REAL NOT NULL
);
"""

ANALYSIS_KINDS = ("graph", "connectivity", "architecture")


def identify_repository(root: Path) -> Dict[str, Any]:
    """Best-effort repository identity: stable id, git remote, HEAD commit."""
    repo_id = hashlib.sha256(str(root).encode("utf-8")).hexdigest()[:16]
    remote = None
    commit = None
    try:
        result = subprocess.run(  # noqa: S603 - fixed argv, no shell
            ["git", "-C", str(root), "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if result.returncode == 0:
            remote = result.stdout.strip() or None
        result = subprocess.run(  # noqa: S603
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if result.returncode == 0:
            commit = result.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        pass
    return {"repo_id": repo_id, "root": str(root), "name": root.name, "git_remote": remote, "commit": commit}


def _file_digest(path: Path) -> str:
    """Content hash for reasonably sized files, (path, size) beyond the cap."""
    try:
        size = path.stat().st_size
        if size > _MAX_HASH_BYTES:
            return hashlib.sha256(f"{path.name}:{size}".encode("utf-8")).hexdigest()
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return "unreadable"


def compute_file_state(root: Path, files: List[Path]) -> Dict[str, str]:
    """Map of relative path -> content digest for the given files."""
    state: Dict[str, str] = {}
    for path in files:
        try:
            relative = path.relative_to(root).as_posix()
        except ValueError:
            continue
        state[relative] = _file_digest(path)
    return state


def signature_for(state: Dict[str, str]) -> str:
    """Stable digest over the whole file state; changes when any file changes."""
    digest = hashlib.sha256()
    for relative in sorted(state):
        digest.update(relative.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(state[relative].encode("utf-8"))
        digest.update(b"\x00")
    return digest.hexdigest()


def diff_file_states(previous: Dict[str, str], current: Dict[str, str]) -> Dict[str, List[str]]:
    added = sorted(path for path in current if path not in previous)
    removed = sorted(path for path in previous if path not in current)
    changed = sorted(
        path for path in current if path in previous and current[path] != previous[path]
    )
    return {"added": added, "removed": removed, "changed": changed}


class KnowledgeBase:
    """SQLite-backed store for repository analyses and artifacts."""

    def __init__(self, path: Optional[Path]) -> None:
        self.path = path
        self._lock = threading.Lock()
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            with self._connect() as connection:
                connection.executescript(_SCHEMA)
            logger.info("Knowledge base enabled at %s", path)

    @property
    def enabled(self) -> bool:
        return self.path is not None

    def _connect(self) -> sqlite3.Connection:
        assert self.path is not None
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    # ------------------------------------------------------------ repositories

    def upsert_repository(
        self,
        repo_id: str,
        root: str,
        name: str,
        *,
        git_remote: Optional[str] = None,
        commit: Optional[str] = None,
        signature: Optional[str] = None,
    ) -> None:
        if not self.enabled:
            return
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT INTO repositories (repo_id, root, name, git_remote, last_commit, last_indexed_at, signature) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(repo_id) DO UPDATE SET root=excluded.root, name=excluded.name, "
                "git_remote=COALESCE(excluded.git_remote, repositories.git_remote), "
                "last_commit=COALESCE(excluded.last_commit, repositories.last_commit), "
                "last_indexed_at=excluded.last_indexed_at, "
                "signature=COALESCE(excluded.signature, repositories.signature)",
                (repo_id, root, name, git_remote, commit, time.time(), signature),
            )

    def get_repository(self, repo_id: str) -> Optional[Dict[str, Any]]:
        if not self.enabled:
            return None
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM repositories WHERE repo_id = ?", (repo_id,)
            ).fetchone()
        return dict(row) if row else None

    def find_repository_by_root(self, root: str) -> Optional[Dict[str, Any]]:
        if not self.enabled:
            return None
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM repositories WHERE root = ? ORDER BY last_indexed_at DESC LIMIT 1",
                (root,),
            ).fetchone()
        return dict(row) if row else None

    def list_repositories(self) -> List[Dict[str, Any]]:
        if not self.enabled:
            return []
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT r.*, "
                "(SELECT COUNT(*) FROM analyses a WHERE a.repo_id = r.repo_id) AS analysis_count "
                "FROM repositories r ORDER BY r.last_indexed_at DESC"
            ).fetchall()
        return [dict(row) for row in rows]

    # -------------------------------------------------------------- analyses

    def record_analysis(
        self,
        repo_id: str,
        kind: str,
        payload: Dict[str, Any],
        *,
        commit: Optional[str] = None,
        signature: Optional[str] = None,
    ) -> None:
        """Append an analysis to the history; keeps the last 25 per (repo, kind)."""
        if not self.enabled:
            return
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT INTO analyses (repo_id, kind, commit_hash, signature, payload, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (repo_id, kind, commit, signature, json.dumps(payload, ensure_ascii=False), time.time()),
            )
            connection.execute(
                "DELETE FROM analyses WHERE id IN ("
                "  SELECT id FROM analyses WHERE repo_id = ? AND kind = ? "
                "  ORDER BY created_at DESC, id DESC LIMIT -1 OFFSET 25"
                ")",
                (repo_id, kind),
            )

    def latest_analysis(
        self, repo_id: str, kind: str, signature: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Most recent analysis of a kind, optionally matching a content signature."""
        if not self.enabled:
            return None
        query = "SELECT * FROM analyses WHERE repo_id = ? AND kind = ?"
        params: List[Any] = [repo_id, kind]
        if signature is not None:
            query += " AND signature = ?"
            params.append(signature)
        query += " ORDER BY created_at DESC, id DESC LIMIT 1"
        with self._lock, self._connect() as connection:
            row = connection.execute(query, params).fetchone()
        if row is None:
            return None
        record = dict(row)
        try:
            record["payload"] = json.loads(record["payload"])
        except json.JSONDecodeError:
            logger.warning("Dropping corrupt %s analysis for %s", kind, repo_id)
            return None
        return record

    def list_analyses(self, repo_id: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        if not self.enabled:
            return []
        query = (
            "SELECT id, repo_id, kind, commit_hash, signature, created_at FROM analyses"
        )
        params: List[Any] = []
        if repo_id:
            query += " WHERE repo_id = ?"
            params.append(repo_id)
        query += " ORDER BY created_at DESC, id DESC LIMIT ?"
        params.append(limit)
        with self._lock, self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    # ------------------------------------------------------------ file hashes

    def stored_file_state(self, repo_id: str) -> Dict[str, str]:
        if not self.enabled:
            return {}
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT path, hash FROM file_hashes WHERE repo_id = ?", (repo_id,)
            ).fetchall()
        return {row["path"]: row["hash"] for row in rows}

    def store_file_state(self, repo_id: str, state: Dict[str, str]) -> None:
        if not self.enabled:
            return
        rows = [(repo_id, path, digest) for path, digest in state.items()]
        with self._lock, self._connect() as connection:
            connection.execute("DELETE FROM file_hashes WHERE repo_id = ?", (repo_id,))
            connection.executemany(
                "INSERT INTO file_hashes (repo_id, path, hash) VALUES (?, ?, ?)", rows
            )

    # -------------------------------------------------------------- artifacts

    def save_artifact(
        self, repo_id: str, name: str, kind: str, payload: Dict[str, Any]
    ) -> int:
        if not self.enabled:
            return -1
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                "INSERT INTO artifacts (repo_id, name, kind, payload, created_at) VALUES (?, ?, ?, ?, ?)",
                (repo_id, name, kind, json.dumps(payload, ensure_ascii=False), time.time()),
            )
        return int(cursor.lastrowid or -1)

    def list_artifacts(self, repo_id: Optional[str] = None) -> List[Dict[str, Any]]:
        if not self.enabled:
            return []
        query = "SELECT id, repo_id, name, kind, created_at FROM artifacts"
        params: List[Any] = []
        if repo_id:
            query += " WHERE repo_id = ?"
            params.append(repo_id)
        query += " ORDER BY created_at DESC"
        with self._lock, self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [dict(row) for row in rows]


def load_knowledge_base(path: Optional[Path]) -> KnowledgeBase:
    """Construct the store; ``None`` (or ``off``) disables it."""
    return KnowledgeBase(path)
