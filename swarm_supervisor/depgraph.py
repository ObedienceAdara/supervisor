"""
depgraph.py — Real file-to-file dependency graph, built from researcher.py's
raw import/call extraction.

This is the piece that lets `verifier.py` check whether a proposed task split
is *actually* independent, instead of trusting an LLM's promise in prose.

Two kinds of edges are resolved:
  · IMPORT edges  — file A imports file B (Python dotted-module resolution +
                     JS/TS relative-path resolution).
  · CALL edges    — file A calls a function/method name that is defined in
                     file B (Python only, name-based heuristic — no real
                     scope resolution, so it can produce false positives on
                     generically-named functions; see _COMMON_BUILTINS in
                     researcher.py for the filter applied before this point).

Neither is a substitute for a real language server. Both are considerably
more grounded than "ask the LLM nicely not to overlap," which is the bar
every other tool in this space currently clears.
"""

from __future__ import annotations

import posixpath
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Dict, List, Optional, Set

# Filenames treated as a "shared surface" regardless of measured in-degree —
# these are the files that predictably cause conflicts in real repos even
# when nothing statically points at them yet (e.g. a fresh routes.py that
# two tasks will both need to append to).
_HOTSPOT_NAME_PATTERNS: frozenset = frozenset({
    "config.py", "settings.py", "__init__.py", "routes.py", "urls.py",
    "schema.py", "schemas.py", "models.py", "app.py", "main.py",
    "server.py", "api.py", "index.ts", "index.tsx", "index.js", "index.jsx",
    "package.json", "requirements.txt", "pyproject.toml", "docker-compose.yml",
})

_JS_EXTENSIONS = (".ts", ".tsx", ".js", ".jsx")
_DEFAULT_HOTSPOT_DEGREE = 3


@dataclass
class Edge:
    src:    str
    dst:    str
    kind:   str   # "import" | "call"
    detail: str = ""   # imported module string, or called function name


@dataclass
class DependencyGraph:
    files:        Set[str]                = field(default_factory=set)
    edges:        List[Edge]              = field(default_factory=list)
    in_degree:    Dict[str, int]          = field(default_factory=dict)
    out_edges:    Dict[str, List[Edge]]   = field(default_factory=dict)
    in_edges:     Dict[str, List[Edge]]   = field(default_factory=dict)

    # ── Queries ──────────────────────────────────────────────────────────────

    def hotspots(self, min_in_degree: int = _DEFAULT_HOTSPOT_DEGREE) -> List[dict]:
        """
        Return files that are either heavily depended-upon (in_degree above
        the threshold) or match a known shared-surface filename pattern.
        Each entry: {"file": str, "in_degree": int, "reason": str}
        """
        out = []
        for f in sorted(self.files):
            deg    = self.in_degree.get(f, 0)
            name   = PurePosixPath(f).name
            by_deg = deg >= min_in_degree
            by_pat = name in _HOTSPOT_NAME_PATTERNS
            if by_deg or by_pat:
                reason = []
                if by_deg:
                    reason.append(f"imported/called by {deg} other file(s)")
                if by_pat:
                    reason.append("matches known shared-surface filename")
                out.append({"file": f, "in_degree": deg, "reason": "; ".join(reason)})
        out.sort(key=lambda x: -x["in_degree"])
        return out

    def coupling_between(self, files_a: Set[str], files_b: Set[str]) -> List[Edge]:
        """
        Return every edge that crosses the boundary between two disjoint file
        sets (in either direction). Used to score how entangled two tasks are.
        """
        out = []
        for e in self.edges:
            if (e.src in files_a and e.dst in files_b) or (e.src in files_b and e.dst in files_a):
                out.append(e)
        return out

    def to_summary(self, top_n: int = 8) -> dict:
        """Compact JSON-safe summary — used by the MCP tool and preflight display."""
        return {
            "files_in_graph": len(self.files),
            "edge_count":     len(self.edges),
            "import_edges":   sum(1 for e in self.edges if e.kind == "import"),
            "call_edges":     sum(1 for e in self.edges if e.kind == "call"),
            "top_hotspots":   self.hotspots()[:top_n],
        }


# ═════════════════════════════════════════════════════════════════════════════
# BUILD
# ═════════════════════════════════════════════════════════════════════════════

def build_from_research(research: dict) -> DependencyGraph:
    """
    Turn researcher.py's raw import_map / call_map / function_map into a
    resolved DependencyGraph.
    """
    file_tree: List[str] = research.get("file_tree", [])
    file_set:  Set[str]  = set(file_tree)

    graph = DependencyGraph(files=set(file_tree))

    module_to_file = _build_python_module_index(file_tree)
    symbol_owner   = _build_symbol_owner_index(research.get("function_map", {}))

    # ── Import edges ─────────────────────────────────────────────────────────
    for src, raw_imports in research.get("import_map", {}).items():
        is_python = src.endswith(".py")
        for raw in raw_imports:
            if is_python:
                dst = _resolve_python_import(raw, src, module_to_file)
            elif src.endswith(_JS_EXTENSIONS):
                dst = _resolve_js_import(raw, src, file_set)
            else:
                dst = None
            if dst and dst != src:
                graph.edges.append(Edge(src=src, dst=dst, kind="import", detail=raw))

    # ── Call edges (Python only, name-based heuristic) ──────────────────────
    for src, called_names in research.get("call_map", {}).items():
        for name in called_names:
            owners = symbol_owner.get(name, ())
            for dst in owners:
                if dst != src:
                    graph.edges.append(Edge(src=src, dst=dst, kind="call", detail=name))

    # ── Dedup + degree bookkeeping ───────────────────────────────────────────
    seen = set()
    deduped = []
    for e in graph.edges:
        key = (e.src, e.dst, e.kind, e.detail)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(e)
    graph.edges = deduped

    for e in graph.edges:
        graph.out_edges.setdefault(e.src, []).append(e)
        graph.in_edges.setdefault(e.dst, []).append(e)
        graph.in_degree[e.dst] = graph.in_degree.get(e.dst, 0) + 1

    return graph


# ═════════════════════════════════════════════════════════════════════════════
# PYTHON MODULE RESOLUTION
# ═════════════════════════════════════════════════════════════════════════════

def _build_python_module_index(file_tree: List[str]) -> Dict[str, str]:
    """Map dotted module name -> file relpath, for every local .py file."""
    index: Dict[str, str] = {}
    for f in file_tree:
        if not f.endswith(".py"):
            continue
        parts = f[:-3].split("/")
        if parts and parts[-1] == "__init__":
            parts = parts[:-1]
            if not parts:
                continue  # top-level __init__.py — no useful package name
        module_name = ".".join(parts)
        index[module_name] = f
    return index


def _resolve_python_import(raw: str, from_file: str, module_to_file: Dict[str, str]) -> Optional[str]:
    """Resolve one raw import string (possibly relative) to a project file."""
    level = 0
    while level < len(raw) and raw[level] == ".":
        level += 1
    mod_part = raw[level:]

    if level > 0:
        # Relative import — anchor to from_file's containing package.
        pkg_parts = from_file.split("/")[:-1]  # directory parts of from_file
        cut = len(pkg_parts) - (level - 1)
        if cut < 0:
            return None
        base_parts = pkg_parts[:cut]
        target_parts = base_parts + (mod_part.split(".") if mod_part else [])
        candidate_module = ".".join(p for p in target_parts if p)
    else:
        candidate_module = mod_part

    if not candidate_module:
        return None

    parts = candidate_module.split(".")
    for cut in range(len(parts), 0, -1):
        candidate = ".".join(parts[:cut])
        hit = module_to_file.get(candidate)
        if hit and hit != from_file:
            return hit
    return None


# ═════════════════════════════════════════════════════════════════════════════
# JS/TS RELATIVE IMPORT RESOLUTION
# ═════════════════════════════════════════════════════════════════════════════

def _resolve_js_import(spec: str, from_file: str, file_set: Set[str]) -> Optional[str]:
    """Resolve a relative JS/TS import spec ('./foo', '../bar/baz') to a file."""
    if not spec.startswith("."):
        return None  # external package / bare specifier — not resolvable locally

    from_dir  = posixpath.dirname(from_file)
    raw       = posixpath.normpath(posixpath.join(from_dir, spec))

    candidates = [raw]
    for ext in _JS_EXTENSIONS:
        candidates.append(f"{raw}{ext}")
    for ext in _JS_EXTENSIONS:
        candidates.append(posixpath.join(raw, f"index{ext}"))

    for c in candidates:
        if c in file_set:
            return c
    return None


# ═════════════════════════════════════════════════════════════════════════════
# SYMBOL OWNERSHIP INDEX (for call-edge resolution)
# ═════════════════════════════════════════════════════════════════════════════

def _build_symbol_owner_index(function_map: Dict[str, list]) -> Dict[str, tuple]:
    """Map symbol name -> tuple of files that define a function/class of that name."""
    owners: Dict[str, list] = {}
    for f, symbols in function_map.items():
        for name in symbols:
            owners.setdefault(name, []).append(f)
    return {name: tuple(files) for name, files in owners.items()}
