import json
import os
import stat
import tempfile
import unittest
from pathlib import Path

from swarm_supervisor import config as cfg_mod
from swarm_supervisor.depgraph import build_from_research
from swarm_supervisor.generator import save_plan_json, save_tasks_md
from swarm_supervisor.planner import _template_plan
from swarm_supervisor.researcher import research_codebase
from swarm_supervisor.verifier import verify_task_plan


class TestTemplatePlanEndToEnd(unittest.TestCase):
    """No LLM involved — exercises the deterministic fallback through the
    same verifier + generator path a real API-backed run would take."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "app.py").write_text(
            "def handler():\n    return 'ok'\n", encoding="utf-8"
        )
        (self.root / "requirements.txt").write_text("flask\n", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_template_plan_is_internally_consistent_and_verifiable(self):
        research = research_codebase(str(self.root))
        plan = _template_plan("Add a health-check endpoint", research)

        self.assertGreaterEqual(len(plan.tasks), 2)
        ids = plan.task_ids()
        self.assertEqual(len(ids), len(set(ids)))  # unique ids

        graph = build_from_research(research)
        report = verify_task_plan(plan, graph)
        self.assertIn(report.verdict, ("SAFE", "RISKY", "CONFLICT"))
        self.assertIsInstance(report.score, int)

    def test_save_tasks_md_and_plan_json_round_trip(self):
        research = research_codebase(str(self.root))
        plan = _template_plan("Add a health-check endpoint", research)
        graph = build_from_research(research)
        report = verify_task_plan(plan, graph)

        with tempfile.TemporaryDirectory() as out_dir:
            md_path   = save_tasks_md(plan, report, out_dir)
            json_path = save_plan_json(plan, report, out_dir)

            self.assertTrue(Path(md_path).exists())
            self.assertTrue(Path(json_path).exists())

            saved = json.loads(Path(json_path).read_text(encoding="utf-8"))
            self.assertEqual(saved["idea"], plan.idea)
            self.assertIn("verification", saved)
            self.assertEqual(saved["verification"]["verdict"], report.verdict)

            md_text = Path(md_path).read_text(encoding="utf-8")
            self.assertIn(plan.tasks[0].id, md_text)


class TestConfigPermissions(unittest.TestCase):
    """Config must never be written world/group readable."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._orig_dir  = cfg_mod.CONFIG_DIR
        self._orig_file = cfg_mod.CONFIG_FILE
        cfg_mod.CONFIG_DIR  = Path(self.tmp.name) / ".supervisor"
        cfg_mod.CONFIG_FILE = cfg_mod.CONFIG_DIR / "config.json"

    def tearDown(self):
        cfg_mod.CONFIG_DIR  = self._orig_dir
        cfg_mod.CONFIG_FILE = self._orig_file
        self.tmp.cleanup()

    def test_saved_config_is_owner_only(self):
        cfg = cfg_mod.load_config()
        cfg["anthropic_api_key"] = "sk-ant-test-not-a-real-key"
        cfg_mod.save_config(cfg)

        mode = stat.S_IMODE(os.stat(cfg_mod.CONFIG_FILE).st_mode)
        self.assertEqual(mode, stat.S_IRUSR | stat.S_IWUSR)

        reloaded = cfg_mod.load_config()
        self.assertEqual(reloaded["anthropic_api_key"], "sk-ant-test-not-a-real-key")


if __name__ == "__main__":
    unittest.main()
