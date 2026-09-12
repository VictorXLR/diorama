import copy
import json
from typing import List, Optional, Literal, Any, Dict, Tuple, Annotated, Set
from pydantic import BaseModel, ConfigDict, Field, AfterValidator, model_validator

from diorama.visual.primitives import (
    Anchor,
    Primitive,
    RoutePrimitive,
    anchor_from_element,
    expand_primitive,
)


class ExcalidrawLabel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    text: str
    fontSize: Optional[int] = Field(default=14, alias="fontSize")
    fontFamily: Optional[int] = Field(default=1, alias="fontFamily")
    textAlign: Optional[Literal["left", "center", "right"]] = Field(default="left", alias="textAlign")
    verticalAlign: Optional[Literal["top", "middle", "bottom"]] = Field(default="middle", alias="verticalAlign")


class ExcalidrawRoundness(BaseModel):
    type: int = 3
    value: Optional[float] = None


class ExcalidrawSkeletonElement(BaseModel):
    """
    Skeleton representation compatible with Excalidraw's convertToExcalidrawElements.
    This enables the Python server to directly output whiteboard scenes.
    """
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    type: Literal["rectangle", "ellipse", "diamond", "arrow", "line", "text", "freedraw", "image", "frame"]
    x: float
    y: float
    width: Optional[float] = None
    height: Optional[float] = None
    angle: Optional[float] = 0.0
    strokeColor: Optional[str] = Field(default="#000000", alias="strokeColor")
    backgroundColor: Optional[str] = Field(default="transparent", alias="backgroundColor")
    fillStyle: Optional[Literal["hachure", "cross-hatch", "solid", "zigzag"]] = Field(default="solid", alias="fillStyle")
    strokeWidth: Optional[float] = Field(default=1.0, alias="strokeWidth")
    strokeStyle: Optional[Literal["solid", "dashed", "dotted"]] = Field(default="solid", alias="strokeStyle")
    roughness: Optional[int] = 0
    opacity: Optional[int] = 100
    roundness: Optional[ExcalidrawRoundness] = None
    points: Optional[List[Tuple[float, float]]] = None
    label: Optional[ExcalidrawLabel] = None
    customData: Optional[Dict[str, Any]] = Field(default=None, alias="customData")


class SceneElement(ExcalidrawSkeletonElement):
    """Validation view only: never serialize this over a supplied native element."""

    model_config = ConfigDict(extra="allow", strict=True, allow_inf_nan=False)
    id: str = Field(min_length=1)
    type: Literal[
        "rectangle", "ellipse", "diamond", "arrow", "line", "text", "freedraw",
        "image", "frame", "magicframe", "embeddable", "iframe",
    ]
    points: Optional[List[List[float]]] = None
    text: Optional[str] = None
    width: Optional[float] = Field(default=None, ge=0)
    height: Optional[float] = Field(default=None, ge=0)
    opacity: int = Field(default=100, ge=0, le=100)
    roughness: float = Field(default=0, ge=0)
    strokeWidth: float = Field(default=1, ge=0)

    @model_validator(mode="after")
    def check_geometry(self):
        if not self.id.strip():
            raise ValueError("Element IDs must not be blank")
        if self.type == "text" and self.text is None:
            raise ValueError("Text elements require text")
        if self.type in {"line", "arrow", "freedraw"}:
            minimum = 1 if self.type == "freedraw" else 2
            if not self.points or len(self.points) < minimum or any(len(p) != 2 for p in self.points):
                raise ValueError("Linear elements require coordinate pairs")
        elif self.type != "text" and (self.width is None or self.height is None):
            raise ValueError("Shape elements require width and height")
        return self


def validate_scene(elements: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Validate without dropping, defaulting, or coercing any native JSON fields."""
    try:
        json.dumps(elements, allow_nan=False)
    except (ValueError, TypeError) as exc:
        raise ValueError("Scene must contain finite JSON values") from exc
    ids = set()
    for element in elements:
        SceneElement.model_validate(element)
        if element["id"] in ids:
            raise ValueError("Scene contains duplicate element IDs")
        ids.add(element["id"])
    return copy.deepcopy(elements)


VisualElements = Annotated[List[Dict[str, Any]], AfterValidator(validate_scene)]


class CanvasFile(BaseModel):
    """A binary asset (image) referenced by ``image`` elements via ``fileId``."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    mime_type: str = Field(alias="mimeType", pattern=r"^image/")
    data_url: str = Field(alias="dataURL", min_length=16, pattern=r"^data:image/")
    created: Optional[int] = None
    source: Optional[str] = Field(default=None, description="Provenance, e.g. the map provider URL.")


CanvasFiles = Dict[str, CanvasFile]


class CanvasPatch(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid", strict=True)

    upsert_elements: List[Dict[str, Any]] = Field(default_factory=list, alias="upsertElements")
    delete_element_ids: List[str] = Field(default_factory=list, alias="deleteElementIds")
    primitives: List[Primitive] = Field(default_factory=list)
    files: Dict[str, CanvasFile] = Field(default_factory=dict)

    @model_validator(mode="after")
    def check_ids(self):
        ids = [element.get("id") for element in self.upsert_elements]
        primitive_ids = [primitive.id for primitive in self.primitives]
        if any(not isinstance(id_, str) or not id_.strip() for id_ in ids + self.delete_element_ids):
            raise ValueError("Patch elements require non-empty stable IDs")
        if len(set(ids)) != len(ids) or len(set(self.delete_element_ids)) != len(self.delete_element_ids):
            raise ValueError("Patch contains duplicate IDs")
        if len(set(primitive_ids)) != len(primitive_ids):
            raise ValueError("Patch contains duplicate primitive IDs")
        if set(ids) & set(self.delete_element_ids):
            raise ValueError("Cannot upsert and delete the same element")
        if set(primitive_ids) & set(self.delete_element_ids):
            raise ValueError("Cannot upsert and delete the same primitive")
        return self

    @property
    def is_empty(self) -> bool:
        return not (self.upsert_elements or self.delete_element_ids or self.primitives or self.files)


def _merge_fields(original: Dict[str, Any], update: Dict[str, Any]) -> Dict[str, Any]:
    merged = copy.deepcopy(original)
    for key, value in update.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_fields(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def _primitive_of(element: Dict[str, Any]) -> Optional[str]:
    custom = element.get("customData")
    if isinstance(custom, dict) and isinstance(custom.get("primitive"), str):
        return custom["primitive"]
    return None


def _is_anchor(element: Dict[str, Any]) -> bool:
    custom = element.get("customData")
    return isinstance(custom, dict) and custom.get("role") == "anchor"


def finalize_scene(elements: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Keep frame membership consistent for agent-generated content.

    Native (user-drawn) elements are never rewritten; only elements produced by
    primitives get their ``frameId``/``children`` reconciled.
    """
    frame_ids = {element["id"] for element in elements if element.get("type") in {"frame", "magicframe"}}
    children: Dict[str, List[str]] = {frame_id: [] for frame_id in frame_ids}
    for element in elements:
        frame_id = element.get("frameId")
        if frame_id in children and element.get("type") not in {"frame", "magicframe"}:
            children[frame_id].append(element["id"])
        elif frame_id is not None and frame_id not in children and _primitive_of(element):
            element["frameId"] = None
    for element in elements:
        if element["id"] in children and _primitive_of(element):
            element["children"] = children[element["id"]]
    return elements


def apply_canvas_patch(
    scene: List[Dict[str, Any]],
    patch: CanvasPatch,
    *,
    theme: str = "light",
    known_files: Optional[Set[str]] = None,
) -> List[Dict[str, Any]]:
    """Apply atomically in scene order; nested objects merge, arrays/null replace.

    Primitives are expanded after raw upserts so routes can reference elements
    created in the same patch.  Re-upserting a primitive id replaces all of the
    elements it previously produced.
    """
    current = {element["id"]: element for element in validate_scene(scene)}
    available_files = set(known_files or set()) | set(patch.files.keys())

    # Deleting a primitive id removes everything it expanded into.
    delete_ids: Set[str] = set()
    for id_ in patch.delete_element_ids:
        owned = [eid for eid, element in current.items() if _primitive_of(element) == id_]
        if id_ not in current and not owned:
            raise ValueError("Cannot delete an unknown element ID")
        delete_ids.add(id_)
        delete_ids.update(owned)

    for element in patch.upsert_elements:
        id_ = element["id"]
        if id_ in current:
            if "type" in element and element["type"] != current[id_]["type"]:
                raise ValueError("Cannot change an existing element's type")
            current[id_] = _merge_fields(current[id_], element)
        else:
            # Only supported skeleton types may be created; native-only types can be edited.
            ExcalidrawSkeletonElement.model_validate(element)
            if element.get("type") == "image" and element.get("fileId") not in available_files:
                raise ValueError("Image elements must reference a known fileId (use an asset tool first)")
            current[id_] = copy.deepcopy(element)

    def resolve(ref: str) -> Optional[Anchor]:
        for element in current.values():
            if _primitive_of(element) == ref and _is_anchor(element):
                return anchor_from_element(element)
        direct = current.get(ref)
        return anchor_from_element(direct) if direct else None

    def expand(primitive: Primitive) -> None:
        for eid in [eid for eid, element in current.items() if _primitive_of(element) == primitive.id]:
            del current[eid]
        if primitive.kind == "image" and primitive.asset_id not in available_files:
            raise ValueError(f"Image primitive '{primitive.id}' references unknown assetId '{primitive.asset_id}'")
        if primitive.frame and resolve(primitive.frame) is None:
            raise ValueError(f"Primitive '{primitive.id}' references unknown frame '{primitive.frame}'")
        expansion = expand_primitive(primitive, theme, resolve)
        for element in expansion.elements:
            if _is_anchor(element):
                element.setdefault("customData", {})["spec"] = primitive.model_dump(by_alias=True, exclude_none=True)
            current[element["id"]] = element

    touched: Set[str] = set()
    for primitive in patch.primitives:
        expand(primitive)
        touched.add(primitive.id)

    # Routes attached to a primitive that just moved must follow it.
    if touched:
        for element in list(current.values()):
            custom = element.get("customData") or {}
            spec = custom.get("spec") if _is_anchor(element) else None
            if not isinstance(spec, dict) or spec.get("kind") != "route" or spec["id"] in touched:
                continue
            if spec.get("from") in touched or spec.get("to") in touched:
                expand(RoutePrimitive.model_validate(spec))

    for id_ in delete_ids:
        current.pop(id_, None)
    return validate_scene(finalize_scene(list(current.values())))


def changed_element_ids(before: List[Dict[str, Any]], after: List[Dict[str, Any]]) -> List[str]:
    """Ids that were added or modified (used by the UI to highlight what the agent touched)."""
    previous = {element["id"]: element for element in before}
    return [element["id"] for element in after if previous.get(element["id"]) != element]

