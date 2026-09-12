"""Tests for the codebase-facing layer: workspace, indexer, and code tools."""

from __future__ import annotations

import pytest

from diorama.codebase.indexer import build_code_graph
from diorama.codebase.visualize import graph_to_primitives
from diorama.codebase.workspace import Workspace, WorkspaceError
from diorama.tools import ToolContext, default_registry
from diorama.tools.code import (
    EditFileArgs,
    ListDirArgs,
    ReadFileArgs,
    RunCommandArgs,
    SearchCodeArgs,
    VisualizeCodebaseArgs,
    WriteFileArgs,
    _edit_file,
    _list_dir,
    _read_file,
    _run_command,
    _search_code,
    _visualize_codebase,
    _write_file,
)


def make_repo(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("")
    (tmp_path / "pkg" / "core.py").write_text(
        "from pkg.util import helper\n\n\nclass Widget:\n    def render(self):\n        return helper()\n\n\ndef build():\n    return Widget()\n"
    )
    (tmp_path / "pkg" / "util.py").write_text("def helper():\n    return 42\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_core.py").write_text("def test_build():\n    assert True\n")
    (tmp_path / "web").mkdir()
    (tmp_path / "web" / "index.ts").write_text("import { thing } from './thing'\nexport function main() {}\n")
    (tmp_path / "web" / "thing.ts").write_text("export const thing = 1\n")
    (tmp_path / ".gitignore").write_text("*.log\nbuild/\n")
    (tmp_path / "noise.log").write_text("ignore me\n")
    return tmp_path


def make_context(workspace: Workspace) -> ToolContext:
    return ToolContext(session_id="s1", scene=[], files={}, workspace=workspace)


# --------------------------------------------------------------------------- #
# Workspace
# --------------------------------------------------------------------------- #


def test_workspace_rejects_escapes(tmp_path):
    workspace = Workspace(make_repo(tmp_path))
    with pytest.raises(WorkspaceError):
        workspace.resolve("../outside.txt")
    with pytest.raises(WorkspaceError):
        workspace.resolve("/etc/passwd")


def test_workspace_respects_gitignore_and_binary(tmp_path):
    workspace = Workspace(make_repo(tmp_path))
    listing = workspace.list_dir(".", recursive=True)
    paths = {entry["path"] for entry in listing["entries"]}
    assert "pkg/core.py" in paths
    assert "noise.log" not in paths


def test_workspace_read_write_edit_roundtrip(tmp_path):
    workspace = Workspace(make_repo(tmp_path))
    result = workspace.read_file("pkg/util.py")
    assert "helper" in result["content"]

    write = workspace.write_file("pkg/new.py", "VALUE = 1\n")
    assert write["bytesWritten"] > 0

    edit = workspace.edit_file("pkg/new.py", [{"oldString": "VALUE = 1", "newString": "VALUE = 2"}])
    assert "VALUE = 2" in edit["diff"]
    assert workspace.read_file("pkg/new.py")["content"].endswith("VALUE = 2")


def test_workspace_search_finds_matches(tmp_path):
    workspace = Workspace(make_repo(tmp_path))
    result = workspace.search("def build", glob="*.py")
    assert result["matchCount"] == 1
    assert result["matches"][0]["path"] == "pkg/core.py"


def test_workspace_edit_requires_unique_match(tmp_path):
    workspace = Workspace(make_repo(tmp_path))
    workspace.write_file("dup.py", "x = 1\nx = 1\n")
    with pytest.raises(WorkspaceError, match="appears 2 times"):
        workspace.edit_file("dup.py", [{"oldString": "x = 1", "newString": "x = 2"}])


@pytest.mark.asyncio
async def test_workspace_run_command_captures_output(tmp_path):
    workspace = Workspace(make_repo(tmp_path))
    result = await workspace.run("echo hello")
    assert result["exitCode"] == 0
    assert "hello" in result["stdout"]


@pytest.mark.asyncio
async def test_workspace_run_command_can_be_disabled(tmp_path):
    workspace = Workspace(make_repo(tmp_path), allow_exec=False)
    with pytest.raises(WorkspaceError, match="disabled"):
        await workspace.run("echo hi")


# --------------------------------------------------------------------------- #
# Indexer
# --------------------------------------------------------------------------- #


def test_indexer_extracts_symbols_and_imports(tmp_path):
    graph = build_code_graph(Workspace(make_repo(tmp_path)))
    by_path = {node.path: node for node in graph.nodes}

    core = by_path["pkg/core.py"]
    assert core.language == "python"
    assert "pkg.util" in core.imports
    assert {symbol.name for symbol in core.symbols} >= {"Widget", "Widget.render", "build"}

    targets = {(edge.source, edge.target) for edge in graph.edges}
    assert ("file:pkg/core.py", "file:pkg/util.py") in targets


def test_indexer_resolves_typescript_relative_imports(tmp_path):
    graph = build_code_graph(Workspace(make_repo(tmp_path)))
    targets = {(edge.source, edge.target) for edge in graph.edges}
    assert ("file:web/index.ts", "file:web/thing.ts") in targets


def test_indexer_can_exclude_tests(tmp_path):
    graph = build_code_graph(Workspace(make_repo(tmp_path)), include_tests=False)
    assert all(not node.is_test for node in graph.nodes)


def test_layered_layout_is_deterministic(tmp_path):
    graph = build_code_graph(Workspace(make_repo(tmp_path)))
    assert graph.layered_layout() == graph.layered_layout()


# --------------------------------------------------------------------------- #
# Visualization
# --------------------------------------------------------------------------- #


def test_graph_to_primitives_produces_frames_and_cards(tmp_path):
    graph = build_code_graph(Workspace(make_repo(tmp_path)))
    primitives = graph_to_primitives(graph, title="Repo")
    kinds = [primitive.kind for primitive in primitives]
    assert kinds[0] == "heading"
    assert "frame" in kinds
    assert "card" in kinds
    card = next(p for p in primitives if p.kind == "card")
    assert card.title.endswith(".py") or card.title.endswith(".ts")


def test_graph_to_primitives_handles_empty_graph(tmp_path):
    (tmp_path / "README.md").write_text("nothing to index")
    graph = build_code_graph(Workspace(tmp_path))
    primitives = graph_to_primitives(graph)
    assert [p.kind for p in primitives] == ["heading"]


# --------------------------------------------------------------------------- #
# Code tools
# --------------------------------------------------------------------------- #


def test_registry_offers_code_tools_only_when_requested():
    assert "read_file" in {tool.name for tool in default_registry(include_code=True)}
    assert "read_file" not in {tool.name for tool in default_registry(include_code=False)}


@pytest.mark.asyncio
async def test_code_tools_require_a_workspace():
    from diorama.tools.base import ToolError

    context = ToolContext(session_id="s1", scene=[], files={})
    with pytest.raises(ToolError):
        await _read_file(ReadFileArgs(path="x.py"), context)


@pytest.mark.asyncio
async def test_read_and_list_tools(tmp_path):
    context = make_context(Workspace(make_repo(tmp_path)))
    listing = await _list_dir(ListDirArgs(path="pkg"), context)
    assert {entry["name"] for entry in listing.content["entries"]} >= {"core.py", "util.py"}

    read = await _read_file(ReadFileArgs(path="pkg/util.py"), context)
    assert read.content["totalLines"] >= 2


@pytest.mark.asyncio
async def test_search_tool(tmp_path):
    context = make_context(Workspace(make_repo(tmp_path)))
    result = await _search_code(SearchCodeArgs(pattern="helper", glob="*.py"), context)
    assert result.content["matchCount"] >= 1


@pytest.mark.asyncio
async def test_write_and_edit_tools_record_changes(tmp_path):
    context = make_context(Workspace(make_repo(tmp_path)))
    await _write_file(WriteFileArgs(path="pkg/new.py", content="A = 1\n"), context)
    await _edit_file(
        EditFileArgs.model_validate({"path": "pkg/new.py", "edits": [{"oldString": "A = 1", "newString": "A = 2"}]}),
        context,
    )
    assert [change["path"] for change in context.file_changes] == ["pkg/new.py", "pkg/new.py"]
    assert "A = 1" in context.file_changes[1]["before"]


@pytest.mark.asyncio
async def test_run_command_tool(tmp_path):
    context = make_context(Workspace(make_repo(tmp_path)))
    result = await _run_command(RunCommandArgs(command="echo ok"), context)
    assert result.content["exitCode"] == 0


@pytest.mark.asyncio
async def test_visualize_tool_emits_canvas_patch(tmp_path):
    context = make_context(Workspace(make_repo(tmp_path)))
    result = await _visualize_codebase(VisualizeCodebaseArgs(title="Repo"), context)
    assert result.patch is not None
    assert any(primitive.kind == "card" for primitive in result.patch.primitives)
