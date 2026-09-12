"""Canvas tools: draw with composition primitives, edit raw elements, inspect the scene."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from diorama.models.canvas import CanvasPatch, apply_canvas_patch
from diorama.tools.base import Tool, ToolContext, ToolError, ToolResult
from diorama.visual.primitives import Primitive, anchor_from_element


class DrawArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    primitives: List[Primitive] = Field(
        min_length=1,
        description="Composition primitives to add or replace. Re-using an id replaces that primitive.",
    )


class EditElementsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    upsert_elements: List[Dict[str, Any]] = Field(
        alias="upsertElements",
        min_length=1,
        description=(
            "Raw Excalidraw elements. For existing ids include ONLY the fields to change "
            "(e.g. {\"id\":\"sun\",\"x\":200}). New elements need id, type, x, y and geometry."
        ),
    )


class DeleteElementsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ids: List[str] = Field(min_length=1, description="Element ids or primitive ids to remove.")


class InspectSceneArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    ids: Optional[List[str]] = Field(default=None, description="Restrict to these element/primitive ids.")
    include_text: bool = Field(default=True, alias="includeText")


class FinishArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reply: str = Field(min_length=1, description="Concise chat reply for the user (markdown ok).")
    summary: str = Field(default="", description="One line describing what changed on the board.")
    suggestions: List[str] = Field(default_factory=list, max_length=4, description="Up to four follow-up prompts.")


class AskUserArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1)
    options: List[str] = Field(default_factory=list, max_length=4, description="Quick-reply choices.")


def _dry_run(patch: CanvasPatch, context: ToolContext) -> List[Dict[str, Any]]:
    try:
        return apply_canvas_patch(context.scene, patch, theme=context.theme, known_files=context.known_file_ids)
    except ValueError as exc:
        raise ToolError(str(exc)) from exc


def _describe_element(element: Dict[str, Any], include_text: bool) -> Dict[str, Any]:
    info: Dict[str, Any] = {"id": element["id"], "type": element["type"]}
    anchor = anchor_from_element(element)
    if anchor:
        info["box"] = [round(anchor.x), round(anchor.y), round(anchor.width), round(anchor.height)]
    if include_text and isinstance(element.get("text"), str):
        info["text"] = element["text"][:120]
    custom = element.get("customData") or {}
    if isinstance(custom, dict) and custom.get("primitive"):
        info["primitive"] = custom["primitive"]
        if custom.get("role") == "anchor" and isinstance(custom.get("spec"), dict):
            info["kind"] = custom["spec"].get("kind")
    if element.get("frameId"):
        info["frameId"] = element["frameId"]
    return info


def scene_overview(scene: List[Dict[str, Any]], *, ids: Optional[List[str]] = None, include_text: bool = True) -> Dict[str, Any]:
    """Compact scene description: primitives collapse to their anchor, raw elements are listed individually."""
    wanted = set(ids or [])
    primitives: List[Dict[str, Any]] = []
    raw: List[Dict[str, Any]] = []
    texts: Dict[str, List[str]] = {}
    for element in scene:
        custom = element.get("customData") or {}
        primitive_id = custom.get("primitive") if isinstance(custom, dict) else None
        if wanted and element["id"] not in wanted and primitive_id not in wanted:
            continue
        if primitive_id:
            if custom.get("role") == "anchor":
                primitives.append(_describe_element(element, include_text=False))
            elif include_text and isinstance(element.get("text"), str):
                texts.setdefault(primitive_id, []).append(element["text"][:80])
        else:
            raw.append(_describe_element(element, include_text))
    for item in primitives:
        if item.get("primitive") in texts:
            item["texts"] = texts[item["primitive"]][:6]
    xs = [a.x for a in (anchor_from_element(e) for e in scene) if a]
    ys = [a.y for a in (anchor_from_element(e) for e in scene) if a]
    bounds = None
    if xs and ys:
        anchors = [a for a in (anchor_from_element(e) for e in scene) if a]
        bounds = [
            round(min(xs)),
            round(min(ys)),
            round(max(a.x + a.width for a in anchors) - min(xs)),
            round(max(a.y + a.height for a in anchors) - min(ys)),
        ]
    return {"elementCount": len(scene), "bounds": bounds, "primitives": primitives, "rawElements": raw}


async def _draw(args: DrawArgs, context: ToolContext) -> ToolResult:
    patch = CanvasPatch(primitives=args.primitives)
    scene = _dry_run(patch, context)
    ids = {p.id for p in args.primitives}
    placed = [
        _describe_element(e, include_text=False)
        for e in scene
        if (e.get("customData") or {}).get("primitive") in ids and (e.get("customData") or {}).get("role") == "anchor"
    ]
    kinds = sorted({p.kind for p in args.primitives})
    return ToolResult(
        content={"placed": placed, "note": "box = [x, y, width, height] in scene coordinates."},
        patch=patch,
        summary=f"Drew {len(args.primitives)} primitive{'s' if len(args.primitives) != 1 else ''} ({', '.join(kinds)})",
    )


async def _edit_elements(args: EditElementsArgs, context: ToolContext) -> ToolResult:
    try:
        patch = CanvasPatch(upsert_elements=args.upsert_elements)
    except ValueError as exc:
        raise ToolError(str(exc)) from exc
    _dry_run(patch, context)
    return ToolResult(
        content={"updated": [e["id"] for e in args.upsert_elements]},
        patch=patch,
        summary=f"Edited {len(args.upsert_elements)} element{'s' if len(args.upsert_elements) != 1 else ''}",
    )


async def _delete_elements(args: DeleteElementsArgs, context: ToolContext) -> ToolResult:
    try:
        patch = CanvasPatch(delete_element_ids=args.ids)
    except ValueError as exc:
        raise ToolError(str(exc)) from exc
    before = len(context.scene)
    after = len(_dry_run(patch, context))
    return ToolResult(
        content={"removedElements": before - after},
        patch=patch,
        summary=f"Removed {before - after} element{'s' if before - after != 1 else ''}",
    )


async def _inspect_scene(args: InspectSceneArgs, context: ToolContext) -> ToolResult:
    overview = scene_overview(context.scene, ids=args.ids, include_text=args.include_text)
    if context.selected_element_ids:
        overview["selectedElementIds"] = context.selected_element_ids
    if context.viewport:
        overview["viewport"] = context.viewport
    return ToolResult(content=overview, summary="Inspected the scene")


async def _finish(args: FinishArgs, context: ToolContext) -> ToolResult:
    return ToolResult(
        content={"reply": args.reply, "summary": args.summary, "suggestions": args.suggestions},
        summary=args.summary,
        final=True,
    )


async def _ask_user(args: AskUserArgs, context: ToolContext) -> ToolResult:
    return ToolResult(
        content={"reply": args.question, "questions": args.options, "summary": ""},
        final=True,
    )


DRAW_TOOL = Tool(
    name="draw",
    description=(
        "Add or replace composition primitives (frame, heading, card, note, pin, route, timeline, legend, "
        "image, embed, code). The server lays them out with consistent typography and returns each "
        "primitive's final bounding box so you can position the next ones. Prefer this over edit_elements."
    ),
    args_model=DrawArgs,
    handler=_draw,
    mutates_canvas=True,
)

EDIT_ELEMENTS_TOOL = Tool(
    name="edit_elements",
    description=(
        "Low-level: upsert raw Excalidraw elements (rectangle, ellipse, diamond, text, arrow, line, freedraw). "
        "Use for small tweaks to existing user-drawn elements or shapes primitives cannot express. "
        "Never change an element's type."
    ),
    args_model=EditElementsArgs,
    handler=_edit_elements,
    mutates_canvas=True,
)

DELETE_ELEMENTS_TOOL = Tool(
    name="delete_elements",
    description="Remove elements or whole primitives by id. Only delete what the user asked to remove or what you are replacing.",
    args_model=DeleteElementsArgs,
    handler=_delete_elements,
    mutates_canvas=True,
)

INSPECT_SCENE_TOOL = Tool(
    name="inspect_scene",
    description="Get a compact overview of what is on the board (ids, kinds, bounding boxes, texts, selection, viewport).",
    args_model=InspectSceneArgs,
    handler=_inspect_scene,
)

FINISH_TOOL = Tool(
    name="finish",
    description="End the turn with a chat reply, a one-line summary of the board changes, and up to four follow-up suggestions. Call this exactly once when done.",
    args_model=FinishArgs,
    handler=_finish,
)

ASK_USER_TOOL = Tool(
    name="ask_user",
    description="Stop and ask the user a clarifying question (with optional quick-reply options) instead of guessing when the request is ambiguous in a way that materially changes the drawing.",
    args_model=AskUserArgs,
    handler=_ask_user,
)

CANVAS_TOOLS = [DRAW_TOOL, EDIT_ELEMENTS_TOOL, DELETE_ELEMENTS_TOOL, INSPECT_SCENE_TOOL, ASK_USER_TOOL, FINISH_TOOL]
