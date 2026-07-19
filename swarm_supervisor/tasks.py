"""
tasks.py — Agent-agnostic task representation.

This replaces the old "**AGENT N - Role**" markdown-block format. A TaskPlan
is a plain, structured object (JSON-serializable) that:

  · doesn't hardcode a task count (2 tasks or 12 — whatever the idea needs)
  · doesn't name a target tool (no "Qwen Code", no "Claude Code" — any agent
    or orchestrator can consume it)
  · renders to a Spec-Kit-style tasks.md (dependency-ordered, [P]-marked)
    so it drops into the existing ecosystem instead of inventing a new one

The LLM planner in planner.py is one *producer* of a TaskPlan. It is not the
only one — verifier.py's conflict check works on any TaskPlan, including one
handed to it by another tool over MCP.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .verifier import ConflictReport


# ═════════════════════════════════════════════════════════════════════════════
# DATA MODEL
# ═════════════════════════════════════════════════════════════════════════════

@dataclass
class Task:
    id:                   str
    title:                str
    description:          str            = ""
    target_files:         List[str]      = field(default_factory=list)
    avoid_files:          List[str]      = field(default_factory=list)
    depends_on:           List[str]      = field(default_factory=list)
    acceptance_criteria:  List[str]      = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Task":
        return cls(
            id=str(d.get("id", "")).strip() or "T?",
            title=str(d.get("title", "Untitled task")).strip(),
            description=str(d.get("description", "")).strip(),
            target_files=_coerce_str_list(d.get("target_files")),
            avoid_files=_coerce_str_list(d.get("avoid_files")),
            depends_on=_coerce_str_list(d.get("depends_on")),
            acceptance_criteria=_coerce_str_list(d.get("acceptance_criteria")),
        )


@dataclass
class TaskPlan:
    idea:               str
    tasks:              List[Task] = field(default_factory=list)
    integration_notes:  str        = ""

    def to_dict(self) -> dict:
        return {
            "idea": self.idea,
            "tasks": [t.to_dict() for t in self.tasks],
            "integration_notes": self.integration_notes,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    @classmethod
    def from_dict(cls, d: dict) -> "TaskPlan":
        return cls(
            idea=str(d.get("idea", "")).strip(),
            tasks=[Task.from_dict(t) for t in d.get("tasks", []) if isinstance(t, dict)],
            integration_notes=str(d.get("integration_notes", "")).strip(),
        )

    def task_ids(self) -> List[str]:
        return [t.id for t in self.tasks]

    def get(self, task_id: str) -> Optional[Task]:
        for t in self.tasks:
            if t.id == task_id:
                return t
        return None


class TaskPlanParseError(ValueError):
    """Raised when an LLM (or external) response can't be parsed into a TaskPlan."""


# ═════════════════════════════════════════════════════════════════════════════
# PARSING — turns raw LLM text into a validated TaskPlan
# ═════════════════════════════════════════════════════════════════════════════

def parse_llm_json(raw_text: str, idea_fallback: str = "") -> TaskPlan:
    """
    Robustly extract a TaskPlan from an LLM response.

    Handles the common failure modes: wrapping the JSON in ```json fences,
    prepending "Here is the plan:" commentary despite instructions not to,
    or trailing commentary after the closing brace. Raises
    TaskPlanParseError if no valid JSON object with a `tasks` list can be
    found at all — callers should treat that as "replan," not silently
    proceed with an empty plan.
    """
    candidate = _strip_code_fences(raw_text).strip()

    parsed = _try_json(candidate)
    if parsed is None:
        # Fall back to locating the outermost {...} block in noisy output.
        block = _extract_outer_object(candidate)
        parsed = _try_json(block) if block else None

    if not isinstance(parsed, dict) or "tasks" not in parsed:
        raise TaskPlanParseError(
            "Could not find a JSON object with a 'tasks' list in the model's response."
        )

    if not parsed.get("idea"):
        parsed["idea"] = idea_fallback

    plan = TaskPlan.from_dict(parsed)
    if not plan.tasks:
        raise TaskPlanParseError("Parsed JSON had an empty 'tasks' list.")

    _assign_missing_ids(plan)
    return plan


def _try_json(text: Optional[str]):
    if not text:
        return None
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None


def _strip_code_fences(text: str) -> str:
    fence = re.compile(r"```(?:json)?\s*\n?(.*?)```", re.DOTALL | re.IGNORECASE)
    m = fence.search(text)
    return m.group(1) if m else text


def _extract_outer_object(text: str) -> Optional[str]:
    """Find the first '{' and its matching closing '}' via brace counting."""
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


def _coerce_str_list(value) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return []


def _assign_missing_ids(plan: TaskPlan) -> None:
    """Guarantee every task has a non-empty, unique id (T1, T2, ... as fallback)."""
    seen = set()
    for i, t in enumerate(plan.tasks, 1):
        if not t.id or t.id in seen or t.id == "T?":
            t.id = f"T{i}"
        seen.add(t.id)


# ═════════════════════════════════════════════════════════════════════════════
# DEPENDENCY WAVES (for [P] markers and ordering, Spec-Kit style)
# ═════════════════════════════════════════════════════════════════════════════

def compute_waves(plan: TaskPlan) -> tuple[dict[str, int], list[str]]:
    """
    Topologically order tasks into dependency "waves" (Kahn's algorithm).

    Wave 1 = tasks with no dependencies (ready immediately, marked [P]).
    Wave 2 = tasks whose dependencies are all in wave 1. Etc.

    Returns (task_id -> wave_number, [task_ids involved in a cycle]).
    Cyclic tasks are excluded from wave numbering and reported separately
    so the caller can surface them as a planning error instead of silently
    mis-ordering them.
    """
    ids = {t.id for t in plan.tasks}
    remaining_deps = {
        t.id: [d for d in t.depends_on if d in ids and d != t.id]
        for t in plan.tasks
    }
    waves: dict[str, int] = {}
    wave_num = 1
    frontier = [tid for tid, deps in remaining_deps.items() if not deps]

    resolved = set()
    while frontier:
        for tid in frontier:
            waves[tid] = wave_num
            resolved.add(tid)
        wave_num += 1
        frontier = [
            tid for tid, deps in remaining_deps.items()
            if tid not in resolved and all(d in resolved for d in deps)
        ]

    cyclic = [tid for tid in ids if tid not in resolved]
    return waves, cyclic


# ═════════════════════════════════════════════════════════════════════════════
# RENDERING — Spec-Kit-style tasks.md
# ═════════════════════════════════════════════════════════════════════════════

def render_tasks_md(plan: TaskPlan, verification: Optional["ConflictReport"] = None) -> str:
    """
    Render a TaskPlan as a Spec-Kit-style tasks.md: dependency-ordered,
    [P]-marked where a task has no unresolved dependencies, with exact file
    paths and acceptance criteria per task — agent-agnostic, no tool name
    baked in anywhere.
    """
    waves, cyclic = compute_waves(plan)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    lines: List[str] = []
    lines.append(f"# Tasks: {plan.idea or '(untitled)'}")
    lines.append("")
    lines.append(f"Generated by swarm-supervisor · {ts}")
    lines.append("")

    if verification is not None:
        lines.append("## Dependency-Graph Verification")
        lines.append("")
        lines.append(f"**Score:** {verification.score}/100 — **{verification.verdict}**")
        lines.append("")
        if verification.direct_conflicts:
            lines.append("**Direct file conflicts (must fix before running in parallel):**")
            for c in verification.direct_conflicts:
                lines.append(f"- `{c['file']}` is claimed by {', '.join(c['tasks'])}")
            lines.append("")
        if verification.coupling_risks:
            lines.append(f"**Coupling risks:** {len(verification.coupling_risks)} cross-task "
                          f"edge(s) detected (imports/calls between tasks' files — review before "
                          f"merging out of order).")
            lines.append("")
        if verification.hotspot_hits:
            lines.append("**Shared-surface files touched by more than one task:**")
            for h in verification.hotspot_hits:
                lines.append(f"- `{h['file']}` — {h['reason']} (tasks: {', '.join(h['tasks'])})")
            lines.append("")

    if cyclic:
        lines.append(f"> ⚠ Circular dependency detected among: {', '.join(cyclic)}. "
                      f"These tasks are listed but not wave-ordered — resolve the cycle "
                      f"before running them.")
        lines.append("")

    lines.append("## Tasks")
    lines.append("")

    ordered = sorted(plan.tasks, key=lambda t: (waves.get(t.id, 999), t.id))
    current_wave = None
    for t in ordered:
        w = waves.get(t.id)
        if w != current_wave:
            current_wave = w
            label = f"Wave {w}" if w is not None else "Unordered (circular dependency)"
            lines.append(f"### {label}")
            lines.append("")

        marker = " [P]" if w == 1 else ""
        lines.append(f"#### {t.id} — {t.title}{marker}")
        if t.target_files:
            lines.append(f"**Files:** {', '.join(f'`{f}`' for f in t.target_files)}")
        if t.avoid_files:
            lines.append(f"**Do not touch:** {', '.join(f'`{f}`' for f in t.avoid_files)}")
        lines.append(f"**Depends on:** {', '.join(t.depends_on) if t.depends_on else 'none'}")
        if t.description:
            lines.append("")
            lines.append(t.description)
        if t.acceptance_criteria:
            lines.append("")
            lines.append("**Acceptance criteria:**")
            for ac in t.acceptance_criteria:
                lines.append(f"- {ac}")
        lines.append("")

    if plan.integration_notes:
        lines.append("## Integration Notes")
        lines.append("")
        lines.append(plan.integration_notes)
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"
