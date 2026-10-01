"""Shared visual palettes for GD Assistant's Chat and Code interfaces."""

from __future__ import annotations

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
        "error": "#cf222e",
        "working": "#9a6700",
    },
}


def get_theme(name: str) -> dict[str, str]:
    """Return a known palette, falling back safely to dark mode."""
    return THEMES.get(str(name).lower(), THEMES["dark"])
