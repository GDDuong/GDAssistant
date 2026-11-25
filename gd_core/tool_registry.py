"""Central, permission-aware registry for Code Mode tools."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[[dict[str, Any], "ToolContext"], dict[str, Any]]
    permission: str = "read"


@dataclass
class ToolContext:
    workspace: Any
    terminals: Any
    policy: Any
    task_id: str = ""
    event_callback: Callable[[dict[str, Any]], None] | None = None
    checkpoints: Any = None
    plan: Any = None
    decisions: list[str] = field(default_factory=list)

    def emit(self, event: dict[str, Any]) -> None:
        if self.event_callback is not None:
            self.event_callback(event)


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._tools:
            raise ValueError(f"Duplicate tool name: {spec.name}")
        if spec.permission not in {"read", "write", "execute", "destructive"}:
            raise ValueError(f"Invalid permission for {spec.name}: {spec.permission}")
        self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def specs(self) -> list[ToolSpec]:
        return list(self._tools.values())

    def declarations(self) -> list[dict[str, Any]]:
        return [
            {
                "name": spec.name,
                "description": spec.description,
                "parameters": spec.parameters,
            }
            for spec in self._tools.values()
        ]

    def execute(self, name: str, arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        spec = self.get(name)
        if spec is None:
            return {"status": "FAILURE", "message": f"Unknown tool: {name}"}
        args = arguments if isinstance(arguments, dict) else {}
        error = self._validate(spec, args)
        if error:
            return {"status": "FAILURE", "message": error}
        if not self._authorize(spec, args, context):
            return {"status": "FAILURE", "message": f"Permission denied for {name}."}

        fingerprint = hashlib.sha256(
            json.dumps([name, args], sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        context.emit({"type": "tool_start", "tool": name, "arguments": args, "fingerprint": fingerprint})
        try:
            result = spec.handler(args, context)
            if not isinstance(result, dict):
                result = {"status": "SUCCESS", "message": str(result)}
            result.setdefault("status", "SUCCESS")
            result.setdefault("message", "")
        except Exception as exc:
            result = {"status": "FAILURE", "message": f"{name} failed: {exc}"}
        context.emit(
            {
                "type": "tool_end",
                "tool": name,
                "arguments": args,
                "result": result,
                "fingerprint": fingerprint,
            }
        )
        return result

    @staticmethod
    def _validate(spec: ToolSpec, args: dict[str, Any]) -> str | None:
        schema = spec.parameters or {}
        for key in schema.get("required", []):
            if key not in args:
                return f"Missing required argument '{key}' for {spec.name}."
        expected_types = {
            "string": str,
            "integer": int,
            "number": (int, float),
            "boolean": bool,
            "array": list,
            "object": dict,
        }
        for key, definition in (schema.get("properties") or {}).items():
            if key not in args or args[key] is None:
                continue
            expected = expected_types.get(definition.get("type"))
            if expected is None:
                continue
            if not isinstance(args[key], expected) or (
                definition.get("type") in {"integer", "number"} and isinstance(args[key], bool)
            ):
                return f"Argument '{key}' for {spec.name} must be {definition.get('type')}."
        return None

    @staticmethod
    def _authorize(spec: ToolSpec, args: dict[str, Any], context: ToolContext) -> bool:
        policy = context.policy
        if policy is None:
            return spec.permission == "read"
        if spec.permission == "read":
            return True
        target = str(args.get("file_path") or args.get("path") or args.get("command") or "")
        if policy.is_preapproved(spec.permission, target):
            return True
        if spec.permission == "destructive":
            return policy.approve(f"Destructive action: {spec.name}", target)
        if spec.permission == "write" and policy.mode == "supervised":
            return policy.approve(f"File change: {spec.name}", target)
        return True
