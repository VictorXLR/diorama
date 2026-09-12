"""Tests for production-facing pieces: config, persistence, and the CLI."""

from __future__ import annotations

import json

from diorama.config import load_settings
from diorama.models.canvas import CanvasFile
from diorama.models.chat import ChatMessage
from diorama.persistence import SessionStore, deserialize_session, serialize_session


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #


def test_settings_default_to_no_workspace_and_local_cors(monkeypatch):
    for name in ("DIORAMA_WORKSPACE", "DIORAMA_DB", "DIORAMA_CORS_ORIGINS", "DIORAMA_RELOAD"):
        monkeypatch.delenv(name, raising=False)
    settings = load_settings()
    assert settings.workspace_root is None
    assert settings.reload is False
    assert settings.database_path is None
    assert all("localhost" in origin or "127.0.0.1" in origin for origin in settings.cors_origins)


def test_settings_read_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("DIORAMA_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("DIORAMA_ALLOW_EXEC", "off")
    monkeypatch.setenv("DIORAMA_CORS_ORIGINS", "https://app.example.com, https://admin.example.com")
    monkeypatch.setenv("DIORAMA_DB", str(tmp_path / "sessions.db"))
    settings = load_settings()
    assert settings.workspace_root == tmp_path.resolve()
    assert settings.allow_exec is False
    assert settings.cors_origins == ["https://app.example.com", "https://admin.example.com"]
    assert settings.database_path == tmp_path / "sessions.db"


def test_wildcard_origin_disables_credentials(monkeypatch):
    monkeypatch.setenv("DIORAMA_CORS_ORIGINS", "*")
    monkeypatch.setenv("DIORAMA_CORS_CREDENTIALS", "on")
    settings = load_settings()
    assert settings.cors_origins == ["*"]
    assert settings.allow_credentials is False


# --------------------------------------------------------------------------- #
# Persistence
# --------------------------------------------------------------------------- #


def test_session_serialization_roundtrip():
    session = {
        "session_id": "sess-1",
        "context": None,
        "messages": [ChatMessage(id="m1", sender="user", content="hi", timestamp="10:00 AM")],
        "visual_elements": [{"id": "e1", "type": "text", "x": 0, "y": 0, "text": "hello"}],
        "files": {"asset-1": CanvasFile(mimeType="image/png", dataURL="data:image/png;base64,AAAA")},
        "turns": [{"turn_id": "turn-1", "visual_elements": [], "files": {}, "file_edits": {"a.py": "old"}}],
    }
    restored = deserialize_session(serialize_session(session))
    assert isinstance(restored["messages"][0], ChatMessage)
    assert isinstance(restored["files"]["asset-1"], CanvasFile)
    assert restored["visual_elements"][0]["text"] == "hello"
    assert restored["turns"][0]["file_edits"] == {"a.py": "old"}


def test_session_store_persists_to_sqlite(tmp_path):
    store = SessionStore(tmp_path / "sessions.db")
    assert store.enabled
    session = {
        "session_id": "sess-2",
        "context": None,
        "messages": [ChatMessage(id="m1", sender="user", content="persist me", timestamp="10:00 AM")],
        "visual_elements": [],
        "files": {},
        "turns": [],
    }
    store.save(session)

    reopened = SessionStore(tmp_path / "sessions.db")
    loaded = reopened.load_all()
    assert "sess-2" in loaded
    assert loaded["sess-2"]["messages"][0].content == "persist me"


def test_session_store_disabled_is_a_noop(tmp_path):
    store = SessionStore(None)
    assert store.enabled is False
    store.save({"session_id": "x", "messages": [], "visual_elements": [], "files": {}, "turns": []})
    assert store.load_all() == {}


# --------------------------------------------------------------------------- #
# File changes surfaced to the client
# --------------------------------------------------------------------------- #


def test_summarize_file_changes_counts_and_classifies():
    from diorama.server import summarize_file_changes

    result = summarize_file_changes(
        [
            {
                "path": "a.py",
                "before": "x = 1\n",
                "after": "x = 2\n",
                "diff": "--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-x = 1\n+x = 2",
            },
            {"path": "new.py", "before": "", "after": "A = 1\n", "diff": "--- a/new.py\n+++ b/new.py\n@@\n+A = 1"},
            {"path": ""},  # no path -> skipped
        ]
    )
    assert [change.path for change in result] == ["a.py", "new.py"]
    assert result[0].change == "modified"
    assert result[0].additions == 1
    assert result[0].deletions == 1
    assert result[1].change == "created"
    assert result[1].additions == 1


def test_chat_message_persists_file_changes():
    message = ChatMessage.model_validate(
        {
            "id": "m1",
            "sender": "agent",
            "content": "done",
            "timestamp": "10:00 AM",
            "fileChanges": [
                {"path": "a.py", "change": "modified", "diff": "+x", "additions": 1, "deletions": 0}
            ],
        }
    )
    session = {
        "session_id": "sess-files",
        "context": None,
        "messages": [message],
        "visual_elements": [],
        "files": {},
        "turns": [],
    }
    restored = deserialize_session(serialize_session(session))
    assert restored["messages"][0].file_changes[0].path == "a.py"
    assert restored["messages"][0].file_changes[0].additions == 1


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def _sample_repo(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("")
    (tmp_path / "app" / "main.py").write_text("from app.helper import run\n\ndef main():\n    return run()\n")
    (tmp_path / "app" / "helper.py").write_text("def run():\n    return 1\n")
    return tmp_path


def test_cli_index_json(tmp_path, capsys):
    from diorama.cli import main

    repo = _sample_repo(tmp_path)
    code = main(["index", str(repo), "--json", "--max-nodes", "10"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    paths = {node["path"] for node in payload["nodes"]}
    assert "app/main.py" in paths


def test_cli_analyze_writes_excalidraw_scene(tmp_path, capsys):
    from diorama.cli import main

    out = tmp_path / "map.excalidraw"
    code = main(["analyze", str(_sample_repo(tmp_path)), "-o", str(out)])
    assert code == 0
    scene = json.loads(out.read_text())
    assert scene["type"] == "excalidraw"
    assert any(element["type"] == "frame" for element in scene["elements"])
    assert any(element["type"] == "rectangle" for element in scene["elements"])


# --------------------------------------------------------------------------- #
# Frontend serving
# --------------------------------------------------------------------------- #


def _fake_dist(tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text('<!doctype html><div id="root"></div>')
    (dist / "assets" / "app.js").write_text("console.log('hi')")
    return dist


def test_frontend_enabled_only_when_build_present(monkeypatch, tmp_path):
    monkeypatch.setenv("DIORAMA_WEB_DIST", str(tmp_path / "missing"))
    assert load_settings().frontend_enabled is False
    dist = _fake_dist(tmp_path)
    monkeypatch.setenv("DIORAMA_WEB_DIST", str(dist))
    assert load_settings().frontend_enabled is True


def test_mount_frontend_serves_spa_and_assets(tmp_path):
    from fastapi import FastAPI
    from starlette.testclient import TestClient

    from diorama.server import mount_frontend

    app = FastAPI()

    @app.get("/api/thing")
    async def thing():
        return {"ok": True}

    assert mount_frontend(app, _fake_dist(tmp_path)) is True
    client = TestClient(app)
    root = client.get("/")
    assert root.status_code == 200
    assert 'id="root"' in root.text
    assert client.get("/assets/app.js").status_code == 200
    # API routes still win over the SPA mount.
    assert client.get("/api/thing").json() == {"ok": True}


def test_mount_frontend_is_noop_without_build(tmp_path):
    from fastapi import FastAPI

    from diorama.server import mount_frontend

    assert mount_frontend(FastAPI(), tmp_path / "nope") is False
