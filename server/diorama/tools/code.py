"""Code tools: read, search, write, edit, and run commands inside the workspace.

These are what make Diorama a *codebase* harness rather than only a whiteboard.
Every operation goes through :class:`~diorama.codebase.workspace.Workspace`, so
the agent can only ever touch files under the configured repository root.

File mutations are reported back in the tool result (including a unified diff)
and recorded on the :class:`ToolContext` so a turn can be rolled back.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from diorama.codebase.indexer import build_code_graph
from diorama.codebase.visualize import graph_to_primitives
from diorama.codebase.workspace import WorkspaceError
from diorama.models.canvas import CanvasPatch
from diorama.tools.base import Tool, ToolContext, ToolError, ToolResult


def _record_change(context: ToolContext, change: Dict[str, Any]) -> None:
    context.file_changes.append(change)


# --------------------------------------------------------------------------- #
# Read / inspect
# --------------------------------------------------------------------------- #


class ListDirArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    path: str = Field(default=".", description="Directory path relative to the repository root.")
    recursive: bool = Field(default=False, description="Walk the whole subtree (ignores respected).")
    max_entries: int = Field(default=2000, alias="maxEntries", ge=1, le=20000)


class ReadFileArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    path: str = Field(description="File path relative to the repository root.")
    start_line: Optional[int] = Field(default=None, alias="startLine", ge=1, description="1-based first line.")
    end_line: Optional[int] = Field(default=None, alias="endLine", ge=1, description="1-based last line (inclusive).")


class SearchCodeArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    pattern: str = Field(description="Regular expression to search for.")
    glob: Optional[str] = Field(default=None, description="Only search files matching this glob, e.g. '*.py'.")
    case_sensitive: bool = Field(default=True, alias="caseSensitive")
    context_lines: int = Field(default=0, alias="contextLines", ge=0, le=5)
    max_results: int = Field(default=100, alias="maxResults", ge=1, le=500)


class IndexCodebaseArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    include_tests: bool = Field(default=True, alias="includeTests")
    languages: Optional[List[str]] = Field(default=None, description="Restrict to these languages, e.g. ['python'].")
    max_files: int = Field(default=600, alias="maxFiles", ge=1, le=5000)
    max_nodes: int = Field(default=200, alias="maxNodes", ge=1, le=1000, description="Cap nodes in the returned summary.")


class VisualizeCodebaseArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    title: Optional[str] = Field(default=None, description="Heading for the board.")
    max_nodes: int = Field(default=60, alias="maxNodes", ge=1, le=200)
    group_depth: int = Field(default=1, alias="groupDepth", ge=1, le=3, description="Directory depth used to group files into frames.")
    include_edges: bool = Field(default=True, alias="includeEdges", description="Draw import arrows between files.")
    include_tests: bool = Field(default=True, alias="includeTests")
    languages: Optional[List[str]] = None


# --------------------------------------------------------------------------- #
# Write / edit
# --------------------------------------------------------------------------- #


class WriteFileArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    path: str = Field(description="File path relative to the repository root.")
    content: str = Field(description="Full new contents of the file.")
    overwrite: bool = Field(default=True, description="Must be true to replace an existing file.")


class FileEdit(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    old_string: str = Field(alias="oldString", description="Exact text to replace (include surrounding context).")
    new_string: str = Field(alias="newString", description="Replacement text.")
    replace_all: bool = Field(default=False, alias="replaceAll")


class EditFileArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    path: str = Field(description="File path relative to the repository root.")
    edits: List[FileEdit] = Field(min_length=1, description="One or more exact-string replacements.")


class RunCommandArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    command: str = Field(description="Shell command to run (e.g. 'pytest -q', 'bun run build').")
    cwd: str = Field(default=".", description="Working directory relative to the repository root.")
    timeout: Optional[float] = Field(default=None, ge=1, le=1800, description="Seconds before the command is killed.")


# --------------------------------------------------------------------------- #
# Handlers
# --------------------------------------------------------------------------- #


async def _list_dir(args: ListDirArgs, context: ToolContext) -> ToolResult:
    workspace = context.require_workspace()
    try:
        result = workspace.list_dir(args.path, recursive=args.recursive, max_entries=args.max_entries)
    except WorkspaceError as exc:
        raise ToolError(str(exc)) from exc
    return ToolResult(content=result, summary=f"Listed {len(result['entries'])} entries in {result['path']}")


async def _read_file(args: ReadFileArgs, context: ToolContext) -> ToolResult:
    workspace = context.require_workspace()
    try:
        result = workspace.read_file(args.path, start_line=args.start_line, end_line=args.end_line)
    except WorkspaceError as exc:
        raise ToolError(str(exc)) from exc
    return ToolResult(
        content=result,
        summary=f"Read {result['path']} (lines {result['startLine']}-{result['endLine']} of {result['totalLines']})",
    )


async def _search_code(args: SearchCodeArgs, context: ToolContext) -> ToolResult:
    workspace = context.require_workspace()
    try:
        result = workspace.search(
            args.pattern,
            glob=args.glob,
            case_sensitive=args.case_sensitive,
            context_lines=args.context_lines,
            max_results=args.max_results,
        )
    except WorkspaceError as exc:
        raise ToolError(str(exc)) from exc
    return ToolResult(
        content=result,
        summary=f"Found {result['matchCount']} match{'es' if result['matchCount'] != 1 else ''} in {result['filesScanned']} files",
    )


async def _write_file(args: WriteFileArgs, context: ToolContext) -> ToolResult:
    workspace = context.require_workspace()
    try:
        target = workspace.resolve(args.path)
        existed = target.exists()
        if existed and not args.overwrite:
            raise ToolError(f"{args.path} already exists; set overwrite=true to replace it.")
        before = target.read_text(encoding="utf-8", errors="replace") if existed else ""
        result = workspace.write_file(args.path, args.content)
    except WorkspaceError as exc:
        raise ToolError(str(exc)) from exc
    _record_change(context, {"path": result["path"], "before": before, "after": args.content, "diff": result["diff"]})
    verb = "Updated" if existed else "Created"
    return ToolResult(content=result, summary=f"{verb} {result['path']} ({result['bytesWritten']} bytes)")


async def _edit_file(args: EditFileArgs, context: ToolContext) -> ToolResult:
    workspace = context.require_workspace()
    try:
        before = workspace.read_file(args.path)["content"]
        result = workspace.edit_file(args.path, [edit.model_dump(by_alias=True) for edit in args.edits])
    except WorkspaceError as exc:
        raise ToolError(str(exc)) from exc
    _record_change(
        context,
        {
            "path": result["path"],
            "before": _strip_line_numbers(before),
            "after": None,
            "diff": result["diff"],
        },
    )
    return ToolResult(
        content=result,
        summary=f"Edited {result['path']} ({result['editsApplied']} change{'s' if result['editsApplied'] != 1 else ''})",
    )


async def _run_command(args: RunCommandArgs, context: ToolContext) -> ToolResult:
    workspace = context.require_workspace()
    try:
        result = await workspace.run(args.command, cwd=args.cwd, timeout=args.timeout)
    except WorkspaceError as exc:
        raise ToolError(str(exc)) from exc
    status = "timed out" if result["timedOut"] else f"exit {result['exitCode']}"
    return ToolResult(content=result, summary=f"Ran `{args.command}` ({status})")


async def _index_codebase(args: IndexCodebaseArgs, context: ToolContext) -> ToolResult:
    workspace = context.require_workspace()
    graph = build_code_graph(
        workspace,
        max_files=args.max_files,
        include_tests=args.include_tests,
        languages=args.languages,
    )
    summary = graph.to_summary(max_nodes=args.max_nodes)
    return ToolResult(
        content=summary,
        summary=f"Indexed {len(graph.nodes)} files and {len(graph.edges)} imports",
    )


async def _visualize_codebase(args: VisualizeCodebaseArgs, context: ToolContext) -> ToolResult:
    workspace = context.require_workspace()
    graph = build_code_graph(workspace, include_tests=args.include_tests, languages=args.languages)
    primitives = graph_to_primitives(
        graph,
        title=args.title or f"Codebase map · {workspace.root.name}",
        max_nodes=args.max_nodes,
        group_depth=args.group_depth,
        include_edges=args.include_edges,
    )
    patch = CanvasPatch(primitives=primitives)
    return ToolResult(
        content={
            "drawnNodes": min(len(graph.nodes), args.max_nodes),
            "totalFiles": graph.total_files,
            "edges": len(graph.edges),
            "note": "Each card maps to a file path; use read_file to inspect one.",
        },
        patch=patch,
        summary=f"Mapped {min(len(graph.nodes), args.max_nodes)} files of the codebase",
    )


def _strip_line_numbers(numbered: str) -> str:
    lines = []
    for line in numbered.splitlines():
        _, _, text = line.partition("\t")
        lines.append(text)
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Registration
# --------------------------------------------------------------------------- #

LIST_DIR_TOOL = Tool(
    name="list_dir",
    description="List files and directories in the repository. Set recursive=true to walk a subtree (ignored and binary paths are skipped).",
    args_model=ListDirArgs,
    handler=_list_dir,
)

READ_FILE_TOOL = Tool(
    name="read_file",
    description="Read a text file from the repository. Output is line-numbered; use startLine/endLine to page through large files.",
    args_model=ReadFileArgs,
    handler=_read_file,
)

SEARCH_CODE_TOOL = Tool(
    name="search_code",
    description="Search the repository with a regular expression, optionally filtered by glob. Returns matching lines with file and line number.",
    args_model=SearchCodeArgs,
    handler=_search_code,
)

INDEX_CODEBASE_TOOL = Tool(
    name="index_codebase",
    description="Index the repository into a structural graph (files, symbols, imports). Use this to understand a codebase before editing it.",
    args_model=IndexCodebaseArgs,
    handler=_index_codebase,
)

VISUALIZE_CODEBASE_TOOL = Tool(
    name="visualize_codebase",
    description="Draw the repository's structure onto the board: one frame per directory, one card per file, arrows for imports. Use when the user asks to see or map the codebase.",
    args_model=VisualizeCodebaseArgs,
    handler=_visualize_codebase,
    mutates_canvas=True,
)

WRITE_FILE_TOOL = Tool(
    name="write_file",
    description="Create or fully replace a file. Prefer edit_file for small changes; this overwrites the whole file.",
    args_model=WriteFileArgs,
    handler=_write_file,
)

EDIT_FILE_TOOL = Tool(
    name="edit_file",
    description="Apply exact-string replacements to an existing file. Provide enough surrounding context for oldString to be unique. Returns a unified diff.",
    args_model=EditFileArgs,
    handler=_edit_file,
)

RUN_COMMAND_TOOL = Tool(
    name="run_command",
    description="Run a shell command in the repository (build, tests, linters). Returns stdout, stderr and the exit code so you can verify your changes.",
    args_model=RunCommandArgs,
    handler=_run_command,
)

CODE_TOOLS = [
    LIST_DIR_TOOL,
    READ_FILE_TOOL,
    SEARCH_CODE_TOOL,
    INDEX_CODEBASE_TOOL,
    VISUALIZE_CODEBASE_TOOL,
    WRITE_FILE_TOOL,
    EDIT_FILE_TOOL,
    RUN_COMMAND_TOOL,
]
