"""Tool contract for the agent loop.

A tool receives validated arguments plus the live :class:`ToolContext` and returns a
:class:`ToolResult`.  Canvas changes are expressed as a :class:`CanvasPatch` so the
agent applies them atomically and streams the result to the client.  Tools are
provider-agnostic: the same definitions are exposed via native function calling or
rendered into the prompt for models without tool support.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Type

from pydantic import BaseModel, ValidationError

from diorama.codebase.workspace import Workspace
from diorama.models.canvas import CanvasFile, CanvasPatch


class ToolError(RuntimeError):
    """A recoverable tool failure that is reported back to the model."""


@dataclass
class ToolContext:
    """Mutable per-turn state shared by all tool invocations."""

    session_id: str
    scene: List[Dict[str, Any]]
    files: Dict[str, CanvasFile]
    theme: str = "light"
    selected_element_ids: List[str] = field(default_factory=list)
    viewport: Optional[Dict[str, float]] = None
    workspace_context: Dict[str, Any] = field(default_factory=dict)
    workspace: Optional[Workspace] = None
    """Confined view of the target repository, or None when no repo is bound."""

    file_changes: List[Dict[str, Any]] = field(default_factory=list)
    """Files touched this turn, for diffing and rollback: {path, before, after, diff}."""

    @property
    def known_file_ids(self) -> set[str]:
        return set(self.files.keys())

    def require_workspace(self) -> Workspace:
        if self.workspace is None:
            raise ToolError(
                "No repository is bound to this session. Start the server with a workspace "
                "root (DIORAMA_WORKSPACE or `diorama dev <path>`) to use code tools."
            )
        return self.workspace


@dataclass
class ToolResult:
    """Outcome of a tool call."""

    content: Any
    """JSON-serialisable payload returned to the model."""
    patch: Optional[CanvasPatch] = None
    summary: str = ""
    """Short human-readable description streamed to the UI."""
    final: bool = False
    """True when the tool ends the turn (e.g. ``finish``)."""

    def content_text(self) -> str:
        if isinstance(self.content, str):
            return self.content
        return json.dumps(self.content, ensure_ascii=False, default=str)


ToolHandler = Callable[[BaseModel, ToolContext], Awaitable[ToolResult]]


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    args_model: Type[BaseModel]
    handler: ToolHandler
    mutates_canvas: bool = False

    def schema(self) -> Dict[str, Any]:
        """OpenAI-style function schema."""
        params = self.args_model.model_json_schema(by_alias=True)
        params.pop("title", None)
        _strip_titles(params)
        return {
            "type": "function",
            "function": {"name": self.name, "description": self.description, "parameters": params},
        }

    async def run(self, arguments: Dict[str, Any], context: ToolContext) -> ToolResult:
        if "__invalid_json__" in arguments:
            raise ToolError("Tool arguments were not valid JSON; resend them as a JSON object.")
        try:
            args = self.args_model.model_validate(arguments)
        except ValidationError as exc:
            raise ToolError(f"Invalid arguments for {self.name}: {_compact_validation_error(exc)}") from exc
        return await self.handler(args, context)


def _strip_titles(schema: Any) -> None:
    """Pydantic adds ``title`` everywhere; providers ignore it, but it bloats the prompt."""
    if isinstance(schema, dict):
        schema.pop("title", None)
        for value in schema.values():
            _strip_titles(value)
    elif isinstance(schema, list):
        for value in schema:
            _strip_titles(value)


def _compact_validation_error(exc: ValidationError, limit: int = 6) -> str:
    parts = []
    for error in exc.errors()[:limit]:
        location = ".".join(str(item) for item in error.get("loc", ()))
        parts.append(f"{location}: {error.get('msg')}")
    more = len(exc.errors()) - limit
    if more > 0:
        parts.append(f"(+{more} more)")
    return "; ".join(parts)


class ToolRegistry:
    def __init__(self, tools: Optional[List[Tool]] = None) -> None:
        self._tools: Dict[str, Tool] = {}
        for tool in tools or []:
            self.register(tool)

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Duplicate tool name: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def __iter__(self):
        return iter(self._tools.values())

    def __len__(self) -> int:
        return len(self._tools)

    def schemas(self) -> List[Dict[str, Any]]:
        return [tool.schema() for tool in self._tools.values()]

    def prompt_catalog(self) -> str:
        """Textual tool catalogue for models without native tool calling."""
        lines = []
        for tool in self._tools.values():
            params = tool.schema()["function"]["parameters"]
            lines.append(f"### {tool.name}\n{tool.description}\nArguments JSON schema: {json.dumps(params)}")
        return "\n\n".join(lines)
