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
from pathlib import Path
from typing import List, Optional

from diorama.codebase.indexer import build_code_graph
from diorama.codebase.visualize import graph_to_primitives
from diorama.codebase.workspace import Workspace, WorkspaceError
from diorama.models.canvas import CanvasPatch, apply_canvas_patch


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


def _run_server() -> int:
    import uvicorn

    from diorama.config import get_settings, reset_settings_cache

    reset_settings_cache()
    settings = get_settings()
    print(f"Serving on http://{settings.host}:{settings.port}")
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

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
