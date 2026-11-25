"""Code Mode tools: safe workspace editing, project intelligence, and terminals."""

from __future__ import annotations

import ast
import os
import re
from pathlib import Path
from typing import Any

from gd_core.project import ProjectIndex, inspect_project, minecraft_audit
from gd_core.terminal import ExecutionPolicy, TerminalManager
from gd_core.tool_registry import ToolContext, ToolRegistry, ToolSpec
from gd_core.workspace import Workspace


CURRENT_WORKSPACE: Path = Path.cwd().resolve()
EXTRA_REFERENCE_DIRS: list[Path] = []
_workspace: Workspace | None = None
_terminals = TerminalManager()
_policy = ExecutionPolicy()
_registry: ToolRegistry | None = None
_context: ToolContext | None = None
_settings: dict[str, Any] = {}


def set_workspace(path: str) -> bool:
    global CURRENT_WORKSPACE, _workspace, _registry, _context
    try:
        target = Path(path).expanduser().resolve()
        if not target.is_dir():
            return False
        CURRENT_WORKSPACE = target
        _workspace = Workspace(
            CURRENT_WORKSPACE,
            _settings.get("ignored_dirs", []),
            _context.task_id if _context else "default",
            [str(path) for path in EXTRA_REFERENCE_DIRS],
        )
        _registry, _context = _build_registry()
        return True
    except (OSError, ValueError):
        return False


def get_workspace() -> Path:
    return CURRENT_WORKSPACE


def set_extra_dirs(paths: list[str] | None) -> None:
    global EXTRA_REFERENCE_DIRS
    resolved: list[Path] = []
    for value in paths or []:
        try:
            candidate = Path(value).expanduser().resolve()
        except (OSError, ValueError):
            continue
        if candidate.is_dir():
            resolved.append(candidate)
    EXTRA_REFERENCE_DIRS = resolved
    if _workspace is not None:
        _workspace.reference_dirs = resolved


def configure_code_mode(
    path: str,
    settings: dict[str, Any] | None = None,
    approval_callback=None,
    event_callback=None,
    task_id: str = "default",
    checkpoints=None,
    plan=None,
) -> ToolContext:
    global _settings, _policy, _terminals, _context, _registry, CURRENT_WORKSPACE, _workspace
    _settings = dict(settings or {})
    CURRENT_WORKSPACE = Path(path).expanduser().resolve()
    _workspace = Workspace(
        CURRENT_WORKSPACE,
        _settings.get("ignored_dirs", []),
        task_id,
        [str(item) for item in EXTRA_REFERENCE_DIRS],
    )
    _policy = ExecutionPolicy(
        mode=str(_settings.get("permission_mode") or "project_autonomous"),
        allow_dependency_install=bool(_settings.get("allow_dependency_install", True)),
        approval_callback=approval_callback,
        approved_patterns=list(_settings.get("approved_patterns") or []),
    )
    if _settings.get("fresh_terminals", False):
        _terminals = TerminalManager()
    _context = ToolContext(_workspace, _terminals, _policy, task_id, event_callback, checkpoints, plan)
    _registry, _context = _build_registry()
    return _context


def get_context() -> ToolContext:
    if _context is None:
        configure_code_mode(str(Path.cwd()))
    return _context


def get_registry() -> ToolRegistry:
    if _registry is None:
        get_context()
    return _registry


def get_terminal_manager() -> TerminalManager:
    return _terminals


def get_workspace_object() -> Workspace:
    return get_context().workspace


def _schema(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required or []}


def _string(description: str, default: str | None = None) -> dict[str, Any]:
    return {"type": "string", "description": description}


def _integer(description: str, default: int | None = None) -> dict[str, Any]:
    return {"type": "integer", "description": description}


def _terminal_output(context: ToolContext, session_id: str, text: str) -> None:
    context.emit({"type": "terminal_output", "session_id": session_id, "text": text})


def _run_command(args: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    return context.terminals.run(
        args["command"],
        context.workspace.root,
        int(args.get("timeout_sec", 120)),
        args=args.get("args"),
        policy=context.policy,
        on_output=lambda sid, text: _terminal_output(context, sid, text),
        shell=args.get("shell"),
    )


def _build_registry() -> tuple[ToolRegistry, ToolContext]:
    context = get_context()
    workspace = context.workspace
    registry = ToolRegistry()

    def add(name: str, description: str, properties: dict[str, Any], handler, permission: str = "read", required=None) -> None:
        registry.register(ToolSpec(name, description, _schema(properties, required), handler, permission))

    add("list_directory", "List immediate files and folders, excluding ignored and sensitive paths.", {"relative_path": _string("Directory path.", "."), "max_entries": _integer("Maximum entries.", 200)}, lambda a, c: c.workspace.list_directory(a.get("relative_path", "."), a.get("max_entries", 200)))
    add("list_files", "Recursively list project files matching a filename glob.", {"relative_path": _string("Directory path.", "."), "pattern": _string("Filename glob.", "*"), "max_entries": _integer("Maximum files.", 500)}, lambda a, c: c.workspace.list_files(a.get("relative_path", "."), a.get("pattern", "*"), a.get("max_entries", 500)))
    add("read_file", "Read a text file with line numbers. Sensitive files are blocked.", {"file_path": _string("Workspace-relative or reference file path."), "start_line": _integer("First line.", 1), "end_line": _integer("Last line; omit for the whole file.")}, lambda a, c: c.workspace.read_file(a["file_path"], a.get("start_line", 1), a.get("end_line")), required=["file_path"])
    add("read_multiple_files", "Read several project files in one call.", {"file_paths": {"type": "array", "items": {"type": "string"}, "description": "File paths."}, "max_lines_each": _integer("Line limit per file.", 300)}, lambda a, c: c.workspace.read_multiple_files(a["file_paths"], a.get("max_lines_each", 300)), required=["file_paths"])
    add("search_files", "Search project filenames with a case-insensitive regex.", {"query": _string("Filename regex."), "relative_path": _string("Directory path.", "."), "max_results": _integer("Maximum matches.", 100)}, lambda a, c: c.workspace.search_files(a["query"], a.get("relative_path", "."), a.get("max_results", 100)), required=["query"])
    add("search_code", "Search text across project source files with a regex.", {"query": _string("Code regex."), "relative_path": _string("Directory path.", "."), "max_results": _integer("Maximum matches.", 80)}, lambda a, c: c.workspace.search_code(a["query"], a.get("relative_path", "."), a.get("max_results", 80)), required=["query"])
    add("inspect_project", "Detect languages, frameworks, manifests, entrypoints, dependencies, commands, and Minecraft metadata.", {}, lambda a, c: c.workspace.inspect_project())
    add("index_project", "Refresh the incremental project symbol/path index.", {"incremental": {"type": "boolean", "description": "Reuse unchanged file metadata."}}, lambda a, c: _index_project(a, c))
    add("relevant_files", "Find indexed files and symbols relevant to a query.", {"query": _string("Task or symbol query."), "limit": _integer("Maximum files.", 12)}, lambda a, c: _relevant_files(a, c), required=["query"])
    add("create_directory", "Create a project directory.", {"relative_path": _string("Directory path.")}, lambda a, c: c.workspace.create_directory(a["relative_path"]), "write", ["relative_path"])
    add("create_file", "Create a new file without overwriting an existing file.", {"file_path": _string("New file path."), "content": _string("UTF-8 file content.")}, lambda a, c: c.workspace.create_file(a["file_path"], a["content"]), "write", ["file_path", "content"])
    add("write_file", "Overwrite a file after storing a recoverable snapshot.", {"file_path": _string("File path."), "content": _string("New UTF-8 content."), "expected_sha256": _string("Optional hash from the prior read.")}, lambda a, c: c.workspace.write_file(a["file_path"], a["content"], a.get("expected_sha256")), "write", ["file_path", "content"])
    add("edit_file", "Replace one exact, unique text block in a file.", {"file_path": _string("File path."), "target_block": _string("Exact existing block."), "replacement_block": _string("Replacement block.")}, lambda a, c: c.workspace.edit_file(a["file_path"], a["target_block"], a["replacement_block"]), "write", ["file_path", "target_block", "replacement_block"])
    add("delete_file", "Delete a file after approval and snapshotting its previous bytes.", {"file_path": _string("File path.")}, lambda a, c: c.workspace.delete_file(a["file_path"]), "destructive", ["file_path"])
    add("move_file", "Move a file without overwriting the destination.", {"source_path": _string("Existing file."), "destination_path": _string("New file path.")}, lambda a, c: c.workspace.move_file(a["source_path"], a["destination_path"]), "write", ["source_path", "destination_path"])
    add("rename_file", "Rename a file within its current directory.", {"source_path": _string("Existing file."), "new_name": _string("New filename.")}, lambda a, c: c.workspace.rename_file(a["source_path"], a["new_name"]), "write", ["source_path", "new_name"])
    add("run_terminal_command", "Run a project command and return captured output and exit code.", {"command": _string("Command string."), "args": {"type": "array", "items": {"type": "string"}, "description": "Optional structured argv; avoids shell parsing."}, "timeout_sec": _integer("Timeout in seconds.", 120), "shell": {"type": "boolean", "description": "Explicitly request shell syntax."}}, _run_command, "execute", ["command"])
    add("start_terminal", "Start a long-running command and return its session ID.", {"command": _string("Command string."), "args": {"type": "array", "items": {"type": "string"}}, "timeout_sec": _integer("Timeout in seconds.", 300)}, lambda a, c: _start_terminal(a, c), "execute", ["command"])
    add("read_terminal_output", "Read current output and status for a terminal session.", {"session_id": _string("Terminal session ID.")}, lambda a, c: c.terminals.read_output(a["session_id"]), required=["session_id"])
    add("stop_terminal", "Terminate a running terminal process and its children.", {"session_id": _string("Terminal session ID.")}, lambda a, c: c.terminals.stop(a["session_id"]), "destructive", ["session_id"])
    add("git_status", "Show Git working-tree status when the project is a Git repository.", {}, lambda a, c: c.terminals.run("git status --short", c.workspace.root, 20, policy=c.policy), "execute")
    add("create_plan", "Create or replace the visible task plan for a substantial request.", {"request": _string("User request."), "steps": {"type": "array", "items": {"type": "string"}, "description": "Ordered implementation steps."}}, lambda a, c: _create_plan(a, c), required=["request", "steps"])
    add("update_plan", "Update one plan step's status or note.", {"step": _integer("One-based step number.", 1), "status": {"type": "string", "enum": ["pending", "in_progress", "completed", "failed", "blocked"]}, "note": _string("Optional progress note.")}, lambda a, c: _update_plan(a, c), required=["step", "status"])
    add("record_decision", "Record an important implementation decision in the task checkpoint.", {"decision": _string("Concise decision and reason.")}, lambda a, c: _record_decision(a, c), required=["decision"])
    add("list_changes", "List file changes made during this task, including diffs.", {}, lambda a, c: {"status": "SUCCESS", "message": f"{len(c.workspace.tracker.changes)} changes.", "changes": [change.to_dict() for change in c.workspace.tracker.changes]})
    add("accept_change", "Mark a file change as accepted.", {"change_id": _string("Change ID.")}, lambda a, c: c.workspace.tracker.accept(a["change_id"]), "write", ["change_id"])
    add("reject_change", "Reject and undo a file change if it has not been modified externally.", {"change_id": _string("Change ID.")}, lambda a, c: c.workspace.tracker.undo(a["change_id"]), "destructive", ["change_id"])
    add("undo_change", "Undo a file change if it has not been modified externally.", {"change_id": _string("Change ID.")}, lambda a, c: c.workspace.tracker.undo(a["change_id"]), "destructive", ["change_id"])
    return registry, context


def _index_project(args: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    index = getattr(context.workspace, "_project_index", None)
    if index is None:
        index = ProjectIndex(context.workspace)
        context.workspace._project_index = index
    return index.refresh(bool(args.get("incremental", True)))


def _relevant_files(args: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    _index_project({"incremental": True}, context)
    files = context.workspace._project_index.relevant_files(args["query"], int(args.get("limit", 12)))
    return {"status": "SUCCESS", "message": f"Found {len(files)} relevant indexed files.", "files": files}


def _start_terminal(args: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    return context.terminals.start(
        args["command"], context.workspace.root, int(args.get("timeout_sec", 300)),
        args=args.get("args"), policy=context.policy,
        on_output=lambda sid, text: _terminal_output(context, sid, text),
    )


def _record_decision(args: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    decision = str(args["decision"]).strip()
    if not decision:
        return {"status": "FAILURE", "message": "Decision cannot be empty."}
    context.decisions.append(decision)
    context.emit({"type": "decision", "decision": decision})
    return {"status": "SUCCESS", "message": "Decision recorded."}


def _create_plan(args: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    if context.plan is None:
        return {"status": "FAILURE", "message": "Task planner is not available."}
    context.plan.set_steps(args["request"], [str(step) for step in args["steps"]])
    context.emit({"type": "plan", "plan": context.plan.to_dict()})
    return {"status": "SUCCESS", "message": "Plan created.", "plan": context.plan.to_dict()}


def _update_plan(args: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    if context.plan is None:
        return {"status": "FAILURE", "message": "Task planner is not available."}
    result = context.plan.update(int(args["step"]), str(args["status"]), str(args.get("note", "")))
    context.emit({"type": "plan", "plan": context.plan.to_dict()})
    return result


def _is_python_source(content: str) -> bool:
    try:
        ast.parse(content)
    except (SyntaxError, TypeError, ValueError):
        return False
    return True


def _prepare_python_command(command: str) -> tuple[str, bool]:
    match = re.match(r'^\s*(?P<python>python(?:\.exe)?|py(?:\.exe)?)\s+(?P<script>"[^"]+"|\S+)(?P<args>.*)$', command, flags=re.I)
    if not match:
        return command, False
    script = match.group("script").strip('"')
    candidate = Path(script)
    resolved = candidate if candidate.is_absolute() else CURRENT_WORKSPACE / candidate
    if not resolved.exists() and not candidate.suffix and resolved.with_suffix(".py").exists():
        resolved = resolved.with_suffix(".py")
    if not resolved.is_file() or resolved.suffix.lower() != ".py":
        return command, False
    normalized = f'{match.group("python")} "{resolved}"{match.group("args")}'.strip()
    try:
        source = resolved.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return normalized, False
    return normalized, bool(re.search(r"\binput\s*\(", source))


def list_directory(relative_path: str = ".", max_entries: int = 60) -> dict[str, Any]:
    result = get_workspace_object().list_directory(relative_path, max_entries)
    if result.get("entries"):
        result["message"] = "\n".join(f"[{item['type']}] {item['path']}" for item in result["entries"])
    return result


def read_file_range(file_path: str, start_line: int = 1, end_line: int = 200) -> dict[str, Any]:
    return get_workspace_object().read_file(file_path, start_line, end_line)


def edit_file_replace(file_path: str, target_block: str, replacement_block: str) -> dict[str, Any]:
    return get_workspace_object().edit_file(file_path, target_block, replacement_block)


def write_new_file(file_path: str, content: str) -> dict[str, Any]:
    return get_workspace_object().create_file(file_path, content)


def search_code(query: str, relative_path: str = ".") -> dict[str, Any]:
    return get_workspace_object().search_code(query, relative_path)


def run_terminal_command(command: str, timeout_sec: int = 45) -> dict[str, Any]:
    return _run_command({"command": command, "timeout_sec": timeout_sec}, get_context())


# Compatibility exports used by the original agent and external scripts.
_default_context = get_context()
_default_registry = get_registry()
CODING_TOOL_DECLARATIONS = _default_registry.declarations()
CODING_TOOL_REGISTRY = {
    spec.name: (lambda args, name=spec.name: get_registry().execute(name, args, get_context()))
    for spec in _default_registry.specs()
}
