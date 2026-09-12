"""Approximate text metrics for Excalidraw fonts.

Excalidraw measures text in the browser; the server only needs estimates good
enough to size containers and wrap body copy so nothing overflows.
"""

from __future__ import annotations

from typing import List

from diorama.visual.theme import FONT_BODY, FONT_HEADING, FONT_MONO, LINE_HEIGHT

# Average glyph advance as a fraction of font size, tuned per family.
_CHAR_WIDTH_RATIO = {
    FONT_HEADING: 0.58,
    FONT_BODY: 0.54,
    FONT_MONO: 0.62,
}
_DEFAULT_RATIO = 0.56
# Wide glyphs (CJK, emoji) take a full em.
_WIDE_THRESHOLD = 0x2E80


def char_width(character: str, font_size: float, font_family: int) -> float:
    if ord(character) >= _WIDE_THRESHOLD:
        return font_size
    ratio = _CHAR_WIDTH_RATIO.get(font_family, _DEFAULT_RATIO)
    if character in "ilj.,:;'|! ":
        ratio *= 0.55
    elif character.isupper() or character in "mwMW@":
        ratio *= 1.18
    return font_size * ratio


def measure_line(text: str, font_size: float, font_family: int) -> float:
    return sum(char_width(character, font_size, font_family) for character in text)


def line_height(font_size: float) -> float:
    return font_size * LINE_HEIGHT


def wrap_text(text: str, max_width: float, font_size: float, font_family: int) -> List[str]:
    """Greedy word wrap that respects explicit newlines and never returns an empty list."""
    lines: List[str] = []
    for paragraph in text.split("\n"):
        words = paragraph.split(" ")
        current = ""
        for word in words:
            candidate = word if not current else f"{current} {word}"
            if measure_line(candidate, font_size, font_family) <= max_width or not current:
                current = candidate
            else:
                lines.append(current)
                current = word
        lines.append(current)
    return lines or [""]


def measure_block(lines: List[str], font_size: float, font_family: int) -> tuple[float, float]:
    width = max((measure_line(line, font_size, font_family) for line in lines), default=0.0)
    return width, line_height(font_size) * len(lines)
