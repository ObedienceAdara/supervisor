"""
verifier.py — Score a TaskPlan's real independence against a DependencyGraph.

This is the actual differentiator: every worktree-isolation orchestrator on
the market stops conflicts at the git level (two agents can't write the same
file at once) but none of them check *before* you run anything whether the
split was structurally sound. This module does that check — using real
import/call edges, not an LLM's prose assurance that it "won't touch" a file.

It is intentionally decoupled from planner.py: verify_task_plan() takes any
TaskPlan (ours, or one handed in by another tool over MCP) and any
DependencyGraph (built from any research snapshot). Nothing about it assumes
the plan came from our own LLM call.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

from .depgraph import DependencyGraph
from .tasks import TaskPlan

# ── Scoring weights (deliberately simple and documented — tune here) ─────────
_DIRECT_CONFLICT_PENALTY = 35
_COUPLING_PENALTY        = 4
_COUPLING_PENALTY_CAP    = 40
_HOTSPOT_PENALTY         = 8

_SAFE_THRESHOLD  = 80   # score >= this AND no direct conflicts -> SAFE
_RISKY_THRESHOLD = 50   # score >= this (and no direct conflicts) -> RISKY, else CONFLICT


@dataclass
class ConflictReport:
    score:                       int
    verdict:                     str                 # "SAFE" | "RISKY" | "CONFLICT"
    direct_conflicts:            List[dict] = field(default_factory=list)
    coupling_risks:               List[dict] = field(default_factory=list)
    hotspot_hits:                 List[dict] = field(default_factory=list)
    unclaimed_dependency_files:   List[str]  = field(default_factory=list)
    notes:                        List[str]  = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "score": self.score,
            "verdict": self.verdict,
            "direct_conflicts": self.direct_conflicts,
            "coupling_risks": self.coupling_risks,
            "hotspot_hits": self.hotspot_hits,
            "unclaimed_dependency_files": self.unclaimed_dependency_files,
            "notes": self.notes,
        }


def verify_task_plan(plan: TaskPlan, graph: DependencyGraph) -> ConflictReport:
    """
    Run all checks and produce a ConflictReport.

    Checks
    ------
    1. Direct conflicts   — the same file claimed (in target_files) by 2+ tasks.
    2. Coupling risks     — import/call edges that cross task boundaries
                             (task A's files reference task B's files).
    3. Hotspot hits       — a high-in-degree or pattern-matched "shared
                             surface" file claimed by more than one task.
    4. Unclaimed deps     — files that graph edges show are relevant to a
                             task's files, but that aren't claimed by *any*
                             task and aren't obviously external — informational,
                             doesn't affect score, flags likely scope gaps.
    """
    direct_conflicts = _find_direct_conflicts(plan)
    coupling_risks    = _find_coupling_risks(plan, graph)
    hotspot_hits       = _find_hotspot_hits(plan, graph)
    unclaimed          = _find_unclaimed_dependencies(plan, graph)

    score = 100
    score -= _DIRECT_CONFLICT_PENALTY * len(direct_conflicts)
    score -= min(_COUPLING_PENALTY_CAP, _COUPLING_PENALTY * len(coupling_risks))
    score -= _HOTSPOT_PENALTY * len(hotspot_hits)
    score = max(0, min(100, score))

    if direct_conflicts:
        verdict = "CONFLICT"
    elif score >= _SAFE_THRESHOLD and not coupling_risks:
        verdict = "SAFE"
    elif score >= _RISKY_THRESHOLD:
        verdict = "RISKY"
    else:
        verdict = "CONFLICT"

    notes = []
    if not graph.files:
        notes.append("Dependency graph is empty — verification ran on file-overlap checks only.")
    if unclaimed:
        notes.append(
            f"{len(unclaimed)} file(s) are referenced by task-owned files via imports/calls "
            f"but aren't claimed by any task — likely fine if external/shared, worth a glance "
            f"if not."
        )

    return ConflictReport(
        score=score,
        verdict=verdict,
        direct_conflicts=direct_conflicts,
        coupling_risks=coupling_risks,
        hotspot_hits=hotspot_hits,
        unclaimed_dependency_files=unclaimed,
        notes=notes,
    )


# ═════════════════════════════════════════════════════════════════════════════
# CHECKS
# ═════════════════════════════════════════════════════════════════════════════

def _find_direct_conflicts(plan: TaskPlan) -> List[dict]:
    owners: Dict[str, List[str]] = {}
    for t in plan.tasks:
        for f in t.target_files:
            owners.setdefault(f, []).append(t.id)

    return [
        {"file": f, "tasks": task_ids}
        for f, task_ids in sorted(owners.items())
        if len(task_ids) > 1
    ]


def _find_coupling_risks(plan: TaskPlan, graph: DependencyGraph) -> List[dict]:
    risks: List[dict] = []
    tasks = plan.tasks
    for i in range(len(tasks)):
        for j in range(i + 1, len(tasks)):
            a, b = tasks[i], tasks[j]
            files_a, files_b = set(a.target_files), set(b.target_files)
            if not files_a or not files_b:
                continue
            edges = graph.coupling_between(files_a, files_b)
            for e in edges:
                risks.append({
                    "from_task": a.id if e.src in files_a else b.id,
                    "to_task":   b.id if e.dst in files_b else a.id,
                    "file_a":    e.src,
                    "file_b":    e.dst,
                    "kind":      e.kind,
                    "detail":    e.detail,
                })
    return risks


def _find_hotspot_hits(plan: TaskPlan, graph: DependencyGraph) -> List[dict]:
    hotspot_files = {h["file"]: h["reason"] for h in graph.hotspots()}
    owners: Dict[str, List[str]] = {}
    for t in plan.tasks:
        for f in t.target_files:
            if f in hotspot_files:
                owners.setdefault(f, []).append(t.id)

    return [
        {"file": f, "tasks": task_ids, "reason": hotspot_files[f]}
        for f, task_ids in sorted(owners.items())
        if len(task_ids) > 1
    ]


def _find_unclaimed_dependencies(plan: TaskPlan, graph: DependencyGraph) -> List[str]:
    claimed: set = set()
    for t in plan.tasks:
        claimed.update(t.target_files)
    if not claimed:
        return []

    referenced: set = set()
    for e in graph.edges:
        if e.src in claimed and e.dst not in claimed:
            referenced.add(e.dst)

    return sorted(referenced)
