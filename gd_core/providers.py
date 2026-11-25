"""Gemini adapter for Code Mode's streaming tool protocol."""

from __future__ import annotations

import json
from typing import Any, Iterator


class GeminiProvider:
    name = "gemini"

    def __init__(self, client: Any, model: str) -> None:
        self.client = client
        self.model = model

    def stream(
        self,
        history: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        system_instruction: str,
        stop_event=None,
    ) -> Iterator[dict[str, Any]]:
        from google.genai import types

        contents = []
        for message in history:
            role = "model" if message.get("role") == "assistant" else "user"
            parts = []
            if message.get("content"):
                parts.append(types.Part(text=str(message["content"])))
            parts.extend(list(message.get("extra_parts") or []))
            for call in message.get("tool_calls") or []:
                parts.append(
                    types.Part(
                        function_call=types.FunctionCall(
                            id=str(call.get("id") or ""),
                            name=str(call["name"]),
                            args=dict(call.get("arguments") or {}),
                        )
                    )
                )
            if message.get("role") == "tool":
                try:
                    payload = json.loads(str(message.get("content", "{}")))
                except ValueError:
                    payload = {"result": str(message.get("content", ""))}
                parts = [types.Part.from_function_response(name=str(message.get("name") or "tool"), response=payload)]
            if parts:
                contents.append(types.Content(role=role, parts=parts))
        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            tools=[types.Tool(function_declarations=tools)] if tools else [],
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            temperature=0.2,
        )
        emitted = False
        try:
            stream = self.client.models.generate_content_stream(model=self.model, contents=contents, config=config)
            for chunk in stream:
                if stop_event is not None and stop_event.is_set():
                    break
                candidates = getattr(chunk, "candidates", None) or []
                content = getattr(candidates[0], "content", None) if candidates else None
                for index, part in enumerate(getattr(content, "parts", None) or []):
                    text = getattr(part, "text", None)
                    if text and not getattr(part, "thought", False):
                        emitted = True
                        yield {"type": "text", "text": str(text)}
                    call = getattr(part, "function_call", None)
                    if call is not None:
                        emitted = True
                        yield {
                            "type": "tool_call",
                            "id": str(getattr(call, "id", "") or f"{call.name}_{index}"),
                            "name": str(call.name),
                            "arguments": dict(getattr(call, "args", None) or {}),
                        }
        except Exception:
            if emitted:
                raise
            response = self.client.models.generate_content(model=self.model, contents=contents, config=config)
            candidates = getattr(response, "candidates", None) or []
            content = getattr(candidates[0], "content", None) if candidates else None
            for index, part in enumerate(getattr(content, "parts", None) or []):
                text = getattr(part, "text", None)
                if text and not getattr(part, "thought", False):
                    yield {"type": "text", "text": str(text)}
                call = getattr(part, "function_call", None)
                if call is not None:
                    yield {
                        "type": "tool_call",
                        "id": str(getattr(call, "id", "") or f"{call.name}_{index}"),
                        "name": str(call.name),
                        "arguments": dict(getattr(call, "args", None) or {}),
                    }
