import unittest

from swarm_supervisor.depgraph import build_from_research
from swarm_supervisor.tasks import Task, TaskPlan
from swarm_supervisor.verifier import verify_task_plan


class TestVerifier(unittest.TestCase):
    def test_clean_split_scores_safe(self):
        research = {
            "file_tree": ["a.py", "b.py"],
            "function_map": {}, "import_map": {}, "call_map": {},
        }
        graph = build_from_research(research)
        plan = TaskPlan(idea="x", tasks=[
            Task(id="T1", title="a", target_files=["a.py"]),
            Task(id="T2", title="b", target_files=["b.py"]),
        ])
        report = verify_task_plan(plan, graph)
        self.assertEqual(report.verdict, "SAFE")
        self.assertEqual(report.score, 100)
        self.assertEqual(report.direct_conflicts, [])

    def test_same_file_claimed_twice_is_a_conflict(self):
        research = {
            "file_tree": ["a.py"],
            "function_map": {}, "import_map": {}, "call_map": {},
        }
        graph = build_from_research(research)
        plan = TaskPlan(idea="x", tasks=[
            Task(id="T1", title="a", target_files=["a.py"]),
            Task(id="T2", title="b", target_files=["a.py"]),
        ])
        report = verify_task_plan(plan, graph)
        self.assertEqual(report.verdict, "CONFLICT")
        self.assertEqual(len(report.direct_conflicts), 1)
        self.assertEqual(set(report.direct_conflicts[0]["tasks"]), {"T1", "T2"})

    def test_import_coupling_across_tasks_is_flagged(self):
        research = {
            "file_tree": ["pkg/models.py", "pkg/service.py"],
            "function_map": {}, "import_map": {"pkg/service.py": ["pkg.models"]}, "call_map": {},
        }
        graph = build_from_research(research)
        plan = TaskPlan(idea="x", tasks=[
            Task(id="T1", title="models", target_files=["pkg/models.py"]),
            Task(id="T2", title="service", target_files=["pkg/service.py"]),
        ])
        report = verify_task_plan(plan, graph)
        self.assertGreaterEqual(len(report.coupling_risks), 1)
        self.assertNotEqual(report.verdict, "SAFE")

    def test_hotspot_shared_by_two_tasks_is_flagged(self):
        research = {
            "file_tree": ["config.py", "a.py", "b.py", "c.py"],
            "function_map": {}, "import_map": {
                "a.py": ["config"], "b.py": ["config"], "c.py": ["config"],
            }, "call_map": {},
        }
        graph = build_from_research(research)
        plan = TaskPlan(idea="x", tasks=[
            Task(id="T1", title="a", target_files=["a.py", "config.py"]),
            Task(id="T2", title="b", target_files=["b.py", "config.py"]),
        ])
        report = verify_task_plan(plan, graph)
        self.assertEqual(len(report.hotspot_hits), 1)
        self.assertEqual(report.hotspot_hits[0]["file"], "config.py")

    def test_score_never_goes_below_zero(self):
        research = {"file_tree": ["a.py"], "function_map": {}, "import_map": {}, "call_map": {}}
        graph = build_from_research(research)
        plan = TaskPlan(idea="x", tasks=[
            Task(id=f"T{i}", title="a", target_files=["a.py"]) for i in range(10)
        ])
        report = verify_task_plan(plan, graph)
        self.assertGreaterEqual(report.score, 0)
        self.assertEqual(report.verdict, "CONFLICT")


if __name__ == "__main__":
    unittest.main()
