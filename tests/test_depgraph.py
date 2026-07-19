import unittest

from swarm_supervisor.depgraph import build_from_research


def _research(file_tree, function_map=None, import_map=None, call_map=None):
    return {
        "file_tree": file_tree,
        "function_map": function_map or {},
        "import_map": import_map or {},
        "call_map": call_map or {},
    }


class TestDependencyGraph(unittest.TestCase):
    def test_python_absolute_import_resolves(self):
        research = _research(
            file_tree=["pkg/__init__.py", "pkg/models.py", "pkg/service.py"],
            import_map={"pkg/service.py": ["pkg.models"]},
        )
        graph = build_from_research(research)
        dsts = {e.dst for e in graph.edges if e.src == "pkg/service.py"}
        self.assertIn("pkg/models.py", dsts)

    def test_python_relative_import_resolves(self):
        research = _research(
            file_tree=["pkg/__init__.py", "pkg/models.py", "pkg/service.py"],
            import_map={"pkg/service.py": [".models", ".models.User"]},
        )
        graph = build_from_research(research)
        dsts = {e.dst for e in graph.edges if e.src == "pkg/service.py"}
        self.assertIn("pkg/models.py", dsts)

    def test_call_edge_resolves_to_defining_file(self):
        research = _research(
            file_tree=["pkg/models.py", "pkg/service.py"],
            function_map={"pkg/models.py": ["User"]},
            call_map={"pkg/service.py": ["User"]},
        )
        graph = build_from_research(research)
        call_edges = [e for e in graph.edges if e.kind == "call"]
        self.assertTrue(any(e.src == "pkg/service.py" and e.dst == "pkg/models.py" for e in call_edges))

    def test_js_relative_import_resolves_with_extension_guessing(self):
        research = _research(
            file_tree=["src/index.ts", "src/utils.ts"],
            import_map={"src/index.ts": ["./utils"]},
        )
        graph = build_from_research(research)
        dsts = {e.dst for e in graph.edges if e.src == "src/index.ts"}
        self.assertIn("src/utils.ts", dsts)

    def test_external_import_does_not_resolve(self):
        research = _research(
            file_tree=["app.py"],
            import_map={"app.py": ["os", "requests"]},
        )
        graph = build_from_research(research)
        self.assertEqual(graph.edges, [])

    def test_hotspot_detection_by_pattern_and_degree(self):
        research = _research(
            file_tree=["config.py", "a.py", "b.py", "c.py", "d.py"],
            import_map={
                "a.py": ["config"],
                "b.py": ["config"],
                "c.py": ["config"],
            },
        )
        graph = build_from_research(research)
        hotspot_files = {h["file"] for h in graph.hotspots(min_in_degree=3)}
        self.assertIn("config.py", hotspot_files)

    def test_no_self_edges(self):
        research = _research(
            file_tree=["a.py"],
            function_map={"a.py": ["helper"]},
            call_map={"a.py": ["helper"]},
        )
        graph = build_from_research(research)
        self.assertEqual(graph.edges, [])


if __name__ == "__main__":
    unittest.main()
