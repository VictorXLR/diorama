"""HTTP endpoints for choosing and binding a workspace directory from the UI."""

from pathlib import Path

import pytest
from starlette.testclient import TestClient

from diorama.app import app
import diorama.server as server_module


@pytest.fixture(autouse=True)
def restore_workspace():
    """The bind endpoint mutates module globals; keep tests isolated."""
    saved_workspace = server_module.workspace
    saved_seed = server_module.codebase_seed
    try:
        yield
    finally:
        server_module.workspace = saved_workspace
        server_module.codebase_seed = saved_seed


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def sample_repo(tmp_path: Path) -> Path:
    (tmp_path / "app.py").write_text("import utils\nprint(utils.helper())\n")
    (tmp_path / "utils.py").write_text("def helper():\n    return 42\n")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "junk").mkdir()
    return tmp_path


def test_browse_defaults_to_home(client):
    response = client.get("/api/workspace/browse")
    assert response.status_code == 200
    body = response.json()
    assert body["path"]
    assert isinstance(body["entries"], list)


def test_browse_lists_subdirectories_and_skips_noise(client, sample_repo):
    response = client.get("/api/workspace/browse", params={"path": str(sample_repo)})
    assert response.status_code == 200
    body = response.json()
    assert body["path"] == str(sample_repo)
    assert body["parent"] == str(sample_repo.parent)
    names = [entry["name"] for entry in body["entries"]]
    assert names == []  # only node_modules existed, and it is skipped


def test_browse_rejects_missing_directory(client):
    response = client.get("/api/workspace/browse", params={"path": "/definitely/not/a/dir"})
    assert response.status_code == 400
    assert "Not a directory" in response.json()["detail"]


def test_workspace_status_reports_binding(client):
    response = client.get("/api/workspace")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"root", "name", "codebase", "execEnabled"}
    # Whatever is bound, the element list must never leak to the browser.
    if body["codebase"] is not None:
        assert "visual_elements" not in body["codebase"]


def test_bind_indexes_new_root(client, sample_repo):
    response = client.post("/api/workspace/bind", json={"path": str(sample_repo)})
    assert response.status_code == 200
    body = response.json()
    assert body["root"] == str(sample_repo)
    assert body["warning"] is None
    assert body["codebase"]["indexedFiles"] == 2
    assert body["codebase"]["edges"] >= 1
    assert server_module.workspace is not None
    assert server_module.workspace.root == sample_repo
    assert server_module.codebase_seed is not None


def test_bind_rejects_file_path(client, sample_repo):
    response = client.post("/api/workspace/bind", json={"path": str(sample_repo / "app.py")})
    assert response.status_code == 400
    assert "Not a directory" in response.json()["detail"]


def test_bind_warns_when_nothing_indexable(client, tmp_path):
    (tmp_path / "subdir").mkdir()  # empty: no source files at all
    response = client.post("/api/workspace/bind", json={"path": str(tmp_path)})
    assert response.status_code == 200
    body = response.json()
    assert body["root"] == str(tmp_path)
    assert body["codebase"]["indexedFiles"] == 0
    assert "no source files" in body["warning"]


def test_bind_requires_path(client):
    response = client.post("/api/workspace/bind", json={})
    assert response.status_code == 422


def test_browse_skips_hidden_directories(client, tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".venv").mkdir()
    (tmp_path / "src").mkdir()
    response = client.get("/api/workspace/browse", params={"path": str(tmp_path)})
    assert response.status_code == 200
    names = [entry["name"] for entry in response.json()["entries"]]
    assert names == ["src"]


def test_browse_caps_entries(client, tmp_path, monkeypatch):
    for index in range(5):
        (tmp_path / f"dir-{index:02d}").mkdir()
    monkeypatch.setattr(server_module, "MAX_BROWSE_ENTRIES", 3)
    response = client.get("/api/workspace/browse", params={"path": str(tmp_path)})
    assert response.status_code == 200
    body = response.json()
    assert len(body["entries"]) == 3
    assert body["truncated"] is True


def test_browse_rejects_paths_outside_allowlist(client, tmp_path, monkeypatch):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    import dataclasses

    monkeypatch.setattr(
        server_module,
        "settings",
        dataclasses.replace(server_module.settings, browse_roots=(allowed.resolve(),)),
    )
    ok = client.get("/api/workspace/browse", params={"path": str(allowed)})
    denied = client.get("/api/workspace/browse", params={"path": str(outside)})
    assert ok.status_code == 200
    assert denied.status_code == 403
    assert "outside the allowed browse roots" in denied.json()["detail"]


def test_bind_rejects_paths_outside_allowlist(client, sample_repo, monkeypatch):
    allowed = sample_repo / "allowed"
    allowed.mkdir()
    import dataclasses

    monkeypatch.setattr(
        server_module,
        "settings",
        dataclasses.replace(server_module.settings, browse_roots=(allowed.resolve(),)),
    )
    response = client.post("/api/workspace/bind", json={"path": str(sample_repo)})
    assert response.status_code == 400
    assert "outside the allowed browse roots" in response.json()["detail"]
    assert server_module.workspace is None or server_module.workspace.root != sample_repo
