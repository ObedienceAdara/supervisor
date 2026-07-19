import unittest

from swarm_supervisor.tasks import (
    Task, TaskPlan, TaskPlanParseError, compute_waves,
    parse_llm_json, render_tasks_md,
)


class TestParsing(unittest.TestCase):
    def test_parses_clean_json(self):
        raw = '{"idea": "x", "tasks": [{"id": "T1", "title": "Do thing"}]}'
        plan = parse_llm_json(raw)
        self.assertEqual(plan.idea, "x")
        self.assertEqual(len(plan.tasks), 1)
        self.assertEqual(plan.tasks[0].title, "Do thing")

    def test_strips_code_fences(self):
        raw = '```json\n{"idea": "x", "tasks": [{"id": "T1", "title": "Do thing"}]}\n```'
        plan = parse_llm_json(raw)
        self.assertEqual(len(plan.tasks), 1)

    def test_extracts_object_from_surrounding_prose(self):
        raw = (
            "Sure, here is the plan:\n\n"
            '{"idea": "x", "tasks": [{"id": "T1", "title": "Do thing"}]}\n\n'
            "Let me know if you need changes!"
        )
        plan = parse_llm_json(raw)
        self.assertEqual(len(plan.tasks), 1)

    def test_raises_on_empty_tasks(self):
        raw = '{"idea": "x", "tasks": []}'
        with self.assertRaises(TaskPlanParseError):
            parse_llm_json(raw)

    def test_raises_on_garbage(self):
        with self.assertRaises(TaskPlanParseError):
            parse_llm_json("this is not json at all")

    def test_missing_ids_get_assigned(self):
        raw = '{"idea": "x", "tasks": [{"title": "A"}, {"title": "B"}]}'
        plan = parse_llm_json(raw)
        ids = plan.task_ids()
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(i for i in ids))


class TestWaves(unittest.TestCase):
    def test_independent_tasks_are_wave_one(self):
        plan = TaskPlan(idea="x", tasks=[Task(id="T1", title="a"), Task(id="T2", title="b")])
        waves, cyclic = compute_waves(plan)
        self.assertEqual(waves, {"T1": 1, "T2": 1})
        self.assertEqual(cyclic, [])

    def test_diamond_dependency_orders_correctly(self):
        plan = TaskPlan(idea="x", tasks=[
            Task(id="T1", title="base"),
            Task(id="T2", title="left", depends_on=["T1"]),
            Task(id="T3", title="right", depends_on=["T1"]),
            Task(id="T4", title="join", depends_on=["T2", "T3"]),
        ])
        waves, cyclic = compute_waves(plan)
        self.assertEqual(waves["T1"], 1)
        self.assertEqual(waves["T2"], 2)
        self.assertEqual(waves["T3"], 2)
        self.assertEqual(waves["T4"], 3)
        self.assertEqual(cyclic, [])

    def test_cycle_is_detected_not_crashed_on(self):
        plan = TaskPlan(idea="x", tasks=[
            Task(id="T1", title="a", depends_on=["T2"]),
            Task(id="T2", title="b", depends_on=["T1"]),
        ])
        waves, cyclic = compute_waves(plan)
        self.assertEqual(set(cyclic), {"T1", "T2"})


class TestRendering(unittest.TestCase):
    def test_render_contains_task_ids_and_files(self):
        plan = TaskPlan(idea="Add caching", tasks=[
            Task(id="T1", title="Core logic", target_files=["app.py"],
                 acceptance_criteria=["passes tests"]),
        ])
        md = render_tasks_md(plan)
        self.assertIn("Add caching", md)
        self.assertIn("T1", md)
        self.assertIn("app.py", md)
        self.assertIn("passes tests", md)
        self.assertIn("[P]", md)  # no deps -> wave 1 -> parallel-ready marker

    def test_render_does_not_mention_any_specific_agent_tool(self):
        plan = TaskPlan(idea="x", tasks=[Task(id="T1", title="a")])
        md = render_tasks_md(plan)
        for banned in ("Qwen Code", "Claude Code", "Cursor", "Aider"):
            self.assertNotIn(banned, md)


if __name__ == "__main__":
    unittest.main()
