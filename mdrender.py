"""mdrender.py: Lightweight markdown rendering for Tkinter Text widgets."""

from __future__ import annotations

import re
import tkinter as tk
from typing import Any

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_BULLET_RE = re.compile(r"^(\s*)[-*+]\s+(.*)$")
_ORDERED_RE = re.compile(r"^(\s*)(\d+)[.)]\s+(.*)$")
_INLINE_RE = re.compile(
    r"(?P<code>`[^`\n]+`)"
    r"|(?P<bold>\*\*[^*\n]+\*\*)"
    r"|(?P<italic>\*[^*\n]+\*)"
    r"|(?P<link>\[[^\]\n]+\]\([^)\n]+\))"
)
_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


def configure_tags(widget: Any, palette: dict[str, str], family: str = "Segoe UI", size: int = 10) -> None:
    """Create (or refresh, e.g. after a theme change) the md_* display tags."""
    widget.tag_configure("md_h1", font=(family, size + 3, "bold"), spacing1=6, spacing3=2)
    widget.tag_configure("md_h2", font=(family, size + 2, "bold"), spacing1=5, spacing3=2)
    widget.tag_configure("md_h3", font=(family, size + 1, "bold"), spacing1=4, spacing3=1)
    widget.tag_configure("md_bold", font=(family, size, "bold"))
    widget.tag_configure("md_italic", font=(family, size, "italic"))
    widget.tag_configure(
        "md_code",
        font=("Consolas", max(size - 1, 8)),
        background=palette.get("input", "#1e1e1e"),
    )
    widget.tag_configure(
        "md_link",
        foreground=palette.get("accent", "#4f8cff"),
        underline=True,
    )


def insert_markdown(widget: Any, text: str, base_tag: str = "", index: Any = None) -> None:
    """Render markdown text into a Text widget, optionally under a base tag."""

    def emit(chunk: str, md_tag: str | None = None) -> None:
        if not chunk:
            return
        tags: Any = ()
        if base_tag and md_tag:
            tags = (base_tag, md_tag)
        elif md_tag:
            tags = md_tag
        elif base_tag:
            tags = base_tag
        widget.insert(index if index is not None else tk.END, chunk, tags)

    def emit_inline(source: str) -> None:
        position = 0
        for match in _INLINE_RE.finditer(source):
            if match.start() > position:
                emit(source[position:match.start()])
            piece = match.group(0)
            if match.group("code"):
                emit(piece[1:-1], "md_code")
            elif match.group("bold"):
                emit(piece[2:-2], "md_bold")
            elif match.group("italic"):
                emit(piece[1:-1], "md_italic")
            else:
                link = _LINK_RE.match(piece)
                emit(link.group(1) if link else piece, "md_link")
            position = match.end()
        if position < len(source):
            emit(source[position:])

    in_fence = False
    pending_separator = False
    for line in text.split("\n"):
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if pending_separator:
            emit("\n")
        pending_separator = True
        if in_fence:
            emit(line, "md_code")
            continue
        heading = _HEADING_RE.match(line)
        if heading:
            emit(heading.group(2), f"md_h{min(len(heading.group(1)), 3)}")
            continue
        bullet = _BULLET_RE.match(line)
        if bullet:
            emit(bullet.group(1) + "\u2022 ")
            emit_inline(bullet.group(2))
            continue
        ordered = _ORDERED_RE.match(line)
        if ordered:
            emit(ordered.group(1) + ordered.group(2) + ". ")
            emit_inline(ordered.group(3))
            continue
        emit_inline(line)


def strip_markdown(text: str) -> str:
    """Reduce markdown to readable plain text (for voice display and TTS)."""
    text = re.sub(r"^```.*\n?", "", text, flags=re.MULTILINE)
    text = re.sub(r"(`+)([^`]+)\1", r"\2", text)
    text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^(\s*)[-*+]\s+", r"\1", text, flags=re.MULTILINE)
    text = re.sub(r"^(\s*)\d+[.)]\s+", r"\1", text, flags=re.MULTILINE)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"\*([^*\n]+)\*", r"\1", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
