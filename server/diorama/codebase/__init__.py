"""Codebase-facing layer: safe filesystem access and structural indexing.

This package is what turns Diorama from a whiteboard agent into a codebase
harness.  Everything here is confined to a single configured workspace root so
the agent can only ever read or write inside the repository it was pointed at.
"""

from diorama.codebase.indexer import CodeEdge, CodeGraph, CodeNode, CodeSymbol, build_code_graph
from diorama.codebase.visualize import graph_to_primitives
from diorama.codebase.workspace import Workspace, WorkspaceError

__all__ = [
    "Workspace",
    "WorkspaceError",
    "CodeGraph",
    "CodeNode",
    "CodeEdge",
    "CodeSymbol",
    "build_code_graph",
    "graph_to_primitives",
]
