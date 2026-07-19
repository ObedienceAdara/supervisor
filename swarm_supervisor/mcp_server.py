"""
mcp_server.py — Expose swarm-supervisor as an MCP server.

This is the actual distribution strategy: instead of asking developers to
install and learn a standalone CLI, expose the same capabilities as MCP
tools that Claude Code, Vibe Kanban, Claude Squad, or any other MCP-capable
client can call directly, in whatever workflow they already have.

The most important tool here is `verify_task_plan` — it does NOT require
this package's own LLM planner. Any client can propose its own task split
(however it decomposed the work) and hand it to this tool for a real,
dependency-graph-grounded conflict check. That's the piece meant to be
useful standalone, independent of whether anyone ever uses this project's
CLI or planner at all.

Requires: pip install mcp
Run with: supervisor mcp   (or: python -m swarm_supervisor.mcp_server)
"""

from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

from . import __version__
from .config import resolve_anthropic_key, resolve_groq_key, resolve_model
from .depgraph import build_from_research
from .planner import create_task_plan
from .researcher import research_codebase
from .tasks import TaskPlan, TaskPlanParseError, render_tasks_md
from .verifier import verify_task_plan as _verify_task_plan

mcp = FastMCP("swarm-supervisor")


@mcp.tool()
def scan_codebase(project_dir: str) -> dict:
    """
    Scan a local codebase and return a compact structural summary: detected
    languages, file counts, and dependency-graph hotspots (files likely to
    cause conflicts if claimed by more than one task). Does not return full
    file contents — use this for a quick structural read before planning.
    """
    try:
        research = research_codebase(project_dir)
    except SystemExit:
        return {"error": f"project_dir not found: {project_dir}"}

    graph = build_from_research(research)
    return {
        "project_dir": research["project_dir"],
        "file_count": len(research["file_tree"]),
        "python_modules": len(research["function_map"]),
        "total_chars_indexed": research["total_chars"],
        "dependency_graph": graph.to_summary(),
    }


@mcp.tool()
def decompose_idea(project_dir: str, idea: str, model: str = "") -> dict:
    """
    Scan a codebase and decompose a feature idea into a TaskPlan using the
    configured LLM provider (resolved from ~/.supervisor/config.json or
    ANTHROPIC_API_KEY / GROQ_API_KEY env vars — this tool never accepts an
    API key as a parameter, to avoid it passing through MCP call logs).
    Task count is adaptive, not fixed. Falls back to a deterministic
    template if no provider is configured.

    Returns {"task_plan": {...}, "verification": {...}} — the plan is
    already checked against this codebase's dependency graph before it's
    returned, so a caller can inspect `verification.verdict` immediately.
    """
    try:
        research = research_codebase(project_dir)
    except SystemExit:
        return {"error": f"project_dir not found: {project_dir}"}

    ant_key  = resolve_anthropic_key()
    groq_key = resolve_groq_key()
    resolved_model = model or resolve_model()

    try:
        plan = create_task_plan(
            idea=idea, research=research,
            api_key=ant_key, model=resolved_model, groq_key=groq_key,
        )
    except TaskPlanParseError as exc:
        return {"error": f"Planner did not return a parseable task plan: {exc}"}

    graph  = build_from_research(research)
    report = _verify_task_plan(plan, graph)

    return {"task_plan": plan.to_dict(), "verification": report.to_dict()}


@mcp.tool()
def verify_task_plan(project_dir: str, tasks_json: str) -> dict:
    """
    Check whether a proposed task split is actually independent — the core
    tool. Works on ANY task plan, not just ones this package generated:
    hand it Claude Code's own decomposition, a hand-written tasks.json,
    output from another orchestrator, anything matching the schema below.

    tasks_json must be a JSON string with at least:
      {"tasks": [{"id": "T1", "title": "...", "target_files": ["a.py"], ...}]}

    Returns a ConflictReport: score (0-100), verdict (SAFE/RISKY/CONFLICT),
    direct_conflicts (files claimed by 2+ tasks), coupling_risks (real
    import/call edges crossing task boundaries), and hotspot_hits (shared-
    surface files touched by more than one task). This check is entirely
    local static analysis — no LLM call, no network access beyond reading
    the given project_dir.
    """
    try:
        data = json.loads(tasks_json)
    except json.JSONDecodeError as exc:
        return {"error": f"tasks_json is not valid JSON: {exc}"}

    try:
        plan = TaskPlan.from_dict(data)
    except Exception as exc:
        return {"error": f"Could not read a TaskPlan from tasks_json: {exc}"}

    if not plan.tasks:
        return {"error": "No tasks found in tasks_json."}

    try:
        research = research_codebase(project_dir)
    except SystemExit:
        return {"error": f"project_dir not found: {project_dir}"}

    graph  = build_from_research(research)
    report = _verify_task_plan(plan, graph)
    return report.to_dict()


@mcp.tool()
def render_tasks_markdown(tasks_json: str) -> str:
    """
    Render a TaskPlan (optionally with an embedded "verification" key, as
    returned by decompose_idea or verify_task_plan) as a Spec-Kit-style
    tasks.md: dependency-ordered, [P]-marked for tasks with no unresolved
    dependencies, no target-tool name baked in.
    """
    data = json.loads(tasks_json)
    verification_dict = data.pop("verification", None)
    plan = TaskPlan.from_dict(data)

    verification = None
    if verification_dict:
        from .verifier import ConflictReport
        verification = ConflictReport(
            score=verification_dict.get("score", 0),
            verdict=verification_dict.get("verdict", "RISKY"),
            direct_conflicts=verification_dict.get("direct_conflicts", []),
            coupling_risks=verification_dict.get("coupling_risks", []),
            hotspot_hits=verification_dict.get("hotspot_hits", []),
            unclaimed_dependency_files=verification_dict.get("unclaimed_dependency_files", []),
            notes=verification_dict.get("notes", []),
        )

    return render_tasks_md(plan, verification)


def run_server() -> None:
    """Entry point for `supervisor mcp` — runs the MCP server over stdio."""
    mcp.run()


if __name__ == "__main__":
    run_server()
