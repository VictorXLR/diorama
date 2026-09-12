"""Tests for canvas patching: primitive expansion and frame fitting.

Excalidraw clips anything drawn outside a frame, so a frame that is smaller than
its contents hides them.  These tests pin the rule that primitive frames always
end up enclosing their children.
"""

from __future__ import annotations

from typing import Any, Dict, List

from diorama.models.canvas import CanvasPatch, apply_canvas_patch


def _by_id(elements: List[Dict[str, Any]], element_id: str) -> Dict[str, Any]:
    return next(element for element in elements if element["id"] == element_id)


def _box(element: Dict[str, Any]) -> tuple:
    return (
        element["x"],
        element["y"],
        element["x"] + element["width"],
        element["y"] + element["height"],
    )


def test_primitive_frame_grows_to_enclose_its_children():
    # A frame drawn far too small, with its card placed well outside it.
    scene = apply_canvas_patch(
        [],
        CanvasPatch.model_validate(
            {
                "primitives": [
                    {"id": "box", "kind": "frame", "title": "Box", "x": 0, "y": 0, "width": 100, "height": 100},
                    {
                        "id": "card",
                        "kind": "card",
                        "frame": "box",
                        "title": "A card title long enough to wrap onto a second line",
                        "body": ["first bullet", "second bullet", "third bullet"],
                        "x": 400,
                        "y": 300,
                        "width": 320,
                    },
                ]
            }
        ),
    )
    frame = _by_id(scene, "box")
    card = _by_id(scene, "card::anchor")
    frame_left, frame_top, frame_right, frame_bottom = _box(frame)
    card_left, card_top, card_right, card_bottom = _box(card)
    assert frame_left <= card_left
    assert frame_top <= card_top
    assert frame_right >= card_right
    assert frame_bottom >= card_bottom


def test_primitive_frame_is_never_shrunk():
    # A deliberately oversized frame keeps its dimensions.
    scene = apply_canvas_patch(
        [],
        CanvasPatch.model_validate(
            {
                "primitives": [
                    {"id": "box", "kind": "frame", "title": "Box", "x": 0, "y": 0, "width": 2000, "height": 2000},
                    {"id": "card", "kind": "card", "frame": "box", "title": "Tiny", "x": 100, "y": 100, "width": 320},
                ]
            }
        ),
    )
    frame = _by_id(scene, "box")
    assert frame["width"] == 2000
    assert frame["height"] == 2000


def test_native_frames_are_left_alone():
    # User-drawn frames must not be rewritten, even if a child sticks out.
    scene = [
        {"id": "frame", "type": "frame", "x": 0, "y": 0, "width": 500, "height": 300, "name": "User artwork"},
        {"id": "sun", "type": "ellipse", "x": 600, "y": 600, "width": 40, "height": 40, "frameId": "frame"},
    ]
    result = apply_canvas_patch(scene, CanvasPatch())
    frame = _by_id(result, "frame")
    assert (frame["x"], frame["y"], frame["width"], frame["height"]) == (0, 0, 500, 300)
    assert _by_id(result, "sun")["frameId"] == "frame"
