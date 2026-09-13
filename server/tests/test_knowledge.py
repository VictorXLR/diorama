"""Tests for the durable knowledge base and the query service."""

import subprocess
from pathlib import Path

import pytest

from diorama.codebase.workspace import Workspace
from diorama.knowledge import (
    KnowledgeBase,
    compute_file_state,
    diff_file_states,
    identify_repository,
    signature_for,
)
from diorama.queries import QueryError, run_query


@pytest.fixture
def kb(tmp_path: Path) -> KnowledgeBase:
    return KnowledgeBase(tmp_path / "knowledge.db")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "app.py").write_text("print('hi')\n")
    (root / "utils.py").write_text("def helper():\n    return 1\n")
    return root


class TestKnowledgeStore:
    def test_disabled_store_is_a_noop(self, tmp_path: Path):
        disabled = KnowledgeBase(None)
        assert not disabled.enabled
        disabled.upsert_repository("r1", "/x", "x")
        disabled.record_analysis("r1", "graph", {"a": 1})
        assert disabled.list_repositories() == []
        assert disabled.latest_analysis("r1", "graph") is None
        assert disabled.stored_file_state("r1") == {}

    def test_repository_upsert_and_lookup(self, kb: KnowledgeBase, repo: Path):
        kb.upsert_repository("r1", str(repo), repo.name, git_remote="git@example.com:a/b.git", signature="sig1")
        record = kb.get_repository("r1")
        assert record is not None
        assert record["name"] == repo.name
        assert record["git_remote"] == "git@example.com:a/b.git"
        assert record["signature"] == "sig1"
        # Upsert keeps the existing remote when the new one is unknown.
        kb.upsert_repository("r1", str(repo), repo.name, signature="sig2")
        assert kb.get_repository("r1")["git_remote"] == "git@example.com:a/b.git"
        assert kb.find_repository_by_root(str(repo))["repo_id"] == "r1"

    def test_analysis_roundtrip_and_history_cap(self, kb: KnowledgeBase):
        for index in range(30):
            kb.record_analysis("r1", "graph", {"index": index}, signature=f"sig{index}")
        latest = kb.latest_analysis("r1", "graph", signature="sig29")
        assert latest is not None
        assert latest["payload"] == {"index": 29}
        # Only the most recent 25 per (repo, kind) are retained.
        assert len(kb.list_analyses(repo_id="r1")) == 25
        # Signature-scoped lookup misses older entries.
        assert kb.latest_analysis("r1", "graph", signature="sig0") is None

    def test_file_state_store_and_diff(self, kb: KnowledgeBase):
        state = {"a.py": "h1", "b.py": "h2"}
        kb.store_file_state("r1", state)
        assert kb.stored_file_state("r1") == state
        diff = diff_file_states(state, {"a.py": "h1!", "b.py": "h2", "c.py": "h3"})
        assert diff == {"added": ["c.py"], "removed": [], "changed": ["a.py"]}

    def test_artifact_save_and_list(self, kb: KnowledgeBase):
        kb.save_artifact("r1", "map", "excalidraw", {"elements": []})
        artifacts = kb.list_artifacts(repo_id="r1")
        assert len(artifacts) == 1
        assert artifacts[0]["name"] == "map"


class TestRepoIdentity:
    def test_git_identity(self, repo: Path):
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        subprocess.run(["git", "remote", "add", "origin", "git@example.com:owner/repo.git"], cwd=repo, check=True)
        identity = identify_repository(repo)
        assert identity["git_remote"] == "git@example.com:owner/repo.git"
        # No commits yet: HEAD is unknown but must not raise.
        assert identity["commit"] is None
        assert identity["repo_id"] == identify_repository(repo)["repo_id"]

    def test_identity_outside_git(self, repo: Path):
        identity = identify_repository(repo)
        assert identity["git_remote"] is None
        assert identity["commit"] is None
        assert identity["name"] == repo.name


class TestSignatures:
    def test_signature_changes_with_content(self, repo: Path):
        files = list(Workspace(repo).iter_files())
        state = compute_file_state(repo, files)
        first = signature_for(state)
        assert signature_for(compute_file_state(repo, files)) == first
        (repo / "app.py").write_text("print('changed')\n")
        assert signature_for(compute_file_state(repo, files)) != first


class TestRunQuery:
    def test_graph_query_records_and_caches(self, kb: KnowledgeBase, repo: Path):
        workspace = Workspace(repo)
        first = run_query(workspace, "graph", kb)
        assert first["cached"] is False
        assert first["payload"]["totalFiles"] == 2
        assert first["repo"]["name"] == repo.name
        assert first["changedSinceLastIndex"]["added"] == ["app.py", "utils.py"]

        second = run_query(workspace, "graph", kb)
        assert second["cached"] is True
        assert second["payload"] == first["payload"]
        assert second["changedSinceLastIndex"] == {"added": [], "removed": [], "changed": []}

        # A content change invalidates the cache.
        (repo / "app.py").write_text("print('changed')\n")
        third = run_query(workspace, "graph", kb)
        assert third["cached"] is False
        assert third["changedSinceLastIndex"]["changed"] == ["app.py"]

        # Force recomputes even when the cache would hit.
        fourth = run_query(workspace, "graph", kb, force=True)
        assert fourth["cached"] is False

    def test_unknown_kind_rejected(self, kb: KnowledgeBase, repo: Path):
        with pytest.raises(QueryError):
            run_query(Workspace(repo), "nonsense", kb)

    def test_table_query_requires_and_uses_name(self, kb: KnowledgeBase, repo: Path):
        workspace = Workspace(repo)
        with pytest.raises(QueryError):
            run_query(workspace, "table", kb)
        with pytest.raises(QueryError):
            run_query(workspace, "table", kb, table="missing")

    def test_changes_query(self, kb: KnowledgeBase, repo: Path):
        workspace = Workspace(repo)
        run_query(workspace, "graph", kb)  # seeds the file state
        (repo / "new.py").write_text("x = 1\n")
        result = run_query(workspace, "changes", kb)
        assert result["payload"]["added"] == ["new.py"]
        # The changes query stores the new state, so a repeat is empty.
        assert run_query(workspace, "changes", kb)["payload"] == {
            "added": [], "removed": [], "changed": [],
        }
