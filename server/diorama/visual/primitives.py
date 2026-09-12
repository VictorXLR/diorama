"""Composition primitives: the vocabulary an agent uses to lay out a board.

A primitive is a small, declarative description ("a card titled X with these
bullets at (x, y)") that the server expands into properly sized, aligned and
themed Excalidraw elements.  The model never has to do font arithmetic, and
every board ends up with consistent typography, padding and colour.

Each expanded element carries ``customData.primitive`` so a later patch that
re-upserts the same primitive id replaces its children cleanly, and
``groupIds=[id]`` so users can move a primitive as one unit.
"""

from __future__ import annotations

import math
import random
import time
from typing import Annotated, Any, Callable, Dict, List, Literal, Optional, Tuple, Union

from pydantic import BaseModel, ConfigDict, Field

from diorama.visual import text as text_metrics
from diorama.visual.theme import (
    ACCENT_NAMES,
    CARD_WIDTH,
    FONT_BODY,
    FONT_HEADING,
    FONT_MONO,
    FONT_SIZES,
    GRID,
    PADDING,
    PIN_DIAMETER,
    STROKE_WIDTH,
    Palette,
    palette_for,
    snap,
)

Point = Tuple[float, float]
AnchorRef = Union[str, Tuple[float, float]]


class Anchor(BaseModel):
    """Bounding box of something an arrow can attach to."""

    element_id: str
    x: float
    y: float
    width: float
    height: float

    @property
    def center(self) -> Point:
        return (self.x + self.width / 2, self.y + self.height / 2)


AnchorResolver = Callable[[str], Optional[Anchor]]


class _Primitive(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    id: str = Field(min_length=1)
    frame: Optional[str] = Field(default=None, description="Id of a frame primitive this belongs to.")


class FramePrimitive(_Primitive):
    kind: Literal["frame"]
    title: str
    x: float
    y: float
    width: float = Field(gt=0)
    height: float = Field(gt=0)


class HeadingPrimitive(_Primitive):
    kind: Literal["heading"]
    text: str
    subtitle: Optional[str] = None
    x: float
    y: float
    size: Literal["xl", "lg", "md"] = "xl"
    accent: Optional[str] = None


class CardPrimitive(_Primitive):
    kind: Literal["card"]
    title: str
    body: List[str] = Field(default_factory=list, description="Bullet lines; plain sentences are fine too.")
    x: float
    y: float
    width: float = Field(default=CARD_WIDTH, ge=160)
    accent: str = "indigo"
    number: Optional[int] = Field(default=None, description="Optional step number badge.")


class NotePrimitive(_Primitive):
    kind: Literal["note"]
    text: str
    x: float
    y: float
    width: float = Field(default=260, ge=120)
    accent: str = "amber"


class PinPrimitive(_Primitive):
    kind: Literal["pin"]
    label: str
    x: float
    y: float
    number: Optional[int] = None
    detail: Optional[str] = None
    accent: str = "coral"
    label_position: Literal["right", "left", "above", "below"] = Field(default="right", alias="labelPosition")


class RoutePrimitive(_Primitive):
    kind: Literal["route"]
    from_: AnchorRef = Field(alias="from", description="Primitive/element id or [x, y].")
    to: AnchorRef = Field(description="Primitive/element id or [x, y].")
    label: Optional[str] = None
    style: Literal["solid", "dashed", "dotted"] = "solid"
    accent: str = "slate"
    arrow: bool = True
    via: List[Tuple[float, float]] = Field(default_factory=list, description="Optional intermediate points.")


class TimelineStep(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str
    detail: Optional[str] = None
    accent: Optional[str] = None


class TimelinePrimitive(_Primitive):
    kind: Literal["timeline"]
    title: Optional[str] = None
    steps: List[TimelineStep] = Field(min_length=1)
    x: float
    y: float
    length: float = Field(default=800, ge=200, description="Total length along the axis.")
    orientation: Literal["horizontal", "vertical"] = "horizontal"
    accent: str = "indigo"


class LegendItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str
    accent: str = "indigo"


class LegendPrimitive(_Primitive):
    kind: Literal["legend"]
    title: Optional[str] = "Legend"
    items: List[LegendItem] = Field(min_length=1)
    x: float
    y: float


class ImagePrimitive(_Primitive):
    kind: Literal["image"]
    asset_id: str = Field(alias="assetId", description="File id returned by an asset tool (e.g. fetch_map).")
    x: float
    y: float
    width: float = Field(gt=0)
    height: float = Field(gt=0)
    caption: Optional[str] = None


class EmbedPrimitive(_Primitive):
    kind: Literal["embed"]
    url: str = Field(min_length=8)
    x: float
    y: float
    width: float = Field(default=560, gt=0)
    height: float = Field(default=360, gt=0)
    caption: Optional[str] = None


class CodePrimitive(_Primitive):
    kind: Literal["code"]
    code: str
    language: Optional[str] = None
    title: Optional[str] = None
    x: float
    y: float
    width: float = Field(default=480, ge=200)


Primitive = Annotated[
    Union[
        FramePrimitive,
        HeadingPrimitive,
        CardPrimitive,
        NotePrimitive,
        PinPrimitive,
        RoutePrimitive,
        TimelinePrimitive,
        LegendPrimitive,
        ImagePrimitive,
        EmbedPrimitive,
        CodePrimitive,
    ],
    Field(discriminator="kind"),
]

PRIMITIVE_KINDS = (
    "frame", "heading", "card", "note", "pin", "route", "timeline", "legend", "image", "embed", "code",
)


class PrimitiveExpansion(BaseModel):
    """Everything produced for one primitive."""

    elements: List[Dict[str, Any]]
    anchor: Optional[Anchor] = None


# --------------------------------------------------------------------------- #
# Element builders
# --------------------------------------------------------------------------- #


def _meta(primitive: _Primitive, role: str, *, group: bool = True) -> Dict[str, Any]:
    data: Dict[str, Any] = {
        "customData": {"primitive": primitive.id, "kind": primitive.kind, "role": role},
    }
    if group:
        data["groupIds"] = [primitive.id]
    if primitive.frame:
        data["frameId"] = primitive.frame
    return data


def _child_id(primitive: _Primitive, role: str) -> str:
    return f"{primitive.id}::{role}"


def _accent_name(name: Optional[str], fallback: str) -> str:
    return name if name in ACCENT_NAMES else fallback


def _text_element(
    primitive: _Primitive,
    role: str,
    *,
    text: str,
    x: float,
    y: float,
    font_size: float,
    font_family: int,
    color: str,
    align: str = "left",
    width: Optional[float] = None,
) -> Dict[str, Any]:
    lines = text.split("\n")
    measured_width, height = text_metrics.measure_block(lines, font_size, font_family)
    element: Dict[str, Any] = {
        "id": _child_id(primitive, role),
        "type": "text",
        "x": x,
        "y": y,
        "width": width if width is not None else measured_width,
        "height": height,
        "text": text,
        "originalText": text,
        "fontSize": font_size,
        "fontFamily": font_family,
        "textAlign": align,
        "verticalAlign": "top",
        "strokeColor": color,
        "lineHeight": text_metrics.LINE_HEIGHT,
        "autoResize": width is None,
        **_meta(primitive, role),
    }
    return element


def _shape_element(
    primitive: _Primitive,
    role: str,
    *,
    shape: str,
    x: float,
    y: float,
    width: float,
    height: float,
    fill: str,
    stroke: str,
    stroke_width: float = STROKE_WIDTH,
    stroke_style: str = "solid",
    rounded: bool = True,
    opacity: int = 100,
) -> Dict[str, Any]:
    element: Dict[str, Any] = {
        "id": _child_id(primitive, role),
        "type": shape,
        "x": x,
        "y": y,
        "width": width,
        "height": height,
        "backgroundColor": fill,
        "strokeColor": stroke,
        "strokeWidth": stroke_width,
        "strokeStyle": stroke_style,
        "fillStyle": "solid",
        "roughness": 0,
        "opacity": opacity,
        **_meta(primitive, role),
    }
    if rounded and shape == "rectangle":
        element["roundness"] = {"type": 3}
    return element


def _wrapped(text: str, width: float, font_size: float, font_family: int) -> str:
    return "\n".join(text_metrics.wrap_text(text, width, font_size, font_family))


# --------------------------------------------------------------------------- #
# Expanders
# --------------------------------------------------------------------------- #


def _expand_frame(p: FramePrimitive, palette: Palette, _: AnchorResolver) -> PrimitiveExpansion:
    x, y = snap(p.x), snap(p.y)
    width, height = snap(p.width), snap(p.height)
    element = {
        "id": p.id,
        "type": "frame",
        "name": p.title,
        "x": x,
        "y": y,
        "width": width,
        "height": height,
        "children": [],
        "customData": {"primitive": p.id, "kind": "frame", "role": "anchor"},
    }
    return PrimitiveExpansion(
        elements=[element],
        anchor=Anchor(element_id=p.id, x=x, y=y, width=width, height=height),
    )


def _expand_heading(p: HeadingPrimitive, palette: Palette, _: AnchorResolver) -> PrimitiveExpansion:
    x, y = snap(p.x), snap(p.y)
    size = FONT_SIZES[p.size]
    color = palette.accent(p.accent).stroke if p.accent else palette.text
    elements = [
        _text_element(p, "anchor", text=p.text, x=x, y=y, font_size=size, font_family=FONT_HEADING, color=color),
    ]
    height = text_metrics.line_height(size)
    if p.subtitle:
        sub_size = FONT_SIZES["sm"]
        elements.append(
            _text_element(
                p, "subtitle", text=p.subtitle, x=x, y=y + height + 4,
                font_size=sub_size, font_family=FONT_BODY, color=palette.text_muted,
            )
        )
        height += text_metrics.line_height(sub_size) + 4
    width = max(element["width"] for element in elements)
    return PrimitiveExpansion(
        elements=elements,
        anchor=Anchor(element_id=elements[0]["id"], x=x, y=y, width=width, height=height),
    )


def _expand_card(p: CardPrimitive, palette: Palette, _: AnchorResolver) -> PrimitiveExpansion:
    accent = palette.accent(_accent_name(p.accent, "indigo"))
    x, y = snap(p.x), snap(p.y)
    width = snap(p.width)
    inner_width = width - 2 * PADDING
    title_size = FONT_SIZES["md"]
    body_size = FONT_SIZES["sm"]

    badge_offset = 0.0
    elements: List[Dict[str, Any]] = []
    cursor = y + PADDING

    if p.number is not None:
        badge = 32
        badge_offset = badge + 12
        elements.append(
            _shape_element(
                p, "badge", shape="ellipse", x=x + PADDING, y=cursor - 4,
                width=badge, height=badge, fill=accent.stroke, stroke=accent.stroke,
            )
        )
        elements.append(
            _text_element(
                p, "badge-text", text=str(p.number), x=x + PADDING, y=cursor - 4 + (badge - text_metrics.line_height(FONT_SIZES["sm"])) / 2,
                font_size=FONT_SIZES["sm"], font_family=FONT_BODY, color=palette.surface, align="center", width=badge,
            )
        )

    title = _wrapped(p.title, inner_width - badge_offset, title_size, FONT_HEADING)
    title_element = _text_element(
        p, "title", text=title, x=x + PADDING + badge_offset, y=cursor,
        font_size=title_size, font_family=FONT_HEADING, color=accent.text, width=inner_width - badge_offset,
    )
    elements.append(title_element)
    cursor += title_element["height"] + 10

    # Accent rule under the title.
    elements.append(
        {
            "id": _child_id(p, "rule"),
            "type": "line",
            "x": x + PADDING,
            "y": cursor,
            "width": inner_width,
            "height": 0,
            "points": [[0, 0], [inner_width, 0]],
            "strokeColor": accent.stroke,
            "strokeWidth": 2,
            "roughness": 0,
            **_meta(p, "rule"),
        }
    )
    cursor += 14

    if p.body:
        bullet_lines = []
        for item in p.body:
            wrapped = text_metrics.wrap_text(item, inner_width - 18, body_size, FONT_BODY)
            bullet_lines.append("•  " + wrapped[0])
            bullet_lines.extend("    " + line for line in wrapped[1:])
        body_text = "\n".join(bullet_lines)
        body_element = _text_element(
            p, "body", text=body_text, x=x + PADDING, y=cursor,
            font_size=body_size, font_family=FONT_BODY, color=palette.text, width=inner_width,
        )
        elements.append(body_element)
        cursor += body_element["height"]

    height = snap(cursor + PADDING - y)
    background = _shape_element(
        p, "anchor", shape="rectangle", x=x, y=y, width=width, height=height,
        fill=accent.fill, stroke=accent.stroke,
    )
    return PrimitiveExpansion(
        elements=[background, *elements],
        anchor=Anchor(element_id=background["id"], x=x, y=y, width=width, height=height),
    )


def _expand_note(p: NotePrimitive, palette: Palette, _: AnchorResolver) -> PrimitiveExpansion:
    accent = palette.accent(_accent_name(p.accent, "amber"))
    x, y = snap(p.x), snap(p.y)
    width = snap(p.width)
    size = FONT_SIZES["sm"]
    body = _wrapped(p.text, width - 2 * PADDING, size, FONT_BODY)
    body_element = _text_element(
        p, "body", text=body, x=x + PADDING, y=y + PADDING,
        font_size=size, font_family=FONT_BODY, color=accent.text, width=width - 2 * PADDING,
    )
    height = snap(body_element["height"] + 2 * PADDING)
    background = _shape_element(
        p, "anchor", shape="rectangle", x=x, y=y, width=width, height=height,
        fill=accent.fill, stroke=accent.stroke, stroke_style="dashed", rounded=False,
    )
    return PrimitiveExpansion(
        elements=[background, body_element],
        anchor=Anchor(element_id=background["id"], x=x, y=y, width=width, height=height),
    )


def _expand_pin(p: PinPrimitive, palette: Palette, _: AnchorResolver) -> PrimitiveExpansion:
    accent = palette.accent(_accent_name(p.accent, "coral"))
    diameter = PIN_DIAMETER
    x, y = snap(p.x), snap(p.y)
    circle = _shape_element(
        p, "anchor", shape="ellipse", x=x, y=y, width=diameter, height=diameter,
        fill=accent.stroke, stroke=palette.surface, stroke_width=3,
    )
    elements = [circle]
    if p.number is not None:
        elements.append(
            _text_element(
                p, "number", text=str(p.number), x=x,
                y=y + (diameter - text_metrics.line_height(FONT_SIZES["sm"])) / 2,
                font_size=FONT_SIZES["sm"], font_family=FONT_BODY, color="#ffffff", align="center", width=diameter,
            )
        )

    label_size = FONT_SIZES["sm"]
    label_width = text_metrics.measure_line(p.label, label_size, FONT_HEADING)
    gap = 10
    if p.label_position == "right":
        lx, ly, align = x + diameter + gap, y + (diameter - text_metrics.line_height(label_size)) / 2, "left"
    elif p.label_position == "left":
        lx, ly, align = x - gap - label_width, y + (diameter - text_metrics.line_height(label_size)) / 2, "right"
    elif p.label_position == "above":
        lx, ly, align = x + diameter / 2 - label_width / 2, y - gap - text_metrics.line_height(label_size), "center"
    else:
        lx, ly, align = x + diameter / 2 - label_width / 2, y + diameter + gap, "center"

    label_element = _text_element(
        p, "label", text=p.label, x=lx, y=ly, font_size=label_size, font_family=FONT_HEADING,
        color=accent.stroke, align=align,
    )
    elements.append(label_element)
    if p.detail:
        detail_size = FONT_SIZES["xs"]
        elements.append(
            _text_element(
                p, "detail", text=p.detail, x=lx, y=ly + text_metrics.line_height(label_size),
                font_size=detail_size, font_family=FONT_BODY, color=palette.text_muted, align=align,
            )
        )
    return PrimitiveExpansion(
        elements=elements,
        anchor=Anchor(element_id=circle["id"], x=x, y=y, width=diameter, height=diameter),
    )


def _edge_point(anchor: Anchor, towards: Point) -> Point:
    """Point on the anchor's boundary in the direction of ``towards``."""
    cx, cy = anchor.center
    dx, dy = towards[0] - cx, towards[1] - cy
    if dx == 0 and dy == 0:
        return (cx, cy)
    half_w, half_h = anchor.width / 2, anchor.height / 2
    scale = min(
        half_w / abs(dx) if dx else math.inf,
        half_h / abs(dy) if dy else math.inf,
    )
    return (cx + dx * scale, cy + dy * scale)


def _resolve_ref(ref: AnchorRef, resolve: AnchorResolver) -> Tuple[Optional[Anchor], Point]:
    if isinstance(ref, str):
        anchor = resolve(ref)
        if anchor is None:
            raise ValueError(f"Route references unknown anchor '{ref}'")
        return anchor, anchor.center
    return None, (float(ref[0]), float(ref[1]))


def _expand_route(p: RoutePrimitive, palette: Palette, resolve: AnchorResolver) -> PrimitiveExpansion:
    accent = palette.accent(_accent_name(p.accent, "slate"))
    start_anchor, start_center = _resolve_ref(p.from_, resolve)
    end_anchor, end_center = _resolve_ref(p.to, resolve)

    waypoints = [(float(x), float(y)) for x, y in p.via]
    first_target = waypoints[0] if waypoints else end_center
    last_source = waypoints[-1] if waypoints else start_center
    start = _edge_point(start_anchor, first_target) if start_anchor else start_center
    end = _edge_point(end_anchor, last_source) if end_anchor else end_center

    absolute = [start, *waypoints, end]
    origin = absolute[0]
    points = [[round(px - origin[0], 2), round(py - origin[1], 2)] for px, py in absolute]
    xs = [pt[0] for pt in points]
    ys = [pt[1] for pt in points]

    element: Dict[str, Any] = {
        "id": _child_id(p, "anchor"),
        "type": "arrow" if p.arrow else "line",
        "x": origin[0],
        "y": origin[1],
        "width": max(xs) - min(xs),
        "height": max(ys) - min(ys),
        "points": points,
        "strokeColor": accent.stroke,
        "strokeWidth": 2,
        "strokeStyle": p.style,
        "roughness": 0,
        **_meta(p, "anchor", group=False),
    }
    if p.arrow:
        element["endArrowhead"] = "arrow"
        element["startArrowhead"] = None
        if start_anchor:
            element["start"] = {"id": start_anchor.element_id}
        if end_anchor:
            element["end"] = {"id": end_anchor.element_id}
    elements = [element]

    if p.label:
        mid_index = len(absolute) // 2
        if len(absolute) % 2 == 0:
            a, b = absolute[mid_index - 1], absolute[mid_index]
            mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        else:
            mid = absolute[mid_index]
        size = FONT_SIZES["xs"]
        label_width = text_metrics.measure_line(p.label, size, FONT_BODY)
        elements.append(
            _text_element(
                p, "label", text=p.label, x=mid[0] - label_width / 2, y=mid[1] - text_metrics.line_height(size) - 6,
                font_size=size, font_family=FONT_BODY, color=accent.text if palette.surface != "#ffffff" else accent.stroke,
                align="center",
            )
        )
    return PrimitiveExpansion(elements=elements, anchor=None)


def _expand_timeline(p: TimelinePrimitive, palette: Palette, _: AnchorResolver) -> PrimitiveExpansion:
    base_accent = _accent_name(p.accent, "indigo")
    x, y = snap(p.x), snap(p.y)
    length = snap(p.length)
    horizontal = p.orientation == "horizontal"
    elements: List[Dict[str, Any]] = []
    cursor_y = y

    if p.title:
        title = _text_element(
            p, "title", text=p.title, x=x, y=cursor_y, font_size=FONT_SIZES["md"], font_family=FONT_HEADING,
            color=palette.text,
        )
        elements.append(title)
        cursor_y += title["height"] + PADDING

    dot = 28
    count = len(p.steps)
    spacing = length / max(count - 1, 1)
    label_size = FONT_SIZES["sm"]
    detail_size = FONT_SIZES["xs"]
    axis_stroke = palette.accent(base_accent).stroke

    if horizontal:
        axis_y = cursor_y + dot / 2
        elements.append(
            {
                "id": _child_id(p, "axis"), "type": "line", "x": x, "y": axis_y,
                "width": length, "height": 0, "points": [[0, 0], [length, 0]],
                "strokeColor": axis_stroke, "strokeWidth": 3, "roughness": 0, **_meta(p, "axis"),
            }
        )
    else:
        axis_x = x + dot / 2
        elements.append(
            {
                "id": _child_id(p, "axis"), "type": "line", "x": axis_x, "y": cursor_y,
                "width": 0, "height": length, "points": [[0, 0], [0, length]],
                "strokeColor": axis_stroke, "strokeWidth": 3, "roughness": 0, **_meta(p, "axis"),
            }
        )

    max_extent = 0.0
    for index, step in enumerate(p.steps):
        accent = palette.accent(_accent_name(step.accent, base_accent))
        if horizontal:
            cx = x + index * spacing - dot / 2 if count > 1 else x
            cy = cursor_y
        else:
            cx = x
            cy = cursor_y + index * spacing - dot / 2 if count > 1 else cursor_y
        cx, cy = max(cx, x) if horizontal else cx, max(cy, cursor_y)
        elements.append(
            _shape_element(
                p, f"dot-{index}", shape="ellipse", x=cx, y=cy, width=dot, height=dot,
                fill=accent.stroke, stroke=palette.surface, stroke_width=3,
            )
        )
        elements.append(
            _text_element(
                p, f"num-{index}", text=str(index + 1), x=cx,
                y=cy + (dot - text_metrics.line_height(FONT_SIZES["xs"])) / 2,
                font_size=FONT_SIZES["xs"], font_family=FONT_BODY, color="#ffffff", align="center", width=dot,
            )
        )
        column_width = spacing - 16 if horizontal and count > 1 else 240
        label = _wrapped(step.label, column_width, label_size, FONT_HEADING)
        if horizontal:
            lx, ly = cx - column_width / 2 + dot / 2, cy + dot + 10
            align = "center"
        else:
            lx, ly = cx + dot + 14, cy + (dot - text_metrics.line_height(label_size)) / 2
            align = "left"
        label_element = _text_element(
            p, f"label-{index}", text=label, x=lx, y=ly, font_size=label_size, font_family=FONT_HEADING,
            color=accent.text if palette.surface != "#ffffff" else accent.stroke, align=align, width=column_width,
        )
        elements.append(label_element)
        extent = label_element["height"]
        if step.detail:
            detail = _wrapped(step.detail, column_width, detail_size, FONT_BODY)
            detail_element = _text_element(
                p, f"detail-{index}", text=detail, x=lx, y=ly + label_element["height"] + 2,
                font_size=detail_size, font_family=FONT_BODY, color=palette.text_muted, align=align, width=column_width,
            )
            elements.append(detail_element)
            extent += detail_element["height"] + 2
        max_extent = max(max_extent, extent)

    if horizontal:
        width, height = length, (cursor_y - y) + dot + 10 + max_extent
    else:
        width, height = dot + 14 + 240, (cursor_y - y) + length + dot
    return PrimitiveExpansion(
        elements=elements,
        anchor=Anchor(element_id=elements[0]["id"], x=x, y=y, width=width, height=height),
    )


def _expand_legend(p: LegendPrimitive, palette: Palette, _: AnchorResolver) -> PrimitiveExpansion:
    x, y = snap(p.x), snap(p.y)
    size = FONT_SIZES["xs"]
    swatch = 14
    row = text_metrics.line_height(size) + 8
    inner = PADDING * 0.75
    elements: List[Dict[str, Any]] = []
    cursor = y + inner
    widest = 0.0
    if p.title:
        title = _text_element(
            p, "title", text=p.title, x=x + inner, y=cursor, font_size=FONT_SIZES["xs"], font_family=FONT_HEADING,
            color=palette.text_muted,
        )
        elements.append(title)
        widest = title["width"]
        cursor += title["height"] + 6
    for index, item in enumerate(p.items):
        accent = palette.accent(_accent_name(item.accent, "indigo"))
        elements.append(
            _shape_element(
                p, f"swatch-{index}", shape="rectangle", x=x + inner, y=cursor + (row - swatch) / 2 - 4,
                width=swatch, height=swatch, fill=accent.stroke, stroke=accent.stroke, rounded=False,
            )
        )
        label = _text_element(
            p, f"label-{index}", text=item.label, x=x + inner + swatch + 8, y=cursor,
            font_size=size, font_family=FONT_BODY, color=palette.text,
        )
        elements.append(label)
        widest = max(widest, swatch + 8 + label["width"])
        cursor += row
    width = snap(widest + 2 * inner)
    height = snap(cursor - y + inner - 8)
    background = _shape_element(
        p, "anchor", shape="rectangle", x=x, y=y, width=width, height=height,
        fill=palette.surface, stroke=palette.border,
    )
    return PrimitiveExpansion(
        elements=[background, *elements],
        anchor=Anchor(element_id=background["id"], x=x, y=y, width=width, height=height),
    )


def _expand_image(p: ImagePrimitive, palette: Palette, _: AnchorResolver) -> PrimitiveExpansion:
    x, y = snap(p.x), snap(p.y)
    width, height = snap(p.width), snap(p.height)
    image = {
        "id": _child_id(p, "anchor"),
        "type": "image",
        "x": x,
        "y": y,
        "width": width,
        "height": height,
        "fileId": p.asset_id,
        "status": "saved",
        "scale": [1, 1],
        "roundness": {"type": 3},
        **_meta(p, "anchor"),
    }
    elements = [image]
    if p.caption:
        elements.append(
            _text_element(
                p, "caption", text=p.caption, x=x, y=y + height + 8, font_size=FONT_SIZES["xs"],
                font_family=FONT_BODY, color=palette.text_muted,
            )
        )
    return PrimitiveExpansion(
        elements=elements,
        anchor=Anchor(element_id=image["id"], x=x, y=y, width=width, height=height),
    )


def native_element_base(element_id: str) -> Dict[str, Any]:
    """Fields Excalidraw expects on elements that bypass its skeleton converter."""
    now = int(time.time() * 1000)
    return {
        "id": element_id,
        "angle": 0,
        "strokeColor": "#1e1e1e",
        "backgroundColor": "transparent",
        "fillStyle": "solid",
        "strokeWidth": 1,
        "strokeStyle": "solid",
        "roughness": 0,
        "opacity": 100,
        "groupIds": [],
        "frameId": None,
        "index": None,
        "roundness": None,
        "seed": random.randint(1, 2**31 - 1),
        "version": 1,
        "versionNonce": random.randint(1, 2**31 - 1),
        "isDeleted": False,
        "boundElements": None,
        "updated": now,
        "link": None,
        "locked": False,
    }


def _expand_embed(p: EmbedPrimitive, palette: Palette, _: AnchorResolver) -> PrimitiveExpansion:
    if not p.url.startswith("https://"):
        raise ValueError("Embeds must use https URLs")
    x, y = snap(p.x), snap(p.y)
    width, height = snap(p.width), snap(p.height)
    element = {
        **native_element_base(_child_id(p, "anchor")),
        "type": "embeddable",
        "x": x,
        "y": y,
        "width": width,
        "height": height,
        "link": p.url,
        "validated": True,
        "strokeColor": palette.border,
        **_meta(p, "anchor"),
    }
    element["groupIds"] = [p.id]
    element["frameId"] = p.frame
    elements = [element]
    if p.caption:
        elements.append(
            _text_element(
                p, "caption", text=p.caption, x=x, y=y + height + 8, font_size=FONT_SIZES["xs"],
                font_family=FONT_BODY, color=palette.text_muted,
            )
        )
    return PrimitiveExpansion(
        elements=elements,
        anchor=Anchor(element_id=element["id"], x=x, y=y, width=width, height=height),
    )


def _expand_code(p: CodePrimitive, palette: Palette, _: AnchorResolver) -> PrimitiveExpansion:
    x, y = snap(p.x), snap(p.y)
    width = snap(p.width)
    size = FONT_SIZES["xs"]
    inner_width = width - 2 * PADDING
    elements: List[Dict[str, Any]] = []
    cursor = y + PADDING * 0.75
    header = p.title or p.language
    if header:
        title = _text_element(
            p, "title", text=header, x=x + PADDING, y=cursor, font_size=FONT_SIZES["xs"], font_family=FONT_BODY,
            color=palette.text_muted,
        )
        elements.append(title)
        cursor += title["height"] + 8
    # Keep source lines intact; only soft-wrap absurdly long ones.
    lines: List[str] = []
    for raw in p.code.split("\n"):
        lines.extend(text_metrics.wrap_text(raw, inner_width, size, FONT_MONO) if raw else [""])
    body = _text_element(
        p, "body", text="\n".join(lines), x=x + PADDING, y=cursor, font_size=size, font_family=FONT_MONO,
        color=palette.text, width=inner_width,
    )
    elements.append(body)
    height = snap(cursor + body["height"] + PADDING * 0.75 - y)
    background = _shape_element(
        p, "anchor", shape="rectangle", x=x, y=y, width=width, height=height,
        fill=palette.surface_alt, stroke=palette.border,
    )
    return PrimitiveExpansion(
        elements=[background, *elements],
        anchor=Anchor(element_id=background["id"], x=x, y=y, width=width, height=height),
    )


_EXPANDERS = {
    "frame": _expand_frame,
    "heading": _expand_heading,
    "card": _expand_card,
    "note": _expand_note,
    "pin": _expand_pin,
    "route": _expand_route,
    "timeline": _expand_timeline,
    "legend": _expand_legend,
    "image": _expand_image,
    "embed": _expand_embed,
    "code": _expand_code,
}


def expand_primitive(primitive: Primitive, theme: str, resolve: AnchorResolver) -> PrimitiveExpansion:
    palette = palette_for(theme)
    expander = _EXPANDERS[primitive.kind]
    expansion = expander(primitive, palette, resolve)  # type: ignore[arg-type]
    for element in expansion.elements:
        element.setdefault("locked", False)
    return expansion


def anchor_from_element(element: Dict[str, Any]) -> Optional[Anchor]:
    """Bounding box for a scene element, if it has one."""
    x, y = element.get("x"), element.get("y")
    if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
        return None
    width = element.get("width") or 0
    height = element.get("height") or 0
    return Anchor(element_id=element["id"], x=float(x), y=float(y), width=float(width), height=float(height))


def primitive_schema_summary() -> str:
    """Compact schema description used in the model prompt."""
    return f"""Primitives (put them in canvas.primitives; the server expands them into styled elements):
- frame: {{id,kind:"frame",title,x,y,width,height}} — a titled region; other primitives set "frame":"<frame id>" to live inside it.
- heading: {{id,kind:"heading",text,subtitle?,x,y,size?:"xl"|"lg"|"md",accent?}}
- card: {{id,kind:"card",title,body?:[lines],x,y,width?(default {CARD_WIDTH}),accent?,number?,frame?}} — height is computed.
- note: {{id,kind:"note",text,x,y,width?,accent?,frame?}} — a dashed sticky note for tips/caveats.
- pin: {{id,kind:"pin",label,x,y,number?,detail?,accent?,labelPosition?,frame?}} — a numbered marker; place on top of images/maps.
- route: {{id,kind:"route",from:<primitive id>|[x,y],to:<primitive id>|[x,y],label?,style?:"solid"|"dashed"|"dotted",arrow?,via?:[[x,y]],accent?}} — arrows stay attached to the pins/cards they reference.
- timeline: {{id,kind:"timeline",title?,steps:[{{label,detail?,accent?}}],x,y,length?,orientation?,accent?,frame?}}
- legend: {{id,kind:"legend",title?,items:[{{label,accent}}],x,y,frame?}}
- image: {{id,kind:"image",assetId,x,y,width,height,caption?,frame?}} — assetId must come from an asset tool result.
- embed: {{id,kind:"embed",url(https),x,y,width?,height?,caption?,frame?}} — live iframe (maps, videos, docs).
- code: {{id,kind:"code",code,language?,title?,x,y,width?,frame?}}
Accents: {", ".join(ACCENT_NAMES)}. Grid: {GRID}px — use multiples of {GRID} for x/y. Ids are stable: re-sending a primitive with the same id replaces it."""
