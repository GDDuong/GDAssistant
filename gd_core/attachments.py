"""Shared helpers for attaching local files to Chat and Code mode messages."""

from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any

MAX_INLINE_CHARS = 50_000


def prepare_message(text: str, file_paths: list[Any]) -> tuple[str, list[Path]]:
    """Build the model-facing message and list any non-text files.

    Readable text files are inlined as fenced blocks so they persist in chat
    history; images/PDFs are returned as paths for load_binary_parts().
    """
    paths = [Path(path) for path in file_paths]
    if not paths:
        return text, []

    sections: list[str] = []
    binary_paths: list[Path] = []
    for path in paths:
        content = _read_text_file(path)
        if content is not None:
            sections.append(f"Attached file: {path}\n```\n{content}\n```")
        else:
            binary_paths.append(path)

    if binary_paths:
        names = ", ".join(str(path) for path in binary_paths)
        sections.append(f"Attached files sent separately as attachments: {names}")

    body = text.strip()
    joined = "\n\n".join(sections)
    request_text = f"{body}\n\n{joined}" if body else joined
    return request_text, binary_paths


def display_summary(file_paths: list[Any]) -> str:
    """Short on-screen note listing attached file names."""
    names = ", ".join(Path(path).name for path in file_paths)
    return f"[Attached: {names}]"


def load_binary_parts(file_paths: list[Any]) -> list[Any]:
    """Load non-text files as Gemini inline-data parts; unreadable files are skipped."""
    from google.genai import types

    parts: list[Any] = []
    for path in file_paths:
        path = Path(path)
        try:
            data = path.read_bytes()
        except OSError:
            continue
        mime_type, _ = mimetypes.guess_type(str(path))
        parts.append(types.Part.from_bytes(data=data, mime_type=mime_type or "application/octet-stream"))
    return parts


def _read_text_file(path: Path) -> str | None:
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    # Control bytes outside tab/newline/CR mark a file as binary; anything
    # left is decoded strictly as UTF-8, falling back to the Windows
    # Vietnamese legacy codepage before being inlined.
    if any(byte < 32 and byte not in (9, 10, 13) for byte in raw):
        return None
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        try:
            text = raw.decode("cp1252")
        except UnicodeDecodeError:
            return None
    if len(text) > MAX_INLINE_CHARS:
        return text[:MAX_INLINE_CHARS] + "\n...[file truncated]"
    return text
