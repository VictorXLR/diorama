"""HTTP tests for the deterministic query channel and knowledge-base endpoints."""

from pathlib import Path

import pytest
from starlette.testclient import TestClient

from diorama.app import app
import diorama.server as server_module


@pytest.fixture(autouse=True)
def restore_workspace():
    """Query endpoints read the module-global workspace; keep tests isolated."""
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
    (tmp_path / "app.py").write_text("from supabase import create_client\nclient = create_client('u', 'k')\n")
    (tmp_path / "page.tsx").write_text(
        "const { data } = await client.from('items').select('id, name');\n"
        "export default function Page() { return null; }\n"
    )
    return tmp_path


def _bind(client, repo: Path):
    response = client.post("/api/workspace/bind", json={"path": str(repo)})
    assert response.status_code == 200
    return response.json()


def test_query_requires_bound_workspace(client):
    server_module.workspace = None
    response = client.get("/api/query/graph")
    assert response.status_code == 409
    assert "No workspace is bound" in response.json()["detail"]


def test_query_graph_and_cache(client, sample_repo):
    _bind(client, sample_repo)
    # Binding indexes the repo, so the first query is already served from the KB.
    first = client.get("/api/query/graph").json()
    assert first["cached"] is True
    assert first["payload"]["totalFiles"] == 2
    # Force recomputes; a follow-up query is cached again.
    forced = client.get("/api/query/graph", params={"force": True}).json()
    assert forced["cached"] is False
    assert forced["payload"] == first["payload"]
    assert client.get("/api/query/graph").json()["cached"] is True


def test_query_connectivity_reports_supabase(client, sample_repo):
    _bind(client, sample_repo)
    body = client.get("/api/query/connectivity").json()
    connectors = [c["name"] for c in body["payload"]["connectors"]]
    assert "Supabase" in connectors
    tables = [t["name"] for t in body["payload"]["tables"]]
    assert "items" in tables


def test_query_table_zoom(client, sample_repo):
    _bind(client, sample_repo)
    ok = client.get("/api/query/table", params={"table": "items"})
    assert ok.status_code == 200
    table = ok.json()["payload"]
    assert table["name"] == "items"
    assert "id" in table["columns"] and "name" in table["columns"]
    missing = client.get("/api/query/table", params={"table": "nope"})
    assert missing.status_code == 400
    assert "no table named" in missing.json()["detail"].lower()


def test_query_changes_reports_edits(client, sample_repo):
    _bind(client, sample_repo)
    (sample_repo / "app.py").write_text("print('edited')\n")
    body = client.get("/api/query/changes").json()
    assert "app.py" in body["payload"]["changed"]


def test_query_unknown_kind_is_400(client, sample_repo):
    _bind(client, sample_repo)
    response = client.get("/api/query/nonsense")
    assert response.status_code == 400


def test_bind_records_graph_in_kb(client, sample_repo):
    _bind(client, sample_repo)
    repos = client.get("/api/kb/repos").json()["repositories"]
    assert any(r["root"] == str(sample_repo) for r in repos)
    analyses = client.get("/api/kb/analyses").json()["analyses"]
    assert any(a["kind"] == "graph" for a in analyses)


def test_kb_endpoints_after_queries(client, sample_repo):
    _bind(client, sample_repo)
    client.get("/api/query/connectivity")
    client.get("/api/query/architecture")
    repo_row = next(
        r for r in client.get("/api/kb/repos").json()["repositories"] if r["root"] == str(sample_repo)
    )
    analyses = client.get("/api/kb/analyses", params={"repo_id": repo_row["repo_id"]}).json()["analyses"]
    kinds = {a["kind"] for a in analyses}
    assert {"graph", "connectivity", "architecture"} <= kinds
    assert client.get("/api/kb/artifacts").json()["artifacts"] == []
