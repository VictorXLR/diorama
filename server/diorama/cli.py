"""Command-line interface for the Diorama harness.

    diorama index [PATH]                 - print a structural summary of a repo
    diorama analyze [PATH] -o out.json   - export the codebase map as .excalidraw
    diorama dev [PATH]                   - start the server bound to PATH
    diorama serve                        - start the server with no repository bound

Run as ``python -m diorama.cli ...`` or, after installation, ``diorama ...``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from diorama.codebase.indexer import build_code_graph
from diorama.codebase.visualize import graph_to_primitives
from diorama.codebase.workspace import Workspace, WorkspaceError
from diorama.knowledge import KnowledgeBase, load_knowledge_base
from diorama.models.canvas import CanvasPatch, apply_canvas_patch
from diorama.queries import QueryError, run_query


def _open_workspace(path: str) -> Workspace:
    try:
        return Workspace(Path(path))
    except WorkspaceError as exc:
        raise SystemExit(f"error: {exc}") from exc


def _resolve_root(path: Optional[str]) -> str:
    return str(Path(path or ".").expanduser().resolve())


def cmd_index(args: argparse.Namespace) -> int:
    workspace = _open_workspace(_resolve_root(args.path))
    graph = build_code_graph(workspace, include_tests=not args.no_tests)
    if args.json:
        print(json.dumps(graph.to_summary(max_nodes=args.max_nodes), indent=2, ensure_ascii=False))
        return 0

    print(f"# {workspace.root}")
    print(f"{len(graph.nodes)} files indexed ({graph.total_files} source files), {len(graph.edges)} import edges")
    print("languages:", ", ".join(f"{name}={count}" for name, count in graph.languages.items()) or "none")
    print()
    for node in graph.nodes[: args.max_nodes]:
        symbols = ", ".join(symbol.name for symbol in node.symbols[:4])
        suffix = f"  [{symbols}]" if symbols else ""
        print(f"  {node.path}  ({node.loc} loc){suffix}")
    if len(graph.nodes) > args.max_nodes:
        print(f"  … and {len(graph.nodes) - args.max_nodes} more")
    return 0


def cmd_analyze(args: argparse.Namespace) -> int:
    workspace = _open_workspace(_resolve_root(args.path))
    graph = build_code_graph(workspace, include_tests=not args.no_tests)
    primitives = graph_to_primitives(
        graph,
        title=args.title or f"Codebase map · {workspace.root.name}",
        max_nodes=args.max_nodes,
        group_depth=args.group_depth,
        include_edges=not args.no_edges,
    )
    elements = apply_canvas_patch([], CanvasPatch(primitives=primitives), theme="light")
    scene = {"type": "excalidraw", "version": 2, "source": "diorama", "elements": elements, "appState": {}, "files": {}}
    out = Path(args.output)
    out.write_text(json.dumps(scene, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {len(elements)} elements ({len(primitives)} primitives) to {out}")
    return 0


def cmd_dev(args: argparse.Namespace) -> int:
    root = _resolve_root(args.path)
    os.environ["DIORAMA_WORKSPACE"] = root
    if args.reload:
        os.environ["DIORAMA_RELOAD"] = "on"
    print(f"Binding workspace: {root}")
    return _run_server()


def cmd_serve(args: argparse.Namespace) -> int:
    return _run_server()


def _knowledge_for_cli() -> KnowledgeBase:
    """The CLI uses the same knowledge base as the server."""
    from diorama.config import get_settings, reset_settings_cache

    reset_settings_cache()
    return load_knowledge_base(get_settings().knowledge_path)


def cmd_query(args: argparse.Namespace) -> int:
    """Run a structured analysis through the knowledge base.

    Shares the exact code path with the server's /api/query endpoints, so the
    CLI and the web UI are one system over one knowledge base.
    """
    workspace = _open_workspace(_resolve_root(args.path))
    knowledge = _knowledge_for_cli()
    try:
        result = run_query(
            workspace, args.kind, knowledge, table=args.table, force=args.force
        )
    except QueryError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    repo = result["repo"]
    origin = f" ({repo['git_remote']})" if repo.get("git_remote") else ""
    print(f"# {repo['name']}{origin}")
    print(f"kind: {result['kind']}  cached: {result['cached']}")
    changed = result.get("changedSinceLastIndex") or {}
    total_changed = sum(len(changed.get(key, [])) for key in ("added", "removed", "changed"))
    print(f"changed since last index: {total_changed} file(s)")
    print()
    _print_query_summary(result)
    return 0


def _print_query_summary(result: Dict[str, Any]) -> None:
    payload = result["payload"]
    kind = result["kind"]
    if kind == "graph":
        print(f"{payload.get('totalFiles', '?')} source files, {payload.get('nodeCount', '?')} indexed, "
              f"{payload.get('edgeCount', '?')} import edges")
        for node in payload.get("nodes", [])[:20]:
            print(f"  {node.get('path', '')}  ({node.get('loc', '?')} loc)")
        return
    if kind == "connectivity":
        for connector in payload.get("connectors", []):
            print(f"connector: {connector.get('name')} ({connector.get('category')})")
        for table in payload.get("tables", []):
            ops = ", ".join(sorted(table.get("operations", []))) or "read"
            print(f"table: {table.get('name')}  [{ops}]  columns: {', '.join(table.get('columns', [])[:8])}")
        for endpoint in payload.get("endpoints", []):
            print(f"endpoint: {endpoint.get('method')} {endpoint.get('path')}  ({endpoint.get('file')})")
        if not payload.get("connectors") and not payload.get("endpoints"):
            print("no external connectors or HTTP endpoints detected")
        return
    if kind == "architecture":
        for component in payload.get("components", []):
            print(f"component: {component.get('label')}  [{component.get('role')}]  "
                  f"{len(component.get('files', []))} files  packages: {', '.join(component.get('packages', [])[:6])}")
        for edge in payload.get("edges", []):
            print(f"dependency: {edge.get('source')} -> {edge.get('target')}  (weight {edge.get('weight')})")
        environment = payload.get("environment") or {}
        if environment.get("runtime"):
            print(f"runtime: {', '.join(environment['runtime'][:6])}")
        return
    if kind == "table":
        ops = ", ".join(sorted(payload.get("operations", []))) or "read"
        print(f"table: {payload.get('name')}  [{ops}]")
        print(f"columns: {', '.join(payload.get('columns', []))}")
        for path in payload.get("files", []):
            print(f"  touched by {path}")
        return
    if kind == "changes":
        total = sum(len(payload.get(key, [])) for key in ("added", "removed", "changed"))
        for key in ("added", "removed", "changed"):
            for path in payload.get(key, []):
                print(f"{key}: {path}")
        if total == 0:
            print("no changes since the last indexed state")
        return
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def cmd_kb(args: argparse.Namespace) -> int:
    """Inspect the durable knowledge base from the shell."""
    knowledge = _knowledge_for_cli()
    if not knowledge.enabled:
        print("Knowledge base is disabled (DIORAMA_KB=off).")
        return 1
    if args.kb_command == "list":
        repos = knowledge.list_repositories()
        if not repos:
            print("No repositories indexed yet. Run `diorama query graph PATH` or bind one in the UI.")
            return 0
        for repo in repos:
            remote = repo.get("git_remote") or "no remote"
            print(f"{repo['repo_id']}  {repo['name']}  analyses={repo['analysis_count']}  {repo['root']}  [{remote}]")
        return 0
    if args.kb_command == "show":
        repo = knowledge.find_repository_by_root(_resolve_root(args.path))
        if repo is None:
            print(f"error: no knowledge base entry for {_resolve_root(args.path)}", file=sys.stderr)
            return 1
        print(f"{repo['name']}  ({repo['root']})")
        print(f"repo_id: {repo['repo_id']}")
        print(f"remote:  {repo.get('git_remote') or 'none'}")
        print(f"commit:  {repo.get('last_commit') or 'unknown'}")
        print()
        for analysis in knowledge.list_analyses(repo_id=repo["repo_id"], limit=args.limit):
            stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(analysis["created_at"]))
            print(f"  {stamp}  {analysis['kind']}  commit={analysis.get('commit_hash') or 'n/a'}")
        return 0
    if args.kb_command == "analyses":
        for analysis in knowledge.list_analyses(limit=args.limit):
            stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(analysis["created_at"]))
            print(f"{stamp}  {analysis['repo_id']}  {analysis['kind']}")
        return 0
    print(f"error: unknown kb command {args.kb_command!r}", file=sys.stderr)
    return 1


def _run_server() -> int:
    import uvicorn

    from diorama.config import get_settings, reset_settings_cache

    reset_settings_cache()
    settings = get_settings()
    print(f"Serving on http://{settings.host}:{settings.port}")
    if settings.frontend_enabled:
        print(f"Frontend:  http://{settings.host}:{settings.port}/  (from {settings.web_dist})")
    else:
        print(
            "Frontend not built — run `bun run build` in web/ (or use `bun run dev` on :5173). "
            f"Looked in {settings.web_dist}"
        )
    uvicorn.run("diorama.app:app", host=settings.host, port=settings.port, reload=settings.reload)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="diorama", description="Diorama codebase harness")
    sub = parser.add_subparsers(dest="command", required=True)

    index = sub.add_parser("index", help="Print a structural summary of a repository")
    index.add_argument("path", nargs="?", default=".")
    index.add_argument("--json", action="store_true", help="Emit the full graph as JSON")
    index.add_argument("--no-tests", action="store_true", help="Skip test files")
    index.add_argument("--max-nodes", type=int, default=40)
    index.set_defaults(func=cmd_index)

    analyze = sub.add_parser("analyze", help="Export the codebase map as an .excalidraw scene")
    analyze.add_argument("path", nargs="?", default=".")
    analyze.add_argument("-o", "--output", default="codebase.excalidraw")
    analyze.add_argument("--title", default=None)
    analyze.add_argument("--group-depth", type=int, default=1)
    analyze.add_argument("--max-nodes", type=int, default=60)
    analyze.add_argument("--no-edges", action="store_true", help="Do not draw import arrows")
    analyze.add_argument("--no-tests", action="store_true")
    analyze.set_defaults(func=cmd_analyze)

    dev = sub.add_parser("dev", help="Start the server bound to a repository")
    dev.add_argument("path", nargs="?", default=".")
    dev.add_argument("--reload", action="store_true")
    dev.set_defaults(func=cmd_dev)

    serve = sub.add_parser("serve", help="Start the server with no repository bound")
    serve.set_defaults(func=cmd_serve)

    query = sub.add_parser(
        "query", help="Run a structured analysis through the knowledge base"
    )
    query.add_argument("kind", choices=("graph", "connectivity", "architecture", "table", "changes"))
    query.add_argument("path", nargs="?", default=".")
    query.add_argument("--table", default=None, help="Table name for the 'table' kind")
    query.add_argument("--force", action="store_true", help="Recompute even if cached")
    query.add_argument("--json", action="store_true", help="Emit the full result as JSON")
    query.set_defaults(func=cmd_query)

    kb = sub.add_parser("kb", help="Inspect the knowledge base")
    kb_sub = kb.add_subparsers(dest="kb_command")
    kb_list = kb_sub.add_parser("list", help="List indexed repositories")
    kb_list.set_defaults(func=cmd_kb, kb_command="list")
    kb_show = kb_sub.add_parser("show", help="Show a repository's analysis history")
    kb_show.add_argument("path", nargs="?", default=".")
    kb_show.add_argument("--limit", type=int, default=25)
    kb_show.set_defaults(func=cmd_kb, kb_command="show")
    kb_analyses = kb_sub.add_parser("analyses", help="List recent analyses across all repos")
    kb_analyses.add_argument("--limit", type=int, default=25)
    kb_analyses.set_defaults(func=cmd_kb, kb_command="analyses")

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
