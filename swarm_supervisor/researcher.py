"""
researcher.py — Codebase scanner for swarm-supervisor.

Walks the project directory and extracts:
  · File tree
  · File contents (budget-limited)
  · Python AST symbol map (functions, classes)
  · Dependency manifests (requirements.txt / package.json)
"""

from __future__ import annotations

import ast
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
        function_map  : dict  — {rel_path: [symbol_names]}  (Python only)
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

            rel = str(path.relative_to(root))
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

            # ── AST symbol extraction ─────────────────────────────────────
            if path.suffix == ".py":
                symbols = _extract_python_symbols(content)
                if symbols:
                    function_map[rel] = symbols

            sp.update(task, description=f"Scanning… {rel[:60]}")

    if budget_hit:
        ui.dim("Char budget reached — some files omitted from context.")

    ui.display_scan_stats(file_tree, file_contents, function_map, total_chars, str(root))

    return {
        "project_dir":   str(root),
        "file_tree":     file_tree,
        "file_contents": file_contents,
        "function_map":  function_map,
        "deps":          "\n\n".join(dep_blocks) if dep_blocks else "No dependency files found.",
        "total_chars":   total_chars,
    }


# ═════════════════════════════════════════════════════════════════════════════
# INTERNAL HELPERS
# ═════════════════════════════════════════════════════════════════════════════

def _should_skip(path: Path) -> bool:
    """Return True if this path should be ignored entirely."""
    # Check every part of the path against ignore dirs
    for part in path.parts:
        if part in IGNORE_DIRS:
            return True
        # Glob-style: anything ending with .egg-info
        if part.endswith(".egg-info"):
            return True
    if path.name in IGNORE_FILES:
        return True
    return False


def _extract_python_symbols(source: str) -> list:
    """Parse Python source with AST and return top-level function/class names."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    return [
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ]
