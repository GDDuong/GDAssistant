"""code_cli.py: Interactive terminal coding interface like Claude Code / Codex CLI."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any
from coding_tools import set_workspace, get_workspace
from code_agent import CodeAgentSession

def launch_coding_cli(
    client: Any,
    model: str = "gemini-3.5-flash-lite",
    start_dir: str = ".",
    debug: bool = False,
) -> None:
    set_workspace(start_dir)

    print("\n" + "=" * 65)
    print(" GD ASSISTANT :: CODING AGENT MODE (Claude Code Style)")
    print(f" Workspace : {get_workspace()}")
    print(f" Model     : {model}")
    print(" Commands  : 'cd <path>' | 'status' | '/model <name>' | 'exit' / 'quit'")
    print("=" * 65 + "\n")

    def print_agent_status(msg: str) -> None:
        print(f"\033[94m[*] {msg}\033[0m")

    session = CodeAgentSession(client, model=model, on_status=print_agent_status, debug=debug)

    while True:
        try:
            rel_ws = os.path.basename(get_workspace()) or str(get_workspace())
            user_input = input(f"\033[1;32m{rel_ws} >\033[0m ").strip()

            if not user_input:
                continue

            if user_input.lower() in {"exit", "quit", ":q"}:
                print("Exiting Coding Mode.")
                break

            if user_input.lower().startswith("/model"):
                requested_model = user_input[len("/model"):].strip()
                if not requested_model:
                    print(f"Current model: {session.model}")
                    print("Usage: /model <Gemini model name>")
                    continue
                session.model = requested_model
                print(f"Code Agent model changed to: {session.model}")
                continue

            if user_input.startswith("cd "):
                target = user_input[3:].strip()
                if set_workspace(target):
                    print(f"Active workspace changed to: {get_workspace()}")
                else:
                    print(f"Error: Directory not found: {target}")
                continue

            if user_input.lower() == "status":
                print(f"Current workspace: {get_workspace()}")
                print(f"Current model: {session.model}")
                continue

            print("\033[90mAgent working...\033[0m")
            response = session.execute_turn(user_input)
            print(f"\n\033[1mGD Assistant\033[0m:\n{response}\n")

        except (KeyboardInterrupt, EOFError):
            print("\nAborted by user.")
            break
