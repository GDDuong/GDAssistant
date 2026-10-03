"""Shared helpers for attaching local files to Chat and Code mode messages."""

from __future__ import annotations

import html as html_module
import mimetypes
import re
import zipfile
from pathlib import Path
from typing import Any

MAX_INLINE_CHARS = 50_000

OFFICE_SUFFIXES = {".docx", ".xlsx", ".pptx"}


def _log(debug: bool, message: str) -> None:
    if debug:
        print(f"[ATTACH] {message}")


def prepare_message(text: str, file_paths: list[Any], debug: bool = False) -> tuple[str, list[Path]]:
    """Build the model-facing message and list any non-text files.

    Readable text files (and Word/Excel/PowerPoint documents, whose text is
    extracted locally) are inlined as fenced blocks so they persist in chat
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
            _log(debug, f"Inlining text from '{path}' ({len(content)} chars)")
            sections.append(f"Attached file: {path}\n```\n{content}\n```")
        else:
            _log(debug, f"Sending '{path}' as a binary attachment")
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


def load_binary_parts(file_paths: list[Any], debug: bool = False) -> list[Any]:
    """Load non-text files as Gemini inline-data parts; unreadable files are skipped."""
    from google.genai import types

    parts: list[Any] = []
    for path in file_paths:
        path = Path(path)
        try:
            data = path.read_bytes()
        except OSError as error:
            _log(debug, f"Skipped unreadable file '{path}': {error}")
            continue
        mime_type, _ = mimetypes.guess_type(str(path))
        mime_type = mime_type or "application/octet-stream"
        _log(debug, f"Loaded '{path}' as {mime_type} ({len(data)} bytes)")
        parts.append(types.Part.from_bytes(data=data, mime_type=mime_type))
    return parts


def _read_text_file(path: Path) -> str | None:
    try:
        raw = path.read_bytes()
    except OSError:
        return None

    if path.suffix.lower() in OFFICE_SUFFIXES:
        text = _extract_office_text(raw)
    else:
        # Control bytes outside tab/newline/CR mark a file as binary; anything
        # left is decoded strictly as UTF-8, falling back to the Windows
        # Vietnamese legacy codepage before being inlined.
        if any(byte < 32 and byte not in (9, 10, 13) for byte in raw):
            return None
        text = None
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            try:
                text = raw.decode("cp1252")
            except UnicodeDecodeError:
                text = None
    if text is None:
        return None
    if len(text) > MAX_INLINE_CHARS:
        return text[:MAX_INLINE_CHARS] + "\n...[file truncated]"
    return text


def _extract_office_text(raw: bytes) -> str | None:
    """Pull readable text out of Word/Excel/PowerPoint XML archives."""
    import io

    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
    except (zipfile.BadZipFile, OSError):
        return None
    try:
        doc = _archive_member_text(archive, "word/document.xml")
        if doc is not None:
            paragraphs = []
            for chunk in doc.split("</w:p>"):
                runs = re.findall(r"<w:t(?: [^>]*)?>(.*?)</w:t>", chunk, re.DOTALL)
                if runs:
                    paragraphs.append("".join(_unescape(run) for run in runs))
            return "\n".join(paragraphs) or None

        slide_names = sorted(
            (int(match.group(1)), info.filename)
            for info in archive.infolist()
            if (match := re.fullmatch(r"ppt/slides/slide(\d+)\.xml", info.filename))
        )
        if slide_names:
            blocks = []
            for number, name in slide_names:
                xml = _archive_member_text(archive, name) or ""
                texts = re.findall(r"<a:t(?: [^>]*)?>(.*?)</a:t>", xml, re.DOTALL)
                blocks.append(f"--- Slide {number} ---\n" + "\n".join(_unescape(item) for item in texts))
            return "\n\n".join(blocks) or None

        sheet_names = sorted(
            (int(match.group(1)), info.filename)
            for info in archive.infolist()
            if (match := re.fullmatch(r"xl/worksheets/sheet(\d+)\.xml", info.filename))
        )
        if sheet_names:
            shared = _shared_strings(archive)
            blocks = []
            for number, name in sheet_names:
                xml = _archive_member_text(archive, name) or ""
                rows = []
                for row_body in re.findall(r"<row[^>]*>(.*?)</row>", xml, re.DOTALL):
                    cells = [_cell_value(attrs, body, shared) for attrs, body in
                             re.findall(r"<c([^>]*?)(?:/>|>(.*?)</c>)", row_body, re.DOTALL)]
                    cells = [value for value in cells if value]
                    if cells:
                        rows.append(" | ".join(cells))
                blocks.append(f"--- Sheet {number} ---\n" + "\n".join(rows))
            return "\n\n".join(blocks) or None
    finally:
        archive.close()
    return None


def _archive_member_text(archive: zipfile.ZipFile, name: str) -> str | None:
    try:
        return archive.read(name).decode("utf-8", "replace")
    except KeyError:
        return None


def _shared_strings(archive: zipfile.ZipFile) -> list[str]:
    xml = _archive_member_text(archive, "xl/sharedStrings.xml") or ""
    return [_unescape(item) for item in re.findall(r"<t(?: [^>]*)?>(.*?)</t>", xml, re.DOTALL)]


def _cell_value(attrs: str, body: str | None, shared: list[str]) -> str:
    body = body or ""
    if 't="s"' in attrs:
        index = re.search(r"<v>(.*?)</v>", body, re.DOTALL)
        if index:
            try:
                return shared[int(index.group(1))]
            except (ValueError, IndexError):
                return ""
        return ""
    if 't="inlineStr"' in attrs:
        return "".join(_unescape(item) for item in re.findall(r"<t(?: [^>]*)?>(.*?)</t>", body, re.DOTALL))
    value = re.search(r"<v>(.*?)</v>", body, re.DOTALL)
    return _unescape(value.group(1)) if value else ""


def _unescape(fragment: str) -> str:
    return html_module.unescape(fragment)
