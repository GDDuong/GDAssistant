"""Skill package and project-history smoke checks."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ["APPDATA"] = tempfile.mkdtemp(prefix="gd_skill_tests_")
sys.path.insert(0, str(Path(__file__).parent))

from gd_core.code_agent import CodeAgentSession
from gd_core.code_settings import normalize_code_settings, permission_mode_from_label, permission_mode_label
from gd_core.coding_tools import configure_code_mode, get_registry
from gd_core.conversations import ConversationStore
from gd_core.skills import SkillManager


class DummyProvider:
    name = "dummy"
    model = "dummy"


class CapturingProvider(DummyProvider):
    def __init__(self):
        self.instruction = ""

    def stream(self, history, declarations, instruction, stop_event):
        self.instruction = instruction
        yield {"type": "text", "text": "ok"}


class SkillTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="gd_skills_")
        self.root = Path(self.temp.name)
        self.user_dir = self.root / "user-skills"
        self.project = self.root / "project"
        self.project.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def test_discovers_project_skill_and_renders_active_instructions(self):
        path = self.project / ".skills" / "reviewer" / "SKILL.md"
        path.parent.mkdir(parents=True)
        path.write_text(
            '---\nname: reviewer\ndescription: "Reviews code carefully"\n---\n\nCheck real files before reporting bugs.\n',
            encoding="utf-8",
        )
        manager = SkillManager(self.project, self.user_dir)
        skill = next(item for item in manager.discover() if item.id == "project:reviewer")
        self.assertEqual(skill.description, "Reviews code carefully")
        rendered = manager.render_active([skill.id])
        self.assertIn("Check real files before reporting bugs.", rendered)
        self.assertIn("do not grant tools or permissions", rendered)

    def test_creates_compatible_user_skill_and_rejects_empty_instructions(self):
        manager = SkillManager(self.project, self.user_dir)
        created = manager.create("My Reviewer", "Review changes", "Use focused diffs.")
        self.assertEqual(created.id, "user:my-reviewer")
        self.assertIn("name: \"my-reviewer\"", created.path.read_text(encoding="utf-8"))
        self.assertIn(created.id, [item.id for item in manager.discover()])
        with self.assertRaises(ValueError):
            manager.create("bad", "", "   ")

    def test_code_agent_includes_enabled_skill(self):
        skill_path = self.project / ".skills" / "helper" / "SKILL.md"
        skill_path.parent.mkdir(parents=True)
        skill_path.write_text("---\nname: helper\ndescription: Helper\n---\nAlways inspect the actual error.\n", encoding="utf-8")
        context = configure_code_mode(self.project, {"auto_index": False})
        session = CodeAgentSession(
            object(), provider=DummyProvider(), context=context, registry=get_registry(),
            settings={"auto_index": False}, skills=["project:helper"],
        )
        self.assertIn("Always inspect the actual error.", session.system_instruction)
        self.assertIn("only when the user explicitly names it", session.system_instruction)

    def test_at_mention_overrides_disabled_skill_for_one_turn(self):
        skill_path = self.project / ".skills" / "helper" / "SKILL.md"
        skill_path.parent.mkdir(parents=True)
        skill_path.write_text("---\nname: helper\ndescription: Helper\n---\nAlways inspect the actual error.\n", encoding="utf-8")
        manager = SkillManager(self.project, self.user_dir)
        self.assertEqual(manager.mentions("Use @helper please"), ["project:helper"])
        self.assertEqual(manager.mentions("Read this\n\nAttached file: note.txt\n```\n@helper\n```"), [])
        context = configure_code_mode(self.project, {"auto_index": False})
        provider = CapturingProvider()
        session = CodeAgentSession(
            object(), provider=provider, context=context, registry=get_registry(),
            settings={"auto_index": False}, skills=[],
        )
        self.assertNotIn("Always inspect the actual error.", session.system_instruction)
        session.execute_turn("Use @helper please")
        self.assertIn("Always inspect the actual error.", provider.instruction)
        session.execute_turn("Continue normally")
        self.assertNotIn("Always inspect the actual error.", provider.instruction)

    def test_chat_at_mention_is_temporary(self):
        import main as app

        session = app.AssistantSession(object(), model="dummy", skills=[])
        session.skill_manager.create("helper", "Helper", "Always inspect the actual error.")
        original = session.config.system_instruction
        captured = []
        real_send = app.send_message_with_tools

        def fake_send(client, model, config, history, on_text=None, stop_event=None):
            captured.append(config.system_instruction)
            return "ok"

        app.send_message_with_tools = fake_send
        try:
            session.ask("Use @helper please")
        finally:
            app.send_message_with_tools = real_send
        self.assertIn("Always inspect the actual error.", captured[0])
        self.assertEqual(session.config.system_instruction, original)


class HistoryTests(unittest.TestCase):
    def test_project_groups_chats_and_deletes_together(self):
        with tempfile.TemporaryDirectory(prefix="gd_history_") as folder:
            store = ConversationStore(Path(folder))
            project = store.create_conversation("code", title="Demo", workspace=folder, is_project=True)
            child = store.create_conversation("code", title="Fix bug", workspace=folder, project_id=project["id"])
            loose = store.create_conversation("code", title="Scratch", workspace="")
            self.assertEqual(child["project_id"], project["id"])
            self.assertEqual(loose["workspace"], "")
            store.delete_project(project["id"])
            self.assertIsNone(store.load_conversation(project["id"]))
            self.assertIsNone(store.load_conversation(child["id"]))
            self.assertIsNotNone(store.load_conversation(loose["id"]))

    def test_default_workspace_and_permission_labels(self):
        settings = normalize_code_settings({"default_project_dir": "."})
        self.assertEqual(Path(settings["default_project_dir"]), Path.home() / "Documents")
        label = permission_mode_label("supervised", "en")
        self.assertIn("Supervised", label)
        self.assertEqual(permission_mode_from_label(label, "en"), "supervised")

    def test_accent_override_preserves_theme_defaults(self):
        from ui_tk.themes import get_theme, is_hex_color

        self.assertEqual(get_theme("dark")["accent"], "#007acc")
        custom = get_theme("dark", "#FF0000")
        self.assertEqual(custom["accent"], "#ff0000")
        self.assertEqual(custom["accent_active"], "#bf0000")
        self.assertEqual(get_theme("dark", "invalid")["accent"], "#007acc")
        self.assertTrue(is_hex_color("#007acc"))
        self.assertFalse(is_hex_color("blue"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
