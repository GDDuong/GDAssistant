"""code_cli.py: Interactive terminal coding interface like Claude Code / Codex CLI."""

from __future__ import annotations

import os
from typing import Any
from coding_tools import set_workspace, get_workspace
from code_agent import CodeAgentSession
from translations import get_text

def launch_coding_cli(
    client: Any,
    model: str = "gemini-3.5-flash-lite",
    start_dir: str = ".",
    debug: bool = False,
    lang: str = "en",
) -> None:
    set_workspace(start_dir)

    print("\n" + "=" * 65)
    print(f" {get_text('code_cli_title', lang)}")
    print(f" {get_text('code_cli_workspace', lang)} : {get_workspace()}")
    print(f" {get_text('code_cli_model', lang)}     : {model}")
    print(f" {get_text('code_cli_commands', lang)}  : {get_text('code_cli_command_list', lang)}")
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

            lowered = user_input.lower()

            if lowered in {"/exit", "/quit", "/q"}:
                print(get_text("code_cli_exiting", lang))
                break

            if lowered.startswith("/model"):
                requested_model = user_input[len("/model"):].strip()
                if not requested_model:
                    print(get_text("code_cli_current_model", lang).format(model=session.model))
                    print(get_text("code_cli_model_usage", lang))
                    continue
                session.model = requested_model
                print(get_text("code_cli_model_changed", lang).format(model=session.model))
                continue

            if lowered == "/cd" or lowered.startswith("/cd "):
                target = user_input[4:].strip()
                if not target:
                    print(get_text("code_cli_cd_usage", lang))
                    continue
                if set_workspace(target):
                    print(get_text("code_cli_workspace_changed", lang).format(workspace=get_workspace()))
                else:
                    print(get_text("code_cli_directory_missing", lang).format(path=target))
                continue

            if lowered == "/status":
                print(get_text("code_cli_current_workspace", lang).format(workspace=get_workspace()))
                print(get_text("code_cli_current_model", lang).format(model=session.model))
                continue

            print("\033[90mAgent working...\033[0m")
            response = session.execute_turn(user_input)
            print(f"\n\033[1mGD Assistant\033[0m:\n{response}\n")

        except (KeyboardInterrupt, EOFError):
            print(f"\n{get_text('code_cli_aborted', lang)}")
            break
