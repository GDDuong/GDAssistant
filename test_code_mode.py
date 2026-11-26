"""Code Mode 2.0 smoke tests using temporary projects only."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

os.environ["APPDATA"] = tempfile.mkdtemp(prefix="gd_code_tests_")
sys.path.insert(0, str(Path(__file__).parent))

from gd_core.code_agent import CodeAgentSession
from gd_core.code_commands import CodeCommandRouter
from gd_core.code_settings import normalize_code_settings, permission_mode_label
from gd_core.coding_tools import configure_code_mode, get_registry
from gd_core.conversations import ConversationStore
from gd_core.project import ProjectIndex, inspect_project, minecraft_audit
from gd_core.terminal import ExecutionPolicy, TerminalManager
from gd_core.workspace import Workspace


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="gd_workspace_")
        self.root = Path(self.temp.name)
        self.workspace = Workspace(self.root, task_id="test")

    def tearDown(self):
        self.temp.cleanup()

    def test_boundaries_and_sensitive_files(self):
        outside = self.root.parent / f"{self.root.name}_outside.txt"
        outside.write_text("secret", encoding="utf-8")
        try:
            with self.assertRaises(ValueError):
                self.workspace.safe_path("../" + outside.name)
            (self.root / ".env").write_text("TOKEN=secret", encoding="utf-8")
            with self.assertRaises(ValueError):
                self.workspace.read_text(".env")
            self.assertEqual(self.workspace.read_text(".env", allow_sensitive=True), "TOKEN=secret")
        finally:
            outside.unlink(missing_ok=True)

    def test_symlink_cannot_escape(self):
        outside = self.root.parent / f"{self.root.name}_linked.txt"
        outside.write_text("outside", encoding="utf-8")
        try:
            (self.root / "link.txt").symlink_to(outside)
        except OSError:
            self.skipTest("Symlink creation is not permitted on this machine")
        with self.assertRaises(ValueError):
            self.workspace.read_text("link.txt")

    def test_file_operations_snapshots_and_undo(self):
        created = self.workspace.create_file("src/app.py", "def app():\n    return 1\n")
        self.assertEqual(created["status"], "SUCCESS")
        edited = self.workspace.edit_file("src/app.py", "return 1", "return 2")
        self.assertEqual(edited["status"], "SUCCESS")
        self.assertIn("+    return 2", edited["diff"])
        moved = self.workspace.move_file("src/app.py", "src/main.py")
        self.assertEqual(moved["status"], "SUCCESS")
        renamed = self.workspace.rename_file("src/main.py", "application.py")
        self.assertEqual(renamed["status"], "SUCCESS")
        self.assertEqual(self.workspace.read_text("src/application.py"), "def app():\n    return 2\n")
        change = self.workspace.tracker.changes[-1]
        undone = self.workspace.tracker.undo(change.id)
        self.assertEqual(undone["status"], "SUCCESS")
        self.assertFalse((self.root / "src/application.py").exists())
        self.assertTrue((self.root / "src/main.py").exists())

    def test_external_modification_blocks_undo_and_overwrite(self):
        self.workspace.create_file("a.txt", "before")
        change = self.workspace.tracker.changes[-1]
        (self.root / "a.txt").write_text("external", encoding="utf-8")
        refused = self.workspace.tracker.undo(change.id)
        self.assertEqual(refused["status"], "FAILURE")
        self.assertEqual((self.root / "a.txt").read_text(encoding="utf-8"), "external")
        stale = self.workspace.write_file("a.txt", "new", expected_sha256="wrong")
        self.assertEqual(stale["status"], "FAILURE")

    def test_ignored_paths_and_index(self):
        (self.root / "src").mkdir()
        (self.root / "src/main.py").write_text("class Main:\n    pass\n", encoding="utf-8")
        (self.root / "node_modules").mkdir()
        (self.root / "node_modules/pkg.js").write_text("function ignored() {}", encoding="utf-8")
        files = self.workspace.list_files(max_entries=100)["files"]
        self.assertIn("src/main.py", files)
        self.assertNotIn("node_modules/pkg.js", files)
        index = ProjectIndex(self.workspace)
        result = index.refresh(incremental=False)
        self.assertEqual(result["status"], "SUCCESS")
        self.assertIn("Main", index.files["src/main.py"]["symbols"])


class ProjectTests(unittest.TestCase):
    def test_python_and_node_detection(self):
        with tempfile.TemporaryDirectory(prefix="gd_project_") as folder:
            root = Path(folder)
            (root / "main.py").write_text("print('ok')", encoding="utf-8")
            self.assertEqual(inspect_project(root)["kind"], "python")
            (root / "package.json").write_text(json.dumps({"scripts": {"test": "vitest"}, "dependencies": {"react": "1"}}), encoding="utf-8")
            info = inspect_project(root)
            self.assertEqual(info["kind"], "node")
            self.assertIn("React", info["frameworks"])
            self.assertIn("npm run test", [item["command"] for item in info["commands"]])

    def test_fabric_profile_and_audit(self):
        with tempfile.TemporaryDirectory(prefix="gd_fabric_") as folder:
            root = Path(folder)
            (root / "src/main/java/com/example").mkdir(parents=True)
            (root / "src/main/java/com/example/ExampleMod.java").write_text("package com.example; public class ExampleMod {}", encoding="utf-8")
            (root / "src/main/resources").mkdir(parents=True)
            (root / "gradle.properties").write_text("minecraft_version=1.21.1\nyarn_mappings=1.21.1+build.3\njava_version=21\n", encoding="utf-8")
            (root / "build.gradle").write_text("plugins { id 'fabric-loom' version '1.6-SNAPSHOT' }", encoding="utf-8")
            (root / "gradlew.bat").write_text("@echo off", encoding="utf-8")
            (root / "fabric.mod.json").write_text(json.dumps({"id": "examplemod", "entrypoints": {"main": "com.example.ExampleMod"}}), encoding="utf-8")
            info = inspect_project(root)["minecraft"]
            self.assertEqual(info["loader"], "Fabric")
            self.assertEqual(info["minecraft_version"], "1.21.1")
            self.assertEqual(info["java_version"], "21")
            self.assertEqual(info["mapping_system"], "Yarn")
            self.assertEqual(info["mod_id"], "examplemod")
            audit = minecraft_audit(root)
            self.assertTrue(audit["compatible"], audit["issues"])


class TerminalTests(unittest.TestCase):
    def test_structured_command_captures_output(self):
        with tempfile.TemporaryDirectory(prefix="gd_terminal_") as folder:
            manager = TerminalManager()
            result = manager.run(sys.executable, folder, 15, args=["-c", "import sys; print('out'); print('err', file=sys.stderr); sys.exit(3)"], policy=ExecutionPolicy())
            self.assertEqual(result["status"], "FAILURE")
            self.assertEqual(result["returncode"], 3)
            self.assertIn("out", result["output"])
            self.assertIn("err", result["output"])
            manager.close()

    def test_permissions_and_cancellation(self):
        with tempfile.TemporaryDirectory(prefix="gd_terminal_") as folder:
            manager = TerminalManager()
            denied = manager.run("git status", folder, 10, policy=ExecutionPolicy(mode="supervised"))
            self.assertEqual(denied["status"], "FAILURE")
            self.assertTrue(denied["permission_denied"])
            approved = []
            policy = ExecutionPolicy(mode="supervised", approval_callback=lambda title, details: approved.append(title) or True)
            approved_result = manager.run("git status", folder, 10, policy=policy)
            self.assertFalse(approved_result.get("permission_denied", False))
            self.assertTrue(approved)
            started = manager.start(sys.executable, folder, 30, args=["-c", "import time; time.sleep(30)"], policy=ExecutionPolicy())
            self.assertEqual(started["status"], "SUCCESS")
            time.sleep(0.2)
            self.assertEqual(manager.stop(started["session_id"])["status"], "SUCCESS")
            manager.close()


class ScriptedProvider:
    name = "scripted"

    def __init__(self, rounds):
        self.rounds = list(rounds)
        self.model = "test"

    def stream(self, history, tools, system_instruction, stop_event=None):
        for event in self.rounds.pop(0):
            yield event


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="gd_agent_")
        self.root = Path(self.temp.name)
        self.context = configure_code_mode(str(self.root), {"permission_mode": "project_autonomous", "auto_index": False}, task_id="agent-test")

    def tearDown(self):
        self.context.terminals.close()
        self.temp.cleanup()

    def test_tool_loop_plan_file_and_checkpoint(self):
        provider = ScriptedProvider([
            [{"type": "tool_call", "id": "plan", "name": "create_plan", "arguments": {"request": "Add a file", "steps": ["Create file", "Verify"]}}],
            [{"type": "tool_call", "id": "decision", "name": "record_decision", "arguments": {"decision": "Keep the file plain text for portability."}}],
            [{"type": "tool_call", "id": "write", "name": "create_file", "arguments": {"file_path": "hello.txt", "content": "hello"}}],
            [{"type": "text", "text": "Created hello.txt."}],
        ])
        session = CodeAgentSession(object(), provider=provider, context=self.context, registry=get_registry(), settings={"auto_index": False})
        response = session.execute_turn("Add a file")
        self.assertIn("Created", response)
        self.assertEqual((self.root / "hello.txt").read_text(encoding="utf-8"), "hello")
        self.assertEqual(session.plan.to_dict()["total"], 2)
        self.assertEqual(session.modified_files, ["hello.txt"])
        checkpoint = session.checkpoints.load(session.task_id)
        self.assertEqual(checkpoint["status"], "completed")
        self.assertEqual(checkpoint["files_modified"], ["hello.txt"])
        self.assertEqual(checkpoint["decisions"], ["Keep the file plain text for portability."])

    def test_read_only_blocks_write_tool(self):
        provider = ScriptedProvider([
            [{"type": "tool_call", "id": "write", "name": "create_file", "arguments": {"file_path": "nope.txt", "content": "nope"}}],
            [{"type": "text", "text": "Read-only review complete."}],
        ])
        session = CodeAgentSession(object(), provider=provider, context=self.context, registry=get_registry(), settings={"auto_index": False})
        session.execute_turn("Review", read_only=True)
        self.assertFalse((self.root / "nope.txt").exists())

    def test_repeated_failure_stops_and_checkpoint_resumes(self):
        provider = ScriptedProvider([
            [{"type": "tool_call", "id": f"bad{i}", "name": "missing_tool", "arguments": {}}]
            for i in range(5)
        ])
        session = CodeAgentSession(object(), provider=provider, context=self.context, registry=get_registry(), settings={"auto_index": False})
        response = session.execute_turn("Do something")
        self.assertIn("three times", response)
        checkpoint = session.checkpoints.load(session.task_id)
        self.assertEqual(checkpoint["status"], "blocked")
        resumed = CodeAgentSession(object(), provider=ScriptedProvider([[{"type": "text", "text": "resumed"}]]), context=self.context, registry=get_registry(), settings={"auto_index": False})
        resumed.resume_checkpoint(checkpoint)
        self.assertEqual(resumed.task_id, session.task_id)

    def test_minecraft_commands_are_functional(self):
        (self.root / "fabric.mod.json").write_text(json.dumps({"id": "demo", "entrypoints": {"main": "Demo"}}), encoding="utf-8")
        (self.root / "gradle.properties").write_text("minecraft_version=1.21.1\njava_version=21\n", encoding="utf-8")
        session = CodeAgentSession(object(), provider=ScriptedProvider([]), context=self.context, registry=get_registry(), settings={"auto_index": False})
        router = CodeCommandRouter(session)
        self.assertIn("Fabric", router.route("/mod-info").text)
        vietnamese = CodeCommandRouter(session, "vi")
        self.assertIn("Lệnh chế độ Code", vietnamese.route("/help").text)
        self.assertIn("Loader", vietnamese.route("/mod-info").text)
        build = router.route("/mod-build")
        self.assertEqual(build.action, "terminal")
        self.assertIn("build", build.command)


class SettingsTests(unittest.TestCase):
    def test_normalization(self):
        settings = normalize_code_settings({"max_iterations": "999", "permission_mode": "invalid", "ignored_dirs": "one\ntwo", "approved_patterns": "git status\nnpm test"})
        self.assertEqual(settings["max_iterations"], 100)
        self.assertEqual(settings["permission_mode"], "project_autonomous")
        self.assertEqual(settings["ignored_dirs"], ["one", "two"])
        self.assertEqual(settings["approved_patterns"], ["git status", "npm test"])


class UiTests(unittest.TestCase):
    def test_skill_autocomplete_requires_whitespace(self):
        try:
            import tkinter as tk
            from gd_core.skills import SkillManager
            from ui_tk.skill_dialog import SkillAutocomplete
            from ui_tk.themes import get_theme
        except (ImportError, tk.TclError):
            self.skipTest("Tk display is unavailable")
        with tempfile.TemporaryDirectory(prefix="gd_skill_complete_") as folder:
            manager = SkillManager(folder, Path(folder) / "user")
            manager.create("helper", "Helpers", "Inspect first.")
            root = tk.Tk()
            root.withdraw()
            try:
                entry = tk.Entry(root)
                entry.pack()
                autocomplete = SkillAutocomplete(entry, manager.discover, get_theme("light"))
                entry.insert(0, "mail@helper")
                autocomplete._refresh()
                self.assertIsNone(autocomplete.window)
                entry.delete(0, tk.END)
                entry.insert(0, "@hel")
                autocomplete._refresh()
                self.assertIsNotNone(autocomplete.window)
                autocomplete._choose()
                self.assertEqual(entry.get(), "@helper ")
            finally:
                root.destroy()

    def test_p1_p2_ui_state_badges_and_mentions(self):
        try:
            import tkinter as tk
            from ui_tk.code_gui import CodeAgentPanel
            from ui_tk.mdrender import configure_tags, insert_mentions
            from ui_tk.themes import get_theme
        except (ImportError, tk.TclError):
            self.skipTest("Tk display is unavailable")
        with tempfile.TemporaryDirectory(prefix="gd_ui_polish_") as folder:
            saved = []
            root = tk.Tk()
            root.withdraw()
            try:
                panel = CodeAgentPanel(
                    root, object(), start_dir=folder,
                    settings={"explorer_visible": False, "activity_visible": False, "terminal_expanded": False},
                    on_settings_change=saved.append,
                )
                self.assertEqual(panel.explorer.winfo_manager(), "")
                self.assertEqual(panel.activity.winfo_manager(), "")
                self.assertEqual(panel.terminal_body.winfo_manager(), "")
                panel.toggle_explorer()
                self.assertTrue(saved[-1]["explorer_visible"])
                self.assertTrue(panel.quick_start.winfo_manager())
                panel.plan.set_steps("Demo", ["Inspect", "Change"])
                panel.refresh_plan()
                self.assertIn("0/2", panel.tabs.tab(panel.plan_tab, "text"))
                self.assertIn(folder, panel._project_tooltip())
                preview = tk.Text(root)
                configure_tags(preview, get_theme("light"))
                insert_mentions(preview, "Use @helper")
                self.assertTrue(preview.tag_ranges("md_mention"))
            finally:
                panel.terminals.close()
                root.destroy()

    def test_permission_mode_is_scoped_to_project(self):
        try:
            import tkinter as tk
            from ui_tk.code_gui import CodeAgentPanel
        except (ImportError, tk.TclError):
            self.skipTest("Tk display is unavailable")
        with tempfile.TemporaryDirectory(prefix="gd_ui_project_") as folder:
            root_path = Path(folder)
            other_path = root_path / "other"
            other_path.mkdir()
            store = ConversationStore(root_path / "history")
            root = tk.Tk()
            root.withdraw()
            try:
                panel = CodeAgentPanel(root, object(), start_dir=folder, store=store, settings={"default_project_dir": folder, "auto_index": False})
                project_id = panel.conv["id"]
                panel.permission_var.set(permission_mode_label("supervised", "en"))
                self.assertEqual(store.load_conversation(project_id)["permission_mode"], "supervised")
                panel.on_new_chat()
                self.assertEqual(panel.context.policy.mode, "supervised")
                self.assertEqual(panel.permission_combo.get(), permission_mode_label("supervised", "en"))
                panel.permission_var.set(permission_mode_label("advanced", "en"))
                self.assertEqual(store.load_conversation(project_id)["permission_mode"], "advanced")
                self.assertEqual(panel.settings["permission_mode"], "project_autonomous")
                other = store.create_conversation("code", title="Other", workspace=str(other_path), is_project=True)
                panel._set_conversation(other)
                self.assertEqual(panel.context.policy.mode, "project_autonomous")
                self.assertEqual(store.load_conversation(other["id"])["permission_mode"], "project_autonomous")
                self.assertEqual(panel.permission_combo.get(), permission_mode_label("project_autonomous", "en"))
            finally:
                panel.terminals.close()
                root.destroy()

    def test_skill_creator_is_separate_themed_popup(self):
        try:
            import tkinter as tk
            from ui_tk.skill_dialog import SkillDialog
            from ui_tk.themes import get_theme
        except (ImportError, tk.TclError):
            self.skipTest("Tk display is unavailable")
        with tempfile.TemporaryDirectory(prefix="gd_skill_ui_") as folder:
            root = tk.Tk()
            root.withdraw()
            try:
                colors = get_theme("light")
                dialog = SkillDialog(root, folder, [], "en", lambda _ids: None, colors=colors)
                dialog._show_create()
                self.assertIsNot(dialog.create_dialog, dialog)
                self.assertEqual(dialog.create_dialog.cget("bg"), colors["background"])
                dialog.create_dialog.destroy()
                dialog.destroy()
            finally:
                root.destroy()

    def test_ide_shell_and_editor_round_trip(self):
        try:
            import tkinter as tk
            from ui_tk.code_gui import CodeAgentPanel
        except (ImportError, tk.TclError):
            self.skipTest("Tk display is unavailable")
        with tempfile.TemporaryDirectory(prefix="gd_ui_project_") as folder:
            root_path = Path(folder)
            (root_path / "main.py").write_text("def main():\n    return 1\n", encoding="utf-8")
            root = tk.Tk()
            root.withdraw()
            try:
                panel = CodeAgentPanel(root, object(), start_dir=folder, settings={"default_project_dir": folder, "auto_index": False})
                root.update_idletasks()
                self.assertEqual(len(panel.tabs.tabs()), 5)
                self.assertEqual(panel.conv["workspace"], folder)
                self.assertTrue(panel.conv["is_project"])
                self.assertEqual(panel.permission_combo.current(), 1)
                self.assertEqual(panel.permission_combo.get(), permission_mode_label("project_autonomous", "en"))
                self.assertTrue(hasattr(panel, "tab_tooltips"))
                self.assertTrue(hasattr(panel, "skills_btn"))
                panel.toggle_terminal()
                self.assertFalse(panel._terminal_expanded)
                self.assertEqual(panel.terminal_body.winfo_manager(), "")
                panel.toggle_terminal()
                self.assertTrue(panel._terminal_expanded)
                panel.open_file(root_path / "main.py")
                self.assertIn("def main", panel.editor.text.get("1.0", tk.END))
                panel.editor.text.insert(tk.END, "\n# changed\n")
                panel.editor.save()
                self.assertIn("# changed", (root_path / "main.py").read_text(encoding="utf-8"))
                panel.refresh_plan()
                panel.refresh_changes()
            finally:
                panel.terminals.close()
                root.destroy()


if __name__ == "__main__":
    unittest.main(verbosity=2)
