"""Backwards-compatible alias: the context agent is now the tool-loop whiteboard agent."""

from diorama.agents.tool_agent import ToolLoopAgent


class ContextAgent(ToolLoopAgent):
    """Live-model agent that turns user requests into whiteboard changes via tools."""


__all__ = ["ContextAgent"]
