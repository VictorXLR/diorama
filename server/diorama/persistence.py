"""Optional SQLite persistence for sessions.

By default the server keeps sessions in memory (fast, and what tests rely on).
Set ``DIORAMA_DB`` to a file path to survive restarts and to let multiple
workers share state.  Sessions are stored as one JSON row each; the in-memory
dict stays the hot path and the database is written through on every mutation.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from diorama.models.canvas import CanvasFile
from diorama.models.chat import ChatMessage

logger = logging.getLogger("diorama.persistence")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    data TEXT NOT NULL,
    updated_at REAL NOT NULL DEFAULT (strftime('%s', 'now'))
)
"""


def _dump(model: Any) -> Any:
    if hasattr(model, "model_dump"):
        return model.model_dump(by_alias=True, exclude_none=True)
    return model


def _dump_files(files: Dict[str, Any]) -> Dict[str, Any]:
    return {key: _dump(value) for key, value in (files or {}).items()}


def serialize_session(session_data: Dict[str, Any]) -> Dict[str, Any]:
    turns = []
    for turn in session_data.get("turns", []):
        turns.append(
            {
                "turn_id": turn["turn_id"],
                "visual_elements": turn.get("visual_elements", []),
                "files": _dump_files(turn.get("files", {})),
                "file_edits": dict(turn.get("file_edits", {})),
                "codebase_map_element_ids": list(turn.get("codebase_map_element_ids", [])),
            }
        )
    return {
        "session_id": session_data["session_id"],
        "context": _dump(session_data.get("context")),
        "messages": [_dump(message) for message in session_data.get("messages", [])],
        "visual_elements": session_data.get("visual_elements", []),
        "files": _dump_files(session_data.get("files", {})),
        "turns": turns,
        "codebase_map_element_ids": list(session_data.get("codebase_map_element_ids", [])),
        "scene_version": session_data.get("scene_version", 0),
    }


def deserialize_session(record: Dict[str, Any]) -> Dict[str, Any]:
    messages: List[ChatMessage] = []
    for raw in record.get("messages", []):
        try:
            messages.append(ChatMessage.model_validate(raw))
        except Exception:  # noqa: BLE001 - skip a corrupt message rather than drop the session
            logger.warning("Dropping unreadable chat message from persisted session")
    files: Dict[str, CanvasFile] = {}
    for key, raw in (record.get("files") or {}).items():
        try:
            files[key] = CanvasFile.model_validate(raw)
        except Exception:  # noqa: BLE001
            logger.warning("Dropping unreadable canvas file %s from persisted session", key)
    return {
        "session_id": record["session_id"],
        "context": record.get("context"),
        "messages": messages,
        "visual_elements": record.get("visual_elements", []),
        "files": files,
        "turns": record.get("turns", []),
        "codebase_map_element_ids": record.get("codebase_map_element_ids", []),
        "scene_version": record.get("scene_version", 0),
    }


class SessionStore:
    """Write-through persistence for sessions. Disabled when ``path`` is None."""

    def __init__(self, path: Optional[Path]) -> None:
        self.path = path
        self._lock = threading.Lock()
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            with self._connect() as connection:
                connection.execute(_SCHEMA)
            logger.info("Session persistence enabled at %s", path)

    @property
    def enabled(self) -> bool:
        return self.path is not None

    def _connect(self) -> sqlite3.Connection:
        assert self.path is not None
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        return connection

    def load_all(self) -> Dict[str, Dict[str, Any]]:
        if not self.enabled:
            return {}
        try:
            with self._lock, self._connect() as connection:
                rows = connection.execute("SELECT data FROM sessions").fetchall()
        except sqlite3.Error as exc:  # pragma: no cover - defensive
            logger.warning("Could not read sessions: %s", exc)
            return {}
        sessions: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            try:
                record = json.loads(row["data"])
                sessions[record["session_id"]] = deserialize_session(record)
            except (json.JSONDecodeError, KeyError, TypeError):
                logger.warning("Skipping corrupt session row")
        return sessions

    def save(self, session_data: Dict[str, Any]) -> None:
        if not self.enabled:
            return
        try:
            payload = json.dumps(serialize_session(session_data), ensure_ascii=False)
            with self._lock, self._connect() as connection:
                connection.execute(
                    "INSERT INTO sessions (session_id, data, updated_at) VALUES (?, ?, strftime('%s','now')) "
                    "ON CONFLICT(session_id) DO UPDATE SET data = excluded.data, updated_at = excluded.updated_at",
                    (session_data["session_id"], payload),
                )
        except sqlite3.Error as exc:  # pragma: no cover - defensive
            logger.warning("Could not persist session %s: %s", session_data.get("session_id"), exc)

    def delete(self, session_id: str) -> None:
        if not self.enabled:
            return
        with self._lock, self._connect() as connection:
            connection.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
