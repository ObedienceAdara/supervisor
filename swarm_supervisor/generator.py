"""
generator.py — Persist a TaskPlan to disk and collect iteration input.

Replaces the old regex-based "**AGENT N**" extraction entirely — planner.py
now hands back a structured TaskPlan directly, so this module's only job is
I/O: writing the Spec-Kit-style tasks.md, writing the raw plan.json (for
any other tool to consume), and reading back what the user pastes in for
the next iteration round.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from . import display as ui
from .tasks import TaskPlan, render_tasks_md
from .verifier import ConflictReport


def save_tasks_md(plan: TaskPlan, verification: Optional[ConflictReport],
                   output_dir: str, filename: Optional[str] = None) -> str:
    """Render and save the Spec-Kit-style tasks.md. Returns the saved path."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = out / (filename or f"tasks_{ts}.md")
    path.write_text(render_tasks_md(plan, verification), encoding="utf-8")
    return str(path)


def save_plan_json(plan: TaskPlan, verification: Optional[ConflictReport],
                    output_dir: str, filename: Optional[str] = None) -> str:
    """
    Save the raw plan (+ verification, if run) as JSON — the format any
    other tool (MCP client, another orchestrator, a CI job) can consume
    directly without parsing markdown.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = out / (filename or f"plan_{ts}.json")

    payload = plan.to_dict()
    if verification is not None:
        payload["verification"] = verification.to_dict()

    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return str(path)


def collect_iteration_results() -> str:
    """
    Read multi-line pasted text (this round's task results/diffs/summaries)
    from stdin, terminated by a line containing only 'END'.
    """
    ui.display_iteration_instructions()
    lines = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if line.strip() == "END":
            break
        lines.append(line)
    return "\n".join(lines)
