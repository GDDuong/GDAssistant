"""Shared visual palettes for GD Assistant's Chat and Code interfaces."""

from __future__ import annotations

import re
from typing import Final

THEMES: Final = {
    "dark": {
        "background": "#1e1e1e",
        "panel": "#252526",
        "input": "#3c3c3c",
        "foreground": "#d4d4d4",
        "muted": "#9cdcfe",
        "border": "#444444",
        "accent": "#007acc",
        "accent_active": "#005a9e",
        "button": "#333333",
        "button_active": "#444444",
        "user": "#4ec9b0",
        "mention": "#9cdcfe",
        "error": "#f48771",
        "working": "#ca5010",
    },
    "light": {
        "background": "#f6f8fa",
        "panel": "#ffffff",
        "input": "#ffffff",
        "foreground": "#24292f",
        "muted": "#0969da",
        "border": "#d0d7de",
        "accent": "#0969da",
        "accent_active": "#0550ae",
        "button": "#f6f8fa",
        "button_active": "#eaeef2",
        "user": "#0a7f57",
        "mention": "#007acc",
        "error": "#cf222e",
        "working": "#9a6700",
    },
}


ACCENT_PRESETS: Final = (
    "#007acc",
    "#0969da",
    "#7c3aed",
    "#db2777",
    "#dc2626",
    "#ea580c",
    "#16a34a",
    "#0891b2",
)


def is_hex_color(value: str) -> bool:
    return re.fullmatch(r"#[0-9a-fA-F]{6}", str(value).strip()) is not None


def get_theme(name: str, accent_color: str | None = None) -> dict[str, str]:
    """Return a known palette, falling back safely to dark mode."""
    palette = dict(THEMES.get(str(name).lower(), THEMES["dark"]))
    accent = str(accent_color or "").strip()
    if is_hex_color(accent):
        palette["accent"] = accent.lower()
        red, green, blue = (int(accent[index:index + 2], 16) for index in (1, 3, 5))
        palette["accent_active"] = "#{:02x}{:02x}{:02x}".format(
            int(red * 0.75), int(green * 0.75), int(blue * 0.75)
        )
    return palette
