"""code_agent.py: Autonomous coding loop with test feedback and resumable history."""

from __future__ import annotations

from typing import Any, Callable
from gd_core.coding_tools import (
    CODING_TOOL_DECLARATIONS,
    CODING_TOOL_REGISTRY,
    get_workspace,
)


CODING_SYSTEM_INSTRUCTION = """You are GD Code Agent, an autonomous software engineering assistant modeled after Claude Code and Codex.
You work directly inside the user's workspace directory.

Rules of Engagement:
1. Explore First: Always read existing code with 'read_file_range' or 'search_code' before modifying files.
2. Precision Edits: Prefer 'edit_file_replace' over 'write_new_file'. Never truncate code or leave placeholder comments like '// rest of code here'.
3. Verify Automatically: After modifying code, run relevant test suites or linter checks using 'run_terminal_command' (e.g. pytest, python -m unittest, npm test).
4. Self-Correction: If a command returns a non-zero exit code or error traceback, inspect the failure, identify the cause, make repairs, and re-run verification.
5. Communication: Use GitHub-flavored Markdown, syntax-highlighted code blocks, and clear file references.
6. Python Files: Create Python programs with a `.py` extension unless the user explicitly requests an extensionless file. For a program that pauses with `input()`, use its `.py` path in any test command; the local verifier will supply one simulated Enter while preserving the pause when the user runs it.
7. Reference Directories: Additional read-only reference directories may be listed below. You may list, read, and search files there with absolute paths, but never modify anything outside the Active Workspace Root.
"""

class CodeAgentSession:
    def __init__(
        self,
        client: Any,
        model: str = "gemini-3.1-pro-preview",
        on_status: Callable[[str], None] | None = None,
        debug: bool = False,
        extra_dirs: list[str] | None = None,
        seed_messages: list[dict[str, str]] | None = None,
    ) -> None:
        from google.genai import types
        self.client = client
        self.model = model
        self.types = types
        self.on_status = on_status or (lambda _: None)
        self.debug = debug
        self.extra_dirs = list(extra_dirs or [])
        self.config = self._build_config()
        self.history: list[Any] = [
            types.Content(
                role="model" if str(message.get("role")) == "assistant" else "user",
                parts=[types.Part(text=str(message.get("content", "")))],
            )
            for message in (seed_messages or [])
        ]

    def _build_config(self) -> Any:
        from google.genai import types

        reference_block = ""
        if self.extra_dirs:
            listed = "\n".join(f"- {path}" for path in self.extra_dirs)
            reference_block = f"\nAdditional Reference Directories (read-only):\n{listed}\n"

        system_instruction = (
            f"{CODING_SYSTEM_INSTRUCTION}\n\n"
            f"Active Workspace Root: {get_workspace()}\n"
            f"{reference_block}"
        )

        return types.GenerateContentConfig(
            system_instruction=system_instruction,
            tools=[types.Tool(function_declarations=CODING_TOOL_DECLARATIONS)],
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            temperature=0.2,
        )

    def rebuild_config(self) -> None:
        """Refresh the system instruction after a workspace/reference change."""
        self.config = self._build_config()

    def _debug(self, message: str) -> None:
        """Emit optional local diagnostics without including credentials."""
        if self.debug:
            print(f"[CODE DEBUG] {message}", flush=True)

    def execute_turn(
        self,
        user_prompt: str,
        max_rounds: int = 15,
        on_text: Callable[[str], None] | None = None,
        stop_event: Any = None,
        extra_parts: list[Any] | None = None,
    ) -> str:
        """Run the multi-turn agent loop with tool execution."""
        from google.genai import types

        parts = [types.Part(text=user_prompt), *(extra_parts or [])]
        self.history.append(types.Content(role="user", parts=parts))

        streamed_pieces: list[str] = []

        def emit_text(text: str) -> None:
            if not text:
                return
            streamed_pieces.append(text)
            if on_text is not None:
                on_text(text)

        def text_of(parts_list: list[Any]) -> str:
            return "".join(
                str(getattr(part, "text", "") or "")
                for part in parts_list
                if not getattr(part, "thought", False)
            )

        def response_parts(chunk: Any) -> list[Any]:
            candidates = getattr(chunk, "candidates", None) or []
            content = getattr(candidates[0], "content", None) if candidates else None
            return list(getattr(content, "parts", None) or [])

        def stream_round() -> tuple[list[Any], bool]:
            parts: list[Any] = []
            try:
                stream = self.client.models.generate_content_stream(
                    model=self.model, contents=self.history, config=self.config
                )
                for chunk in stream:
                    if stop_event is not None and stop_event.is_set():
                        return parts, True
                    for part in response_parts(chunk):
                        parts.append(part)
                        text = getattr(part, "text", None)
                        if text and not getattr(part, "thought", False):
                            emit_text(text)
            except Exception as error:
                if parts:
                    self._debug(f"Round interrupted mid-stream: {type(error).__name__}: {error}")
                    return parts, True
                self._debug(f"Streaming unavailable ({type(error).__name__}); using standard request.")
                response = self.client.models.generate_content(
                    model=self.model, contents=self.history, config=self.config
                )
                return response_parts(response), False
            return parts, False

        final_round_text = ""
        stopped = False

        for round_num in range(1, max_rounds + 1):
            if stop_event is not None and stop_event.is_set():
                self._debug("Stop requested; ending agent turn.")
                stopped = True
                break
            self.on_status(f"Thinking / Planning (Step {round_num}/{max_rounds})...")
            self._debug(f"Round {round_num}/{max_rounds}: requesting {self.model}.")
            try:
                parts, interrupted = stream_round()
            except Exception as err:
                self._debug(f"Round {round_num}: model request failed: {type(err).__name__}: {err}")
                err_text = str(err)
                if "404" in err_text or "not found" in err_text.lower():
                    return (
                        f"Error: Model '{self.model}' returned a 404 error.\n"
                        f"Details: {err_text}\n\n"
                        f"Try using: gemini-3.1-pro-preview or gemini-3.5-flash."
                    )
                return f"Gemini API request failed: {err}"
            function_calls = [
                part.function_call for part in parts if getattr(part, "function_call", None) is not None
            ]
            round_text = text_of(parts)

            if interrupted:
                # A truncated turn must not carry dangling function calls, or
                # the next request would demand responses that never ran.
                self._debug(f"Round {round_num}: interrupted; keeping partial text only.")
                safe_parts = [part for part in parts if getattr(part, "function_call", None) is None]
                if safe_parts:
                    self.history.append(types.Content(role="model", parts=safe_parts))
                final_round_text = text_of(safe_parts)
                stopped = True
                break

            # If no tools requested, the agent has finished its work
            if not function_calls:
                self._debug(f"Round {round_num}: model returned final text; no tool call requested.")
                if parts:
                    self.history.append(types.Content(role="model", parts=parts))
                final_round_text = round_text
                if on_text is not None and not round_text:
                    emit_text("Task complete.")
                break

            self.history.append(types.Content(role="model", parts=parts))
            if on_text is not None and round_text:
                emit_text("\n\n")
            result_parts = []

            for call in function_calls:
                tool_name = call.name
                tool_args = dict(call.args or {})
                self._debug(f"Round {round_num}: requested tool {tool_name}({tool_args!r}).")
                self.on_status(f"Running tool: {tool_name}...")

                if stop_event is not None and stop_event.is_set():
                    # The model turn still needs a response per requested call.
                    result = {"status": "FAILURE", "message": "Stopped by user."}
                else:
                    handler = CODING_TOOL_REGISTRY.get(tool_name)
                    if handler:
                        try:
                            result = handler(tool_args)
                        except Exception as err:
                            result = {"status": "FAILURE", "message": f"Tool error: {err}"}
                    else:
                        result = {"status": "FAILURE", "message": f"Unknown tool: {tool_name}"}

                self._debug(
                    f"Round {round_num}: {tool_name} -> {result.get('status', 'UNKNOWN')}: "
                    f"{str(result.get('message', ''))[:500]}"
                )

                result_parts.append(
                    types.Part.from_function_response(
                        name=tool_name,
                        response={"result": result},
                    )
                )

            self.history.append(types.Content(role="user", parts=result_parts))
        else:
            fallback_msg = "Task paused: reached maximum consecutive tool rounds."
            self._debug(f"Stopped after {max_rounds} rounds without a final response.")
            if on_text is not None:
                emit_text(fallback_msg)
            final_round_text = fallback_msg

        if on_text is not None and streamed_pieces:
            return "".join(streamed_pieces)
        return final_round_text or "Task complete."
