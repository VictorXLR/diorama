"""Design tokens shared by every composition primitive.

Keeping colour, spacing and typography in one place is what makes generated
boards look like one designer made them rather than a model improvising.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Literal

Theme = Literal["light", "dark"]
Accent = Literal["indigo", "coral", "amber", "emerald", "sky", "violet", "rose", "slate"]

GRID = 20
"""Every primitive snaps to this grid so boards line up without effort."""

# Only two fonts, ever. Headings get the hand-drawn Excalifont; body text uses Nunito.
FONT_HEADING = 5
FONT_BODY = 6
FONT_MONO = 3

LINE_HEIGHT = 1.25

FONT_SIZES: Dict[str, int] = {
    "xl": 36,
    "lg": 28,
    "md": 20,
    "sm": 16,
    "xs": 13,
}

PADDING = 20
CARD_WIDTH = 320
PIN_DIAMETER = 44
STROKE_WIDTH = 1.5


@dataclass(frozen=True)
class AccentColors:
    fill: str
    stroke: str
    text: str


@dataclass(frozen=True)
class Palette:
    surface: str
    surface_alt: str
    border: str
    text: str
    text_muted: str
    accents: Dict[str, AccentColors]

    def accent(self, name: str) -> AccentColors:
        return self.accents.get(name, self.accents["indigo"])


LIGHT = Palette(
    surface="#ffffff",
    surface_alt="#f8fafc",
    border="#cbd5e1",
    text="#0f172a",
    text_muted="#64748b",
    accents={
        "indigo": AccentColors(fill="#e0e7ff", stroke="#4338ca", text="#312e81"),
        "coral": AccentColors(fill="#ffe4e6", stroke="#e11d48", text="#881337"),
        "amber": AccentColors(fill="#fef3c7", stroke="#d97706", text="#78350f"),
        "emerald": AccentColors(fill="#d1fae5", stroke="#059669", text="#064e3b"),
        "sky": AccentColors(fill="#e0f2fe", stroke="#0284c7", text="#0c4a6e"),
        "violet": AccentColors(fill="#ede9fe", stroke="#7c3aed", text="#4c1d95"),
        "rose": AccentColors(fill="#fce7f3", stroke="#db2777", text="#831843"),
        "slate": AccentColors(fill="#f1f5f9", stroke="#475569", text="#1e293b"),
    },
)

DARK = Palette(
    surface="#0f172a",
    surface_alt="#1e293b",
    border="#475569",
    text="#f1f5f9",
    text_muted="#94a3b8",
    accents={
        "indigo": AccentColors(fill="#1e1b4b", stroke="#818cf8", text="#c7d2fe"),
        "coral": AccentColors(fill="#4c0519", stroke="#fb7185", text="#fecdd3"),
        "amber": AccentColors(fill="#451a03", stroke="#fbbf24", text="#fde68a"),
        "emerald": AccentColors(fill="#022c22", stroke="#34d399", text="#a7f3d0"),
        "sky": AccentColors(fill="#082f49", stroke="#38bdf8", text="#bae6fd"),
        "violet": AccentColors(fill="#2e1065", stroke="#a78bfa", text="#ddd6fe"),
        "rose": AccentColors(fill="#500724", stroke="#f472b6", text="#fbcfe8"),
        "slate": AccentColors(fill="#1e293b", stroke="#94a3b8", text="#e2e8f0"),
    },
)

ACCENT_NAMES = tuple(LIGHT.accents.keys())


def palette_for(theme: str) -> Palette:
    return DARK if theme == "dark" else LIGHT


def snap(value: float, grid: int = GRID) -> float:
    """Snap to the nearest grid line."""
    return round(value / grid) * grid
