"""
researcher.py — Codebase scanner for swarm-supervisor.

Walks the project directory and extracts:
  · File tree
  · File contents (budget-limited)
  · Python AST symbol map (functions, classes defined per file)
  · Python AST import map (raw import statements per file)
  · Python AST call-name map (unqualified function/method names called per file)
  · JS/TS import map (regex-extracted `import ... from` / `require(...)`)
  · Dependency manifests (requirements.txt / package.json)

The import/call maps are raw, unresolved data — `depgraph.py` is what turns
this into an actual file-to-file dependency graph. Keeping resolution out of
this module keeps the scanner cheap and language-mechanical: it just reports
what each file *says*, without deciding what it *means*.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path
from typing import Dict, List

from . import display as ui

# ── Config ────────────────────────────────────────────────────────────────────
MAX_CODEBASE_CHARS: int = 40_000

SUPPORTED_EXTENSIONS: frozenset = frozenset({
    ".py", ".ts", ".tsx", ".js", ".jsx",
    ".json", ".md", ".txt", ".env.example",
    ".yaml", ".yml", ".toml", ".cfg", ".ini",
})

# Extensions we build import/call edges for (a subset of SUPPORTED_EXTENSIONS —
# config/doc files are read for context but don't participate in the graph).
GRAPH_EXTENSIONS: frozenset = frozenset({".py", ".ts", ".tsx", ".js", ".jsx"})

IGNORE_DIRS: frozenset = frozenset({
    "__pycache__", ".git", "node_modules",
    ".venv", "venv", "env", "dist", "build",
    ".next", ".mypy_cache", ".pytest_cache",
    "coverage", "htmlcov", ".tox", "eggs",
    ".eggs", "*.egg-info",
})

IGNORE_FILES: frozenset = frozenset({
    ".env", ".env.local", ".env.production",
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
    "poetry.lock", "Pipfile.lock",
})

DEP_FILES: frozenset = frozenset({
    "requirements.txt", "requirements-dev.txt",
    "package.json", "Pipfile", "pyproject.toml",
    "setup.cfg", "setup.py",
})

# Names called constantly that almost never point at a same-project symbol.
# Kept short and conservative — this is a heuristic filter, not a real
# resolver, so it errs toward under-filtering rather than hiding real edges.
_COMMON_BUILTINS: frozenset = frozenset({
    "print", "len", "str", "int", "float", "bool", "list", "dict", "set",
    "tuple", "range", "open", "super", "self", "cls", "enumerate", "zip",
    "map", "filter", "sorted", "reversed", "isinstance", "getattr",
    "setattr", "hasattr", "type", "format", "join", "append", "get",
    "update", "items", "keys", "values", "split", "strip", "replace",
    "load", "loads", "dump", "dumps", "run", "main", "init", "add",
    "remove", "pop", "sleep", "wraps", "property", "staticmethod",
    "classmethod", "abstractmethod",
})

_JS_IMPORT_RE = re.compile(
    r"""(?:import\s+(?:[\w*{}\s,]+?)\s+from\s+|require\()\s*['"]([^'"]+)['"]"""
)


# ═════════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ═════════════════════════════════════════════════════════════════════════════

def research_codebase(project_dir: str) -> dict:
    """
    Scan the project directory and return a structured research snapshot.

    Returns
    -------
    dict with keys:
        project_dir   : str   — resolved absolute path
        file_tree     : list  — all relative file paths found
        file_contents : dict  — {rel_path: content_str}
        function_map  : dict  — {rel_path: [symbol_names]}       (Python only)
        import_map    : dict  — {rel_path: [raw_import_strings]} (Python + JS/TS)
        call_map      : dict  — {rel_path: [called_names]}       (Python only)
        deps          : str   — concatenated dependency manifest contents
        total_chars   : int   — total chars read into file_contents
    """
    root = Path(project_dir).resolve()

    if not root.exists():
        ui.error(f"Project directory not found: {root}")
        sys.exit(1)

    file_tree:     List[str]       = []
    file_contents: Dict[str, str]  = {}
    function_map:  Dict[str, list] = {}
    import_map:    Dict[str, list] = {}
    call_map:      Dict[str, list] = {}
    dep_blocks:    List[str]       = []
    total_chars:   int             = 0
    budget_hit                     = False

    with ui.make_spinner("Scanning codebase…") as sp:
        task = sp.add_task("Scanning…")

        for path in sorted(root.rglob("*")):
            if _should_skip(path):
                continue
            if not path.is_file():
                continue

            rel = str(path.relative_to(root).as_posix())
            file_tree.append(rel)

            # ── Dependency manifests ──────────────────────────────────────
            if path.name in DEP_FILES:
                try:
                    dep_blocks.append(f"[{path.name}]\n{path.read_text('utf-8', errors='ignore')}")
                except Exception:
                    pass
                # Also keep contents for full context when within budget
                # (fall through intentionally)

            if path.suffix not in SUPPORTED_EXTENSIONS:
                continue

            if budget_hit:
                continue  # keep building file_tree but skip reading

            # ── Read file ─────────────────────────────────────────────────
            try:
                content = path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue

            remaining = MAX_CODEBASE_CHARS - total_chars
            if len(content) > remaining:
                file_contents[rel] = content[:remaining] + "\n... [TRUNCATED — budget reached]"
                total_chars += remaining
                budget_hit = True
            else:
                file_contents[rel] = content
                total_chars += len(content)

            # ── AST symbol / import / call extraction (Python) ─────────────
            if path.suffix == ".py":
                symbols, imports, calls = _extract_python_ast(content)
                if symbols:
                    function_map[rel] = symbols
                if imports:
                    import_map[rel] = imports
                if calls:
                    call_map[rel] = calls

            # ── Regex import extraction (JS/TS) ─────────────────────────────
            elif path.suffix in (".ts", ".tsx", ".js", ".jsx"):
                imports = _extract_js_imports(content)
                if imports:
                    import_map[rel] = imports

            sp.update(task, description=f"Scanning… {rel[:60]}")

    if budget_hit:
        ui.dim("Char budget reached — some files omitted from context.")

    ui.display_scan_stats(file_tree, file_contents, function_map, total_chars, str(root))

    return {
        "project_dir":   str(root),
        "file_tree":     file_tree,
        "file_contents": file_contents,
        "function_map":  function_map,
        "import_map":    import_map,
        "call_map":      call_map,
        "deps":          "\n\n".join(dep_blocks) if dep_blocks else "No dependency files found.",
        "total_chars":   total_chars,
    }


# ═════════════════════════════════════════════════════════════════════════════
# INTERNAL HELPERS
# ═════════════════════════════════════════════════════════════════════════════

def _should_skip(path: Path) -> bool:
    """Return True if this path should be ignored entirely."""
    for part in path.parts:
        if part in IGNORE_DIRS:
            return True
        if part.endswith(".egg-info"):
            return True
    if path.name in IGNORE_FILES:
        return True
    return False


def _extract_python_ast(source: str) -> tuple[list, list, list]:
    """
    Parse Python source once and return (symbols, imports, calls).

    symbols — top-level-or-nested function/class names *defined* in this file
    imports — raw import strings, e.g. "os", "pkg.sub", ".relative" (dots
              indicate relative-import level, handled by depgraph.py)
    calls   — unqualified names invoked via a Call node, filtered against a
              small common-builtins stoplist (see _COMMON_BUILTINS)
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return [], [], []

    symbols: list = []
    imports: list = []
    calls:   list = []

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            symbols.append(node.name)

        elif isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)

        elif isinstance(node, ast.ImportFrom):
            level = node.level or 0
            mod   = node.module or ""
            prefix = "." * level
            imports.append(f"{prefix}{mod}" if mod else prefix)
            # Also record `from pkg import symbol` — symbol might itself be a
            # submodule (pkg.symbol); depgraph.py tries both interpretations.
            for alias in node.names:
                if alias.name != "*":
                    imports.append(f"{prefix}{mod}.{alias.name}" if mod else f"{prefix}{alias.name}")

        elif isinstance(node, ast.Call):
            fn = node.func
            name = None
            if isinstance(fn, ast.Name):
                name = fn.id
            elif isinstance(fn, ast.Attribute):
                name = fn.attr
            if name and name not in _COMMON_BUILTINS and not name.startswith("_"):
                calls.append(name)

    return symbols, imports, calls


def _extract_js_imports(source: str) -> list:
    """Best-effort regex extraction of import/require specifiers from JS/TS."""
    return _JS_IMPORT_RE.findall(source)
