"""Deterministic queries over a workspace, answered through the knowledge base.

The web UI and the CLI both call ``run_query``; the agent keeps its tools for
freeform synthesis.  Results are cached in the knowledge base keyed by a
content signature, so an unchanged repo is answered from memory and every
analysis is preserved as history.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from diorama.codebase.architecture import build_architecture
from diorama.codebase.connectivity import build_connectivity_map
from diorama.codebase.indexer import build_code_graph
from diorama.codebase.workspace import Workspace
from diorama.knowledge import (
    KnowledgeBase,
    compute_file_state,
    diff_file_states,
    identify_repository,
    signature_for,
)

logger = logging.getLogger("diorama.queries")

QUERY_KINDS = ("graph", "connectivity", "architecture", "table", "changes")


class QueryError(RuntimeError):
    """Raised for unknown query kinds or missing prerequisites."""


def _compute_payload(workspace: Workspace, kind: str) -> Dict[str, Any]:
    """Run the requested analysis from scratch."""
    graph = build_code_graph(workspace)
    if kind == "graph":
        return graph.to_summary(max_nodes=500)
    if kind == "connectivity":
        return build_connectivity_map(workspace, graph).to_summary()
    if kind == "architecture":
        return build_architecture(workspace, graph).to_summary()
    raise QueryError(f"Unknown query kind: {kind}")


def _zoom_table(connectivity: Dict[str, Any], name: str) -> Dict[str, Any]:
    for table in connectivity.get("tables", []):
        if table.get("name") == name:
            return table
    raise QueryError(f"No table named {name!r} was found in the connectivity map.")


def run_query(
    workspace: Workspace,
    kind: str,
    knowledge: KnowledgeBase,
    *,
    table: Optional[str] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """Answer a structured query, using and growing the knowledge base.

    Returns a dict with the repository identity, whether the payload came from
    the cache, what changed since the last indexed state, and the payload
    itself.  ``table`` zooms into a single database table via connectivity.
    """
    if kind not in QUERY_KINDS:
        raise QueryError(f"Unknown query kind: {kind!r}. Expected one of {', '.join(QUERY_KINDS)}.")
    if kind == "table" and not table:
        raise QueryError("The 'table' query requires a table name.")

    identity = identify_repository(Path(workspace.root))
    repo_id = identity["repo_id"]

    current_state = compute_file_state(Path(workspace.root), list(workspace.iter_files()))
    signature = signature_for(current_state)
    previous_state = knowledge.stored_file_state(repo_id)
    changed = diff_file_states(previous_state, current_state) if previous_state else {
        "added": [], "removed": [], "changed": [],
    }
    if not previous_state:
        changed = {"added": sorted(current_state), "removed": [], "changed": []}

    knowledge.upsert_repository(
        repo_id,
        identity["root"],
        identity["name"],
        git_remote=identity["git_remote"],
        commit=identity["commit"],
        signature=signature,
    )

    if kind == "changes":
        knowledge.store_file_state(repo_id, current_state)
        return {
            "kind": "changes",
            "repo": identity,
            "signature": signature,
            "cached": False,
            "changedSinceLastIndex": changed,
            "payload": changed,
        }

    cached = False
    record = None
    # A table zoom is a projection of the connectivity analysis, so it shares
    # that cache entry rather than getting its own.
    cache_kind = "connectivity" if kind == "table" else kind
    if not force:
        record = knowledge.latest_analysis(repo_id, cache_kind, signature=signature)
    if record is not None:
        payload = record["payload"]
        cached = True
    else:
        payload = _compute_payload(workspace, cache_kind)
        knowledge.record_analysis(
            repo_id, cache_kind, payload, commit=identity["commit"], signature=signature
        )
        knowledge.store_file_state(repo_id, current_state)

    if kind == "table":
        payload = _zoom_table(payload, table or "")

    return {
        "kind": kind,
        "repo": identity,
        "signature": signature,
        "cached": cached,
        "changedSinceLastIndex": changed,
        "payload": payload,
    }


def query_table_names(payload: Dict[str, Any]) -> List[str]:
    return [table.get("name", "") for table in payload.get("tables", [])]
