"""Functional slash commands shared by Code Mode GUI and CLI."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from gd_core.project import ProjectIndex, inspect_project, minecraft_audit
from gd_core.task_state import TaskPlan
from gd_core.translations import get_text


@dataclass
class CommandResult:
    handled: bool = True
    text: str = ""
    prompt: str = ""
    plan_only: bool = False
    read_only: bool = False
    action: str = ""
    command: str = ""
    payload: dict[str, Any] = field(default_factory=dict)


class CodeCommandRouter:
    def __init__(self, session: Any, lang: str = "en") -> None:
        self.session = session
        self.lang = lang

    def _raw(self, key: str) -> str:
        return get_text(key, self.lang)

    def _t(self, key: str, **values: Any) -> str:
        return self._raw(key).format(**values)

    def route(self, value: str) -> CommandResult:
        text = value.strip()
        if not text.startswith("/"):
            return CommandResult(handled=False)
        command, _, argument = text.partition(" ")
        command = command.casefold()
        argument = argument.strip()
        if command in {"/exit", "/quit", "/q"}:
            return CommandResult(action="exit")
        if command == "/help":
            return CommandResult(text=self._t("code_cmd_help"))
        if command == "/model":
            if argument:
                self.session.model = argument
                self.session.rebuild_config()
                return CommandResult(text=self._t("code_cmd_model", model=argument))
            return CommandResult(text=self._t("code_cmd_model", model=self.session.model))
        if command == "/cd":
            return CommandResult(action="workspace", payload={"path": argument})
        if command == "/plan":
            if argument:
                return CommandResult(prompt=f"Create an implementation plan only for this request; do not modify files or run commands:\n{argument}", plan_only=True)
            return CommandResult(text=_format_plan(self.session.plan, self.lang))
        if command == "/status":
            return CommandResult(text=self._status())
        if command == "/context":
            return CommandResult(text=self._context())
        if command == "/stop":
            self.session.context.terminals.stop_all()
            return CommandResult(action="stop", text=self._t("code_cmd_stop"))
        if command == "/continue":
            checkpoint = self.session.checkpoints.latest()
            if checkpoint is None:
                return CommandResult(text=self._t("code_cmd_no_checkpoint"))
            self.session.resume_checkpoint(checkpoint)
            pending = checkpoint.get("pending_steps") or []
            return CommandResult(prompt="Continue the interrupted task from its checkpoint. Re-read the relevant files before changing anything.\nPending steps:\n" + "\n".join(f"- {step}" for step in pending))
        if command in {"/explain", "/debug", "/review", "/refactor", "/audit"}:
            scope = argument or "the current project"
            prompts = {
                "/explain": f"Explain {scope} using real file reads. Do not modify files or run commands.",
                "/debug": f"Investigate and fix the current errors in {scope}. Preserve the original error output, inspect relevant files, apply a focused fix, and rerun verification.",
                "/review": f"Review {scope} for correctness, security, and maintainability. Report concrete findings with file references; do not modify files.",
                "/refactor": f"Refactor {scope} without changing behavior. Inspect first, make focused edits, and run relevant verification.",
                "/audit": f"Audit {scope} read-only for bugs, security issues, missing tests, and compatibility problems. Do not modify files or run mutating commands.",
            }
            return CommandResult(prompt=prompts[command], read_only=command in {"/explain", "/review", "/audit"})
        if command.startswith("/mod-"):
            return self._minecraft(command, argument)
        return CommandResult(text=self._t("code_cmd_unknown", command=command))

    def _status(self) -> str:
        workspace = self.session.context.workspace
        plan = self.session.plan.to_dict()
        active = [session.id for session in self.session.context.terminals.sessions.values() if session.exit_code is None]
        return self._t(
            "code_cmd_status", workspace=workspace.root, model=self.session.model,
            completed=plan["completed"], total=plan["total"],
            modified=len(self.session.modified_files), running=len(active),
        )

    def _context(self) -> str:
        workspace = self.session.context.workspace
        project = inspect_project(workspace.root)
        index = getattr(workspace, "_project_index", None)
        if index is None:
            from gd_core.project import ProjectIndex

            index = ProjectIndex(workspace)
            workspace._project_index = index
        index.refresh(incremental=True)
        summary = index.summary()
        return project["summary"] + "\n" + self._t("code_cmd_index", files=summary["files"], symbols=summary["symbols"]) + "\n" + (project.get("instructions") or self._t("code_cmd_context_no_instructions"))

    def _minecraft(self, command: str, argument: str) -> CommandResult:
        workspace = self.session.context.workspace
        info = inspect_project(workspace.root).get("minecraft")
        if not info:
            return CommandResult(text=self._t("code_cmd_not_minecraft"))
        if command == "/mod-info":
            return CommandResult(text=_format_mod(info, self.lang))
        if command == "/mod-deps":
            dependencies = info.get("dependencies") or {}
            rendered = "\n".join(f"- {name}: {value}" for name, value in dependencies.items()) or self._t("code_cmd_none_dependencies")
            return CommandResult(text=self._t("code_cmd_dependencies", dependencies=rendered))
        if command == "/mod-mappings":
            return CommandResult(text=self._t(
                "code_cmd_mappings", mappings=info.get("mappings") or self._raw("code_cmd_not_declared"),
                system=info.get("mapping_system") or self._raw("code_cmd_unknown_value"),
                minecraft=info.get("minecraft_version") or self._raw("code_cmd_unknown_value"),
                java=info.get("java_version") or self._raw("code_cmd_unknown_value"),
            ))
        if command == "/mod-audit":
            audit = minecraft_audit(workspace.root)
            issues = audit.get("issues") or []
            rendered = "\n".join(f"- {issue}" for issue in issues) if issues else self._t("code_cmd_audit_ok")
            return CommandResult(text=self._t("code_cmd_audit", issues=rendered))
        if command in {"/mod-build", "/mod-test", "/mod-run"}:
            key = {"/mod-build": "build", "/mod-test": "test", "/mod-run": "run_server" if argument.casefold() in {"server", "runserver"} else "run_client"}[command]
            return CommandResult(action="terminal", command=info["commands"][key], payload={"label": command})
        if command == "/mod-debug":
            return CommandResult(prompt="Debug this Minecraft mod using its real Gradle files, mappings, source, and crash/log output. Run the detected Gradle task, inspect the actual failure, make a focused fix, and rebuild. Do not upgrade Minecraft, Java, mappings, or dependencies.")
        return CommandResult(text=self._t("code_cmd_unknown_minecraft"))

    @staticmethod
    def _format_plan(plan: TaskPlan, lang: str = "en") -> str:
        if not plan.steps:
            return get_text("code_cmd_plan_empty", lang)
        lines = [get_text("code_cmd_plan", lang).format(request=plan.request)]
        for index, step in enumerate(plan.steps, 1):
            lines.append(f"{index}. [{step.status}] {step.title}" + (f" — {step.note}" if step.note else ""))
        return "\n".join(lines)


def _format_plan(plan: TaskPlan, lang: str = "en") -> str:
    return CodeCommandRouter._format_plan(plan, lang)


def _format_mod(info: dict[str, Any], lang: str = "en") -> str:
    unknown = get_text("code_cmd_unknown_value", lang)
    return get_text("code_cmd_mod_info", lang).format(
        minecraft=info.get("minecraft_version") or unknown,
        loader=info.get("loader"), version=info.get("loader_version") or "",
        java=info.get("java_version") or unknown,
        mappings=info.get("mapping_system") or unknown,
        mod_id=info.get("mod_id") or unknown,
        entrypoints=info.get("entrypoints") or {},
        sources=", ".join(info.get("source_dirs") or []) or get_text("code_cmd_none_source", lang),
    )
