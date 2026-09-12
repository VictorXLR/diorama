"""Agent tools (canvas primitives, assets such as real maps, and turn control)."""

from diorama.tools.assets import ASSET_TOOLS
from diorama.tools.base import Tool, ToolContext, ToolError, ToolRegistry, ToolResult
from diorama.tools.canvas import CANVAS_TOOLS


def default_registry() -> ToolRegistry:
    return ToolRegistry([*CANVAS_TOOLS, *ASSET_TOOLS])


__all__ = [
    "Tool",
    "ToolContext",
    "ToolError",
    "ToolRegistry",
    "ToolResult",
    "default_registry",
]
