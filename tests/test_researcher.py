import tempfile
import unittest
from pathlib import Path

from swarm_supervisor.researcher import research_codebase


class TestResearcher(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, rel_path: str, content: str) -> None:
        p = self.root / rel_path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")

    def test_python_symbols_imports_calls(self):
        self._write("pkg/__init__.py", "")
        self._write("pkg/models.py", "class User:\n    pass\n")
        self._write(
            "pkg/service.py",
            "from .models import User\n\n"
            "def create_user(name):\n"
            "    u = User()\n"
            "    return u\n",
        )

        research = research_codebase(str(self.root))

        self.assertIn("pkg/service.py", research["function_map"])
        self.assertIn("create_user", research["function_map"]["pkg/service.py"])
        self.assertIn("pkg/models.py", research["function_map"])
        self.assertIn("User", research["function_map"]["pkg/models.py"])

        self.assertIn("pkg/service.py", research["import_map"])
        self.assertTrue(
            any("models" in imp for imp in research["import_map"]["pkg/service.py"])
        )

        self.assertIn("pkg/service.py", research["call_map"])
        self.assertIn("User", research["call_map"]["pkg/service.py"])

    def test_js_relative_import_extraction(self):
        self._write("src/index.ts", "import { helper } from './utils';\nhelper();\n")
        self._write("src/utils.ts", "export function helper() {}\n")

        research = research_codebase(str(self.root))

        self.assertIn("src/index.ts", research["import_map"])
        self.assertIn("./utils", research["import_map"]["src/index.ts"])

    def test_ignores_node_modules_and_venv(self):
        self._write("node_modules/pkg/index.js", "module.exports = {};\n")
        self._write(".venv/lib/site.py", "x = 1\n")
        self._write("app.py", "x = 1\n")

        research = research_codebase(str(self.root))

        self.assertNotIn("node_modules/pkg/index.js", research["file_tree"])
        self.assertNotIn(".venv/lib/site.py", research["file_tree"])
        self.assertIn("app.py", research["file_tree"])


if __name__ == "__main__":
    unittest.main()
