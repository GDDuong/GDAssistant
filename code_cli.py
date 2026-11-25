"""Terminal-first Code Mode with the same tools, plans, and commands as the GUI."""

from __future__ import annotations

import os
import threading
from typing import Any

from gd_core.code_agent import CodeAgentSession
from gd_core.code_commands import CodeCommandRouter
from gd_core.code_settings import normalize_code_settings
from gd_core.coding_tools import configure_code_mode, get_registry
from gd_core.task_state import CheckpointStore, TaskPlan
from gd_core.translations import get_text


def launch_coding_cli(client, model="gemini-3.5-flash-lite", start_dir=".", debug=False, lang="en", settings=None):
    config = normalize_code_settings(settings)
    task_id = f"cli_{os.getpid()}"
    plan = TaskPlan()
    stop_event = threading.Event()

    def event(event_data):
        if debug and event_data.get("type") in {"tool_start", "tool_end", "checkpoint"}:
            print(f"[CODE] {event_data}", flush=True)

    def approve(title, details):
        try:
            return input(f"[APPROVAL] {title}: {details}\nAllow? [y/N] ").strip().casefold() in {"y", "yes"}
        except (EOFError, KeyboardInterrupt):
            return False

    context = configure_code_mode(start_dir, config, approval_callback=approve, event_callback=event, task_id=task_id, plan=plan)
    checkpoints = CheckpointStore(context.workspace.root, config.get("checkpoint_retention", 20))
    context.checkpoints = checkpoints
    session = CodeAgentSession(
        client, model=model, on_status=lambda message: print(f"[*] {message}", flush=True), debug=debug,
        settings=config, registry=get_registry(), context=context, on_event=event,
        task_id=task_id, checkpoints=checkpoints, plan=plan, approval_callback=approve,
    )
    router = CodeCommandRouter(session, lang)

    print("\n" + "=" * 72)
    print(f" {get_text('code_cli_title', lang)}")
    print(f" {get_text('code_cli_workspace', lang)} : {context.workspace.root}")
    print(f" {get_text('code_cli_model', lang)}     : {model}")
    print(" Commands: /plan /status /context /continue /explain /review /audit /refactor /debug /stop")
    print(" Minecraft: /mod-info /mod-build /mod-test /mod-run /mod-debug /mod-deps /mod-mappings /mod-audit")
    print("=" * 72 + "\n")

    def rebind_workspace(path):
        nonlocal context, checkpoints
        context = configure_code_mode(path, config, approval_callback=approve, event_callback=event, task_id=task_id, plan=plan)
        checkpoints = CheckpointStore(context.workspace.root, config.get("checkpoint_retention", 20))
        context.checkpoints = checkpoints
        session.context = context
        session.checkpoints = checkpoints
        session.rebuild_config()

    while True:
        try:
            rel_ws = context.workspace.root.name or str(context.workspace.root)
            user_input = input(f"\033[1;32m{rel_ws} >\033[0m ").strip()
            if not user_input:
                continue
            result = router.route(user_input)
            if result.handled:
                if result.text:
                    print(result.text)
                if result.action == "exit":
                    print(get_text("code_cli_exiting", lang))
                    break
                if result.action == "workspace":
                    path = result.payload.get("path")
                    if path and os.path.isdir(path):
                        rebind_workspace(path)
                        print(get_text("code_cli_workspace_changed", lang).format(workspace=context.workspace.root))
                    else:
                        print(get_text("code_cli_directory_missing", lang).format(path=path or ""))
                    continue
                if result.action == "terminal":
                    completed = context.terminals.run(result.command, context.workspace.root, config.get("command_timeout", 120), policy=context.policy, on_output=lambda _sid, text: print(text, end="", flush=True))
                    print(completed.get("output", completed.get("message", "")))
                    continue
                if not result.prompt:
                    continue
                user_input = result.prompt
            stop_event.clear()
            print("\033[90mAgent working...\033[0m", flush=True)
            response = session.execute_turn(
                user_input,
                on_text=lambda text: print(text, end="", flush=True),
                stop_event=stop_event,
                plan_only=result.plan_only,
                read_only=result.read_only,
            )
            print(f"\n\033[1mGD Assistant\033[0m:\n{response}\n")
        except KeyboardInterrupt:
            stop_event.set()
            context.terminals.stop_all()
            print(f"\n{get_text('code_cli_aborted', lang)}")
        except (EOFError, KeyboardInterrupt):
            break
    context.terminals.close()
