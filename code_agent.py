"""code_agent.py: Autonomous coding loop with test feedback and history persistence."""

from __future__ import annotations

from typing import Any, Callable
from coding_tools import (
    CODING_TOOL_DECLARATIONS,
    CODING_TOOL_REGISTRY,
    get_workspace,
)
try:
    from history import HistoryManager
except ImportError:
    class HistoryManager:
        def __init__(self, filename="coding_history.json"):
            pass
        def save_session(self, messages):
            pass
        def get_session(self, session_id):
            return []


CODING_SYSTEM_INSTRUCTION = """You are GD Code Agent, an autonomous software engineering assistant modeled after Claude Code and Codex.
You work directly inside the user's workspace directory.

Rules of Engagement:
1. Explore First: Always read existing code with 'read_file_range' or 'search_code' before modifying files.
2. Precision Edits: Prefer 'edit_file_replace' over 'write_new_file'. Never truncate code or leave placeholder comments like '// rest of code here'.
3. Verify Automatically: After modifying code, run relevant test suites or linter checks using 'run_terminal_command' (e.g. pytest, python -m unittest, npm test).
4. Self-Correction: If a command returns a non-zero exit code or error traceback, inspect the failure, identify the cause, make repairs, and re-run verification.
5. Communication: Use GitHub-flavored Markdown, syntax-highlighted code blocks, and clear file references.
6. Python Files: Create Python programs with a `.py` extension unless the user explicitly requests an extensionless file. For a program that pauses with `input()`, use its `.py` path in any test command; the local verifier will supply one simulated Enter while preserving the pause when the user runs it.
"""

class CodeAgentSession:
    def __init__(
        self,
        client: Any,
        model: str = "gemini-3.1-pro-preview",
        on_status: Callable[[str], None] | None = None,
        debug: bool = False,
    ) -> None:
        from google.genai import types
        self.client = client
        self.model = model
        self.types = types
        self.on_status = on_status or (lambda _: None)
        self.debug = debug
        self.history_mgr = HistoryManager(filename="coding_history.json")
        self.session_messages: list[dict[str, str]] = []

        system_instruction = (
            f"{CODING_SYSTEM_INSTRUCTION}\n\n"
            f"Active Workspace Root: {get_workspace()}\n"
        )

        self.config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            tools=[types.Tool(function_declarations=CODING_TOOL_DECLARATIONS)],
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            temperature=0.2,
        )
        self.history: list[Any] = []

    def _debug(self, message: str) -> None:
        """Emit optional local diagnostics without including credentials."""
        if self.debug:
            print(f"[CODE DEBUG] {message}", flush=True)

    def execute_turn(self, user_prompt: str, max_rounds: int = 15) -> str:
        """Run the multi-turn agent loop with tool execution."""
        from google.genai import types

        self.session_messages.append({"role": "user", "content": user_prompt})
        self.history.append(types.Content(role="user", parts=[types.Part(text=user_prompt)]))

        for round_num in range(1, max_rounds + 1):
            self.on_status(f"Thinking / Planning (Step {round_num}/{max_rounds})...")
            self._debug(f"Round {round_num}/{max_rounds}: requesting {self.model}.")
            try:
                response = self.client.models.generate_content(
                    model=self.model,
                    contents=self.history,
                    config=self.config,
                )
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

            function_calls = getattr(response, "function_calls", None) or []

            # If no tools requested, the agent has finished its work
            if not function_calls:
                self._debug(f"Round {round_num}: model returned final text; no tool call requested.")
                self.history.append(response.candidates[0].content)
                final_text = getattr(response, "text", "") or "Task complete."
                self.session_messages.append({"role": "assistant", "content": final_text})
                self.history_mgr.save_session(self.session_messages)
                return final_text

            self.history.append(response.candidates[0].content)
            result_parts = []

            for call in function_calls:
                tool_name = call.name
                tool_args = dict(call.args or {})
                self._debug(f"Round {round_num}: requested tool {tool_name}({tool_args!r}).")
                self.on_status(f"Running tool: {tool_name}...")

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

        fallback_msg = "Task paused: reached maximum consecutive tool rounds."
        self._debug(f"Stopped after {max_rounds} rounds without a final response.")
        self.session_messages.append({"role": "assistant", "content": fallback_msg})
        self.history_mgr.save_session(self.session_messages)
        return fallback_msg
