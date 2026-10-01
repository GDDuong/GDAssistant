"""coding_tools.py: Repository navigation, surgical file editing, and test execution."""

from __future__ import annotations

import ast
import os
import re
import subprocess
from pathlib import Path
from typing import Any

# Global workspace directory anchor
CURRENT_WORKSPACE: Path = Path.cwd().resolve()

def set_workspace(path: str) -> bool:
    """Set the active workspace directory for coding operations."""
    global CURRENT_WORKSPACE
    target = Path(path).resolve()
    if target.exists() and target.is_dir():
        CURRENT_WORKSPACE = target
        return True
    return False

def get_workspace() -> Path:
    return CURRENT_WORKSPACE

def _resolve_safe_path(rel_or_abs_path: str) -> Path | None:
    """Ensure file paths stay within the active workspace boundary."""
    try:
        candidate = Path(rel_or_abs_path)
        target = candidate if candidate.is_absolute() else (CURRENT_WORKSPACE / candidate)
        target = target.resolve()
        # Must be equal to or inside CURRENT_WORKSPACE
        if CURRENT_WORKSPACE in target.parents or target == CURRENT_WORKSPACE:
            return target
        return None
    except Exception:
        return None

def list_directory(relative_path: str = ".", max_entries: int = 60) -> dict[str, Any]:
    """List directory contents, filtering out common build/cache folders."""
    target_dir = _resolve_safe_path(relative_path)
    if not target_dir or not target_dir.is_dir():
        return {"status": "FAILURE", "message": f"Invalid workspace directory: {relative_path}"}

    ignored = {".git", ".venv", "venv", "__pycache__", "node_modules", "dist", "build", ".idea", ".vscode"}
    results = []

    try:
        entries = sorted(os.scandir(target_dir), key=lambda e: (not e.is_dir(), e.name.lower()))
        for entry in entries:
            if entry.name in ignored:
                continue
            item_type = "DIR " if entry.is_dir() else "FILE"
            size = f"({entry.stat().st_size} bytes)" if entry.is_file() else ""
            rel = os.path.relpath(entry.path, CURRENT_WORKSPACE)
            results.append(f"[{item_type}] {rel} {size}".strip())
            if len(results) >= max_entries:
                results.append(f"... (truncated at {max_entries} items)")
                break

        return {"status": "SUCCESS", "message": "\n".join(results) if results else "Directory is empty."}
    except Exception as e:
        return {"status": "FAILURE", "message": f"Failed listing directory: {e}"}

def read_file_range(file_path: str, start_line: int = 1, end_line: int = 200) -> dict[str, Any]:
    """Read a slice of source code with 1-based line numbers."""
    target = _resolve_safe_path(file_path)
    if not target or not target.is_file():
        return {"status": "FAILURE", "message": f"File not found within workspace: {file_path}"}

    try:
        with open(target, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()

        total = len(lines)
        start = max(1, start_line)
        end = min(total, end_line)

        if start > total:
            return {"status": "FAILURE", "message": f"Start line {start} exceeds total lines ({total})."}

        numbered = [f"{i:4d} | {lines[i-1].rstrip()}" for i in range(start, end + 1)]
        rel_path = os.path.relpath(target, CURRENT_WORKSPACE)
        output = f"File: {rel_path} (Lines {start}-{end} of {total})\n" + "\n".join(numbered)
        return {"status": "SUCCESS", "message": output}
    except Exception as e:
        return {"status": "FAILURE", "message": f"Error reading file: {e}"}

def edit_file_replace(file_path: str, target_block: str, replacement_block: str) -> dict[str, Any]:
    """Surgically replace a unique block of code, preserving line endings (CRLF/LF)."""
    target = _resolve_safe_path(file_path)
    if not target or not target.is_file():
        return {"status": "FAILURE", "message": f"File not found: {file_path}"}

    try:
        with open(target, "r", encoding="utf-8") as f:
            raw_content = f.read()

        is_crlf = "\r\n" in raw_content
        norm_content = raw_content.replace("\r\n", "\n")
        norm_target = target_block.replace("\r\n", "\n")
        norm_replacement = replacement_block.replace("\r\n", "\n")

        occurrences = norm_content.count(norm_target)
        if occurrences == 0:
            return {
                "status": "FAILURE",
                "message": (
                    "Target block not found. Ensure exact matching of indentation, "
                    "spacing, and surrounding context lines."
                )
            }
        if occurrences > 1:
            return {
                "status": "FAILURE",
                "message": (
                    f"Target block matched {occurrences} times. Include more surrounding lines "
                    "to make the replacement location unique."
                )
            }

        new_norm_content = norm_content.replace(norm_target, norm_replacement, 1)
        final_content = new_norm_content.replace("\n", "\r\n") if is_crlf else new_norm_content

        with open(target, "w", encoding="utf-8") as f:
            f.write(final_content)

        return {"status": "SUCCESS", "message": f"Successfully updated {file_path}."}
    except Exception as e:
        return {"status": "FAILURE", "message": f"Failed editing file: {e}"}

def write_new_file(file_path: str, content: str) -> dict[str, Any]:
    """Create a new file or completely overwrite an existing one.

    Extensionless content that is valid Python becomes ``.py`` automatically.
    This protects the common "create a Python file named hello" case from
    producing an extensionless file that is awkward to run on Windows.
    """
    target = _resolve_safe_path(file_path)
    if not target:
        return {"status": "FAILURE", "message": f"Cannot write outside workspace: {file_path}"}

    added_python_suffix = False
    if not target.suffix and not target.name.startswith(".") and _is_python_source(content):
        target = target.with_suffix(".py")
        added_python_suffix = True

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            f.write(content)
        suffix_note = " Added the .py extension for Python source." if added_python_suffix else ""
        return {
            "status": "SUCCESS",
            "message": f"Wrote {len(content)} characters to {target.name}.{suffix_note}",
        }
    except Exception as e:
        return {"status": "FAILURE", "message": f"Failed writing file: {e}"}


def _is_python_source(content: str) -> bool:
    """Return whether text parses as Python source for extension normalization."""
    try:
        ast.parse(content)
    except (SyntaxError, TypeError, ValueError):
        return False
    return True

def search_code(query: str, relative_path: str = ".") -> dict[str, Any]:
    """Search for regex or text matches across project files."""
    target_dir = _resolve_safe_path(relative_path)
    if not target_dir or not target_dir.is_dir():
        return {"status": "FAILURE", "message": f"Directory not found: {relative_path}"}

    matches = []
    ignored = {".git", ".venv", "venv", "__pycache__", "node_modules", "dist", "build"}

    try:
        pattern = re.compile(query, re.IGNORECASE)
        for root, dirs, files in os.walk(target_dir):
            dirs[:] = [d for d in dirs if d not in ignored]
            for file_name in files:
                ext = os.path.splitext(file_name)[1].lower()
                if ext in {".exe", ".dll", ".pyd", ".png", ".jpg", ".zip", ".pyc", ".ico"}:
                    continue
                full_path = Path(root) / file_name
                try:
                    with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                        for line_no, line in enumerate(f, start=1):
                            if pattern.search(line):
                                rel = os.path.relpath(full_path, CURRENT_WORKSPACE)
                                matches.append(f"{rel}:{line_no} | {line.strip()[:140]}")
                                if len(matches) >= 35:
                                    break
                except Exception:
                    continue
            if len(matches) >= 35:
                break

        if not matches:
            return {"status": "SUCCESS", "message": f"No code matches found for '{query}'."}
        return {"status": "SUCCESS", "message": "\n".join(matches)}
    except Exception as e:
        return {"status": "FAILURE", "message": f"Search error: {e}"}

def run_terminal_command(command: str, timeout_sec: int = 45) -> dict[str, Any]:
    """Execute bash/powershell commands (pytest, git, python, npm) in the workspace root."""
    blocked = ["format", "rmdir /s /q c:", "del /f /s /q c:", ":(){ :|:& };:"]
    clean_cmd = command.strip().lower()
    for b in blocked:
        if b in clean_cmd:
            return {"status": "FAILURE", "message": f"Command blocked by safety guardrail: {command}"}

    command, requires_enter = _prepare_python_command(command)

    try:
        run_options: dict[str, Any] = {
            "shell": True,
            "cwd": CURRENT_WORKSPACE,
            "capture_output": True,
            "text": True,
            "timeout": timeout_sec,
        }
        # Preserve pause behavior for the user's own terminal. For the agent's
        # verification run, provide one simulated Enter so input() cannot stall.
        if requires_enter:
            # ``input=`` creates its own stdin pipe in subprocess.run.
            run_options["input"] = "\n"
        else:
            run_options["stdin"] = subprocess.DEVNULL
        proc = subprocess.run(
            command,
            **run_options,
        )
        stdout = proc.stdout.strip()
        stderr = proc.stderr.strip()
        code = proc.returncode

        max_len = 4000
        if len(stdout) > max_len:
            stdout = stdout[:max_len] + "\n...[stdout truncated]..."
        if len(stderr) > max_len:
            stderr = stderr[:max_len] + "\n...[stderr truncated]..."

        msg = f"Exit code: {code}"
        if stdout:
            msg += f"\n[STDOUT]:\n{stdout}"
        if stderr:
            msg += f"\n[STDERR]:\n{stderr}"

        return {
            "status": "SUCCESS" if code == 0 else "FAILURE",
            "message": msg,
            "returncode": code,
        }
    except subprocess.TimeoutExpired:
        return {"status": "FAILURE", "message": f"Command timed out after {timeout_sec}s."}
    except Exception as e:
        return {"status": "FAILURE", "message": f"Execution failed: {e}"}


def _prepare_python_command(command: str) -> tuple[str, bool]:
    """Normalize simple Python script commands and detect an input() pause.

    This accepts ``python hello`` when the created source is ``hello.py``. The
    caller can supply a single simulated Enter while testing a program that
    intentionally uses input() to pause for its real user.
    """
    match = re.match(
        r'^\s*(?P<python>python(?:\.exe)?|py(?:\.exe)?)\s+(?P<script>"[^"]+"|\S+)(?P<args>.*)$',
        command,
        flags=re.IGNORECASE,
    )
    if not match:
        return command, False

    script_text = match.group("script").strip('"')
    candidate = Path(script_text)
    resolved = candidate if candidate.is_absolute() else CURRENT_WORKSPACE / candidate
    if not resolved.exists() and not candidate.suffix:
        python_candidate = resolved.with_suffix(".py")
        if python_candidate.exists():
            resolved = python_candidate

    if not resolved.is_file() or resolved.suffix.lower() != ".py":
        return command, False

    normalized_command = (
        f'{match.group("python")} "{resolved}"{match.group("args")} '
    ).strip()
    try:
        source = resolved.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return normalized_command, False

    return normalized_command, bool(re.search(r"\binput\s*\(", source))


CODING_TOOL_DECLARATIONS = [
    {
        "name": "list_directory",
        "description": "Lists files and subdirectories in the workspace project tree.",
        "parameters": {
            "type": "object",
            "properties": {
                "relative_path": {"type": "string", "description": "Relative directory path (default is '.')."}
            },
        },
    },
    {
        "name": "read_file_range",
        "description": "Reads lines from a file with line numbers. Use this to inspect code before modifying it.",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Workspace relative path."},
                "start_line": {"type": "integer", "description": "Line to start reading from (1-based)."},
                "end_line": {"type": "integer", "description": "Line to stop reading."},
            },
            "required": ["file_path"],
        },
    },
    {
        "name": "edit_file_replace",
        "description": "Surgically replaces an exact, unique target code block with a replacement block.",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Workspace relative path."},
                "target_block": {"type": "string", "description": "The exact lines to be replaced."},
                "replacement_block": {"type": "string", "description": "The new replacement lines."},
            },
            "required": ["file_path", "target_block", "replacement_block"],
        },
    },
    {
        "name": "write_new_file",
        "description": "Creates a new file or completely replaces an existing file with the given content. Use a .py suffix for Python programs.",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Relative file path."},
                "content": {"type": "string", "description": "Full file content."},
            },
            "required": ["file_path", "content"],
        },
    },
    {
        "name": "search_code",
        "description": "Searches for regex/text patterns across all project source files.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Text or regex string to locate."},
                "relative_path": {"type": "string", "description": "Subdirectory to scan (default is '.')."},
            },
            "required": ["query"],
        },
    },
    {
        "name": "run_terminal_command",
        "description": "Runs a terminal command (e.g. pytest, python, git, npm) within the workspace root.",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Terminal command string to run."},
                "timeout_sec": {"type": "integer", "description": "Timeout in seconds (default 45)."},
            },
            "required": ["command"],
        },
    },
]

CODING_TOOL_REGISTRY = {
    "list_directory": lambda args: list_directory(args.get("relative_path", ".")),
    "read_file_range": lambda args: read_file_range(
        args["file_path"],
        int(args.get("start_line", 1)),
        int(args.get("end_line", 200)),
    ),
    "edit_file_replace": lambda args: edit_file_replace(
        args["file_path"],
        args["target_block"],
        args["replacement_block"],
    ),
    "write_new_file": lambda args: write_new_file(args["file_path"], args["content"]),
    "search_code": lambda args: search_code(args["query"], args.get("relative_path", ".")),
    "run_terminal_command": lambda args: run_terminal_command(
        args["command"],
        int(args.get("timeout_sec", 45)),
    ),
}
