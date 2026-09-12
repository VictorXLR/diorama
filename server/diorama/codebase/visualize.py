"""Turn a :class:`CodeGraph` into canvas primitives with a deterministic layout.

The layout is intentionally simple and reproducible: files are grouped into
directory bands, arranged in a grid inside a titled ``frame``, and their import
relationships are drawn as ``route`` arrows between the file cards.  Cards carry
``customData`` (via the primitive id) so the UI can link a shape back to a file.
"""

from __future__ import annotations

import math
from typing import Dict, List, Sequence, Tuple

from diorama.codebase.indexer import CodeGraph, CodeNode
from diorama.visual.primitives import (
    CardPrimitive,
    FramePrimitive,
    HeadingPrimitive,
    LegendItem,
    LegendPrimitive,
    Primitive,
    RoutePrimitive,
)

CARD_WIDTH = 320
CARD_HEIGHT = 168
CARD_GAP = 40
FRAME_PAD = 40
FRAME_TITLE = 56
FRAME_GAP = 80
MAX_COLUMNS = 4
MAX_BODY_LINES = 3
MAX_SYMBOLS = 3

ACCENT_BY_LANGUAGE: Dict[str, str] = {
    "python": "indigo",
    "typescript": "sky",
    "javascript": "amber",
    "go": "emerald",
    "rust": "coral",
    "java": "violet",
    "ruby": "rose",
    "config": "slate",
}
DEFAULT_ACCENT = "slate"


def _accent(node: CodeNode) -> str:
    if node.is_test:
        return "slate"
    return ACCENT_BY_LANGUAGE.get(node.language, DEFAULT_ACCENT)


def _sanitize(value: str) -> str:
    """Primitive ids end up as Excalidraw element ids; keep them conservative."""
    return "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in value)


def _group_key(path: str, depth: int = 1) -> str:
    parts = path.split("/")
    if len(parts) <= 1:
        return "."
    return "/".join(parts[:depth]) if len(parts) > depth else "/".join(parts[:-1]) or "."


def _body_lines(node: CodeNode) -> List[str]:
    lines = [f"{node.loc} lines · {node.language}"]
    if node.imports:
        lines.append(f"{len(node.imports)} imports")
    symbol_names = [symbol.name for symbol in node.symbols if symbol.kind in {"class", "function", "interface", "type"}]
    if symbol_names:
        shown = symbol_names[:MAX_SYMBOLS]
        extra = len(symbol_names) - len(shown)
        text = ", ".join(shown) + (f" +{extra}" if extra else "")
        lines.append(text)
    return lines[:MAX_BODY_LINES]


def _group_nodes(nodes: Sequence[CodeNode], *, depth: int) -> List[Tuple[str, List[CodeNode]]]:
    groups: Dict[str, List[CodeNode]] = {}
    for node in nodes:
        groups.setdefault(_group_key(node.path, depth), []).append(node)
    return sorted(groups.items(), key=lambda item: (item[0] != ".", item[0]))


def graph_to_primitives(
    graph: CodeGraph,
    *,
    title: str = "Codebase map",
    max_nodes: int = 60,
    group_depth: int = 1,
    include_edges: bool = True,
    include_legend: bool = True,
) -> List[Primitive]:
    """Lay out ``graph`` as frames (directories), cards (files) and routes (imports)."""
    nodes = graph.nodes[:max_nodes]
    if not nodes:
        return [
            HeadingPrimitive(
                kind="heading",
                id="codebase-heading",
                text=title,
                subtitle="No source files were indexed.",
                x=0,
                y=0,
            )
        ]

    included = {node.id for node in nodes}
    primitives: List[Primitive] = []
    languages_present: List[str] = []

    heading = HeadingPrimitive(
        kind="heading",
        id="codebase-heading",
        text=title,
        subtitle=f"{len(nodes)} of {graph.total_files} files · {len(graph.edges)} imports",
        x=0,
        y=0,
        size="xl",
    )
    primitives.append(heading)
    cursor_y = 120.0

    for group_name, members in _group_nodes(nodes, depth=group_depth):
        members = sorted(members, key=lambda node: node.path)
        columns = min(MAX_COLUMNS, max(1, math.ceil(math.sqrt(len(members)))))
        rows = math.ceil(len(members) / columns)
        frame_width = columns * CARD_WIDTH + (columns - 1) * CARD_GAP + 2 * FRAME_PAD
        frame_height = FRAME_TITLE + rows * CARD_HEIGHT + (rows - 1) * CARD_GAP + FRAME_PAD
        frame_id = _sanitize(f"frame-{group_name}")
        primitives.append(
            FramePrimitive(
                kind="frame",
                id=frame_id,
                title=group_name,
                x=0,
                y=cursor_y,
                width=frame_width,
                height=frame_height,
            )
        )
        for index, node in enumerate(members):
            column = index % columns
            row = index // columns
            x = FRAME_PAD + column * (CARD_WIDTH + CARD_GAP)
            y = cursor_y + FRAME_TITLE + row * (CARD_HEIGHT + CARD_GAP)
            card_id = _sanitize(node.id)
            accent = _accent(node)
            if node.language not in languages_present:
                languages_present.append(node.language)
            primitives.append(
                CardPrimitive(
                    kind="card",
                    id=card_id,
                    frame=frame_id,
                    title=node.name,
                    body=_body_lines(node),
                    x=x,
                    y=y,
                    width=CARD_WIDTH,
                    accent=accent,
                )
            )
        cursor_y += frame_height + FRAME_GAP

    if include_edges:
        seen: set[Tuple[str, str]] = set()
        for edge in graph.edges:
            if edge.source not in included or edge.target not in included or edge.source == edge.target:
                continue
            key = (edge.source, edge.target)
            if key in seen:
                continue
            seen.add(key)
            primitives.append(
                RoutePrimitive.model_validate(
                    {
                        "kind": "route",
                        "id": _sanitize(f"import-{edge.source}-{edge.target}"),
                        "from": _sanitize(edge.source),
                        "to": _sanitize(edge.target),
                        "style": "dashed",
                        "accent": "slate",
                        "arrow": True,
                    }
                )
            )

    if include_legend and len(languages_present) > 1:
        primitives.append(
            LegendPrimitive(
                kind="legend",
                id="codebase-legend",
                title="Languages",
                items=[
                    LegendItem(label=language, accent=ACCENT_BY_LANGUAGE.get(language, DEFAULT_ACCENT))
                    for language in languages_present[:6]
                ],
                x=0,
                y=cursor_y,
            )
        )
    return primitives
