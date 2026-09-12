"""Agent tools (canvas primitives, assets such as real maps, codebase access, and turn control)."""

from diorama.tools.assets import ASSET_TOOLS
from diorama.tools.base import Tool, ToolContext, ToolError, ToolRegistry, ToolResult
from diorama.tools.canvas import CANVAS_TOOLS
from diorama.tools.code import CODE_TOOLS


def default_registry(*, include_code: bool = True) -> ToolRegistry:
    """Build the tool set. Code tools are only offered when a repo is bound."""
    tools = [*CANVAS_TOOLS, *ASSET_TOOLS]
    if include_code:
        tools.extend(CODE_TOOLS)
    return ToolRegistry(tools)


__all__ = [
    "Tool",
    "ToolContext",
    "ToolError",
    "ToolRegistry",
    "ToolResult",
    "default_registry",
]
