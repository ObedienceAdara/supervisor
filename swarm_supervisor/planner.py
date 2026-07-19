"""
planner.py — LLM planner for swarm-supervisor.

Builds prompt context from codebase research (including dependency-graph
hotspots, so the model sees likely trouble spots before it plans around
them) and calls Claude (Anthropic SDK) or Groq (stdlib HTTP) to produce a
TaskPlan. Falls back to a deterministic template when no API key is set.

Two things changed from v1, both deliberate:
  · No fixed task count. The prompt asks for however many independent
    tasks the idea actually needs (typically 2-10) instead of forcing 7.
  · No named target tool. The model is asked for structured JSON — a
    TaskPlan — not markdown formatted for pasting into one specific CLI.
    Structured output is also just more reliable to parse than hoping an
    LLM reproduces a "**AGENT N - Role**" heading exactly every time.
"""

from __future__ import annotations

import json
import os
import textwrap
import urllib.error
import urllib.request
from typing import Optional

from . import display as ui
from .depgraph import build_from_research
from .tasks import TaskPlan, TaskPlanParseError, parse_llm_json

# ── Model defaults ────────────────────────────────────────────────────────────
# NOTE: check these periodically — provider model catalogs are retired /
# renamed faster than this file gets updated. `supervisor init` lets you
# override with any model string.
DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-4-6"
DEFAULT_GROQ_MODEL      = "llama-3.3-70b-versatile"

_MAX_PARSE_RETRIES = 1  # one retry with a sterner reminder before giving up

# ── Lazy Anthropic import ─────────────────────────────────────────────────────
try:
    import anthropic as _anthropic_sdk
    HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False


# ═════════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ═════════════════════════════════════════════════════════════════════════════

def create_task_plan(
    idea:      str,
    research:  dict,
    api_key:   Optional[str] = None,
    model:     Optional[str] = None,
    groq_key:  Optional[str] = None,
) -> TaskPlan:
    """
    Analyse the codebase research snapshot and return a TaskPlan.

    Priority: Anthropic Claude → Groq → deterministic template fallback.
    Raises TaskPlanParseError only if an LLM responded but never produced
    parseable JSON even after one retry — callers should treat that as
    "replan or fall back," not silently proceed.
    """
    with ui.make_spinner("Decomposing idea into a task plan…") as sp:
        sp.add_task("")

        ant_key = api_key or os.getenv("ANTHROPIC_API_KEY", "")
        if ant_key and HAS_ANTHROPIC:
            raw = _call_anthropic_with_retries(idea, research, ant_key, model or DEFAULT_ANTHROPIC_MODEL)
            if raw is not None:
                plan = parse_llm_json(raw, idea_fallback=idea)
                ui.success(f"Plan generated via Claude ({model or DEFAULT_ANTHROPIC_MODEL}) — {len(plan.tasks)} task(s)")
                return plan

        if ant_key and not HAS_ANTHROPIC:
            ui.warn("ANTHROPIC_API_KEY set but `anthropic` package not installed. "
                    "Run: pip install anthropic")

        g_key = groq_key or os.getenv("GROQ_API_KEY", "")
        if g_key:
            raw = _call_groq_with_retries(idea, research, g_key)
            if raw is not None:
                plan = parse_llm_json(raw, idea_fallback=idea)
                ui.success(f"Plan generated via Groq ({DEFAULT_GROQ_MODEL}) — {len(plan.tasks)} task(s)")
                return plan

        ui.warn(
            "No API key detected (or the model never returned parseable JSON). "
            "Using deterministic template.\n"
            "    Set ANTHROPIC_API_KEY or GROQ_API_KEY for AI-powered planning."
        )
        return _template_plan(idea, research)


def plan_next_iteration(
    idea:           str,
    previous_plan:  TaskPlan,
    results_text:   str,
    research:       dict,
    verification:   Optional[dict] = None,
    api_key:        Optional[str] = None,
    model:          Optional[str] = None,
    groq_key:       Optional[str] = None,
) -> TaskPlan:
    """
    Given the results from the previous round's tasks (and, if available,
    that round's dependency-graph verification report), plan the next round.
    If the previous plan came back RISKY/CONFLICT, the specific conflicts
    are fed back in so the model corrects them instead of repeating them.
    """
    system = textwrap.dedent("""
        You are a senior systems architect running the next iteration of an
        automated task-decomposition tool. Analyse what was built, identify
        integration points and remaining gaps, then produce a NEW TaskPlan
        as JSON, following the exact schema you were given previously.
        Output ONLY the JSON object — no commentary, no markdown fences.
    """).strip()

    verification_block = ""
    if verification and verification.get("verdict") != "SAFE":
        verification_block = textwrap.dedent(f"""
            ## Previous Round's Dependency-Graph Verification (fix these)
            Verdict: {verification.get('verdict')}  (score {verification.get('score')}/100)
            Direct conflicts: {json.dumps(verification.get('direct_conflicts', []))}
            Coupling risks: {len(verification.get('coupling_risks', []))} cross-task edge(s)
            Hotspot hits: {json.dumps(verification.get('hotspot_hits', []))}

            The new plan MUST resolve every direct conflict above (no two tasks may
            claim the same file) and should reduce coupling/hotspot overlap where
            possible.
        """).strip()

    user = textwrap.dedent(f"""
        ## Original Idea
        {idea}

        ## Previous Round's Task Plan
        {previous_plan.to_json()}

        ## Previous Round's Results (diffs / summaries from that round's tasks)
        {results_text}

        {verification_block}

        ---

        Identify:
        1. What was successfully completed.
        2. What needs integration or conflict resolution.
        3. What new tasks remain.

        Then produce the next TaskPlan as JSON, in the same schema as before.
        Use however many tasks the remaining work actually needs.
    """).strip()

    with ui.make_spinner("Planning next iteration…") as sp:
        sp.add_task("")

        ant_key = api_key or os.getenv("ANTHROPIC_API_KEY", "")
        if ant_key and HAS_ANTHROPIC:
            raw = _anthropic_raw_call(system, user, ant_key, model or DEFAULT_ANTHROPIC_MODEL)
            if raw:
                try:
                    plan = parse_llm_json(raw, idea_fallback=idea)
                    ui.success(f"Next iteration plan generated via Claude — {len(plan.tasks)} task(s)")
                    return plan
                except TaskPlanParseError as exc:
                    ui.error(f"Could not parse iteration plan: {exc}")

        g_key = groq_key or os.getenv("GROQ_API_KEY", "")
        if g_key:
            raw = _groq_raw_call(system, user, g_key)
            if raw:
                try:
                    plan = parse_llm_json(raw, idea_fallback=idea)
                    ui.success(f"Next iteration plan generated via Groq — {len(plan.tasks)} task(s)")
                    return plan
                except TaskPlanParseError as exc:
                    ui.error(f"Could not parse iteration plan: {exc}")

    ui.warn("No usable API response — returning the previous plan unchanged.")
    return previous_plan


# ═════════════════════════════════════════════════════════════════════════════
# PROMPT BUILDER
# ═════════════════════════════════════════════════════════════════════════════

_JSON_SCHEMA_INSTRUCTIONS = textwrap.dedent("""
    Respond with ONLY a single JSON object — no preamble, no commentary, no
    markdown code fences — matching this exact schema:

    {
      "idea": "<restated idea, one line>",
      "tasks": [
        {
          "id": "T1",
          "title": "<short task name>",
          "description": "<what to build, specific enough to hand to any coding agent>",
          "target_files": ["<exact relative file paths this task will create or edit>"],
          "avoid_files": ["<files this task must NOT touch, to prevent conflicts>"],
          "depends_on": ["<ids of tasks that must land first, or [] if independent>"],
          "acceptance_criteria": ["<binary, checkable criteria>"]
        }
      ],
      "integration_notes": "<how to merge/order the tasks once all are done>"
    }

    Rules:
    - Choose however many tasks the idea's actual scope needs — typically
      2 to 10. Do not force a fixed count. A one-line change might need 1-2
      tasks; a multi-layer feature might need 6-8. Never pad with filler
      tasks just to hit a number.
    - target_files must use exact relative paths from the file tree given
      below. Two tasks must never list the same file in target_files.
    - Prefer giving each task files it can complete independently of tasks
      in the same wave (i.e. tasks with no depends_on between them).
    - Be specific: reference real filenames and function/symbol names from
      the codebase context, not generic placeholders.
""").strip()


def build_planner_prompt(idea: str, research: dict) -> tuple[str, str]:
    """Construct (system_prompt, user_prompt) for the planning LLM call."""
    file_tree_str    = "\n".join(research["file_tree"][:150])
    function_map_str = json.dumps(research["function_map"], indent=2)

    graph = build_from_research(research)
    hotspots = graph.hotspots()[:10]
    hotspot_str = (
        "\n".join(f"- {h['file']} ({h['reason']})" for h in hotspots)
        or "None detected."
    )

    content_blocks = []
    for fname, content in research["file_contents"].items():
        lines   = content.splitlines()
        preview = "\n".join(lines[:40])
        tail    = "\n..." if len(lines) > 40 else ""
        content_blocks.append(f"### {fname}\n```\n{preview}{tail}\n```")
    contents_str = "\n\n".join(content_blocks)

    system = textwrap.dedent("""
        You are a senior systems architect. Your job is to turn a developer's
        feature idea plus a codebase snapshot into a precise, independently
        executable task plan — the kind that could be handed to several
        coding agents (or several human contributors) working in parallel
        without stepping on each other's files.

        You are NOT told which specific coding agent or tool will execute
        these tasks. Write task descriptions that are agent-agnostic — clear
        enough for any capable coding agent or developer to execute exactly.
    """).strip()

    user = textwrap.dedent(f"""
        ## Developer's Feature Idea
        {idea}

        ## Project File Tree
        ```
        {file_tree_str}
        ```

        ## Python Symbol Map (AST-extracted)
        ```json
        {function_map_str}
        ```

        ## Dependency-Graph Hotspots (files already heavily depended-upon —
        avoid assigning these to more than one task where possible)
        {hotspot_str}

        ## Dependency Manifests
        ```
        {research['deps']}
        ```

        ## File Contents (truncated previews)
        {contents_str}

        ---

        {_JSON_SCHEMA_INSTRUCTIONS}
    """).strip()

    return system, user


# ═════════════════════════════════════════════════════════════════════════════
# LLM BACKENDS
# ═════════════════════════════════════════════════════════════════════════════

def _call_anthropic_with_retries(idea: str, research: dict, api_key: str, model: str) -> Optional[str]:
    system, user = build_planner_prompt(idea, research)
    return _anthropic_raw_call_with_retry(system, user, api_key, model)


def _call_groq_with_retries(idea: str, research: dict, groq_key: str) -> Optional[str]:
    system, user = build_planner_prompt(idea, research)
    return _groq_raw_call_with_retry(system, user, groq_key)


def _anthropic_raw_call(system: str, user: str, api_key: str, model: str) -> Optional[str]:
    try:
        client  = _anthropic_sdk.Anthropic(api_key=api_key)
        message = client.messages.create(
            model=model, max_tokens=4096, system=system,
            messages=[{"role": "user", "content": user}],
        )
        return message.content[0].text
    except Exception as exc:
        ui.error(f"Anthropic request failed: {exc}")
        return None


def _anthropic_raw_call_with_retry(system: str, user: str, api_key: str, model: str) -> Optional[str]:
    """Call Anthropic, and if the response isn't parseable JSON, retry once with a sterner reminder."""
    raw = _anthropic_raw_call(system, user, api_key, model)
    if raw is None:
        return None
    if _looks_parseable(raw):
        return raw
    stern_user = user + "\n\nREMINDER: respond with ONLY the JSON object. No prose, no fences."
    return _anthropic_raw_call(system, stern_user, api_key, model) or raw


def _groq_raw_call(system: str, user: str, groq_key: str) -> Optional[str]:
    payload = json.dumps({
        "model": DEFAULT_GROQ_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
        "max_tokens": 4096,
        "temperature": 0.2,
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=payload,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {groq_key}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        ui.error(f"Groq HTTP {exc.code}: {body[:300]}")
        return None
    except Exception as exc:
        ui.error(f"Groq request failed: {exc}")
        return None


def _groq_raw_call_with_retry(system: str, user: str, groq_key: str) -> Optional[str]:
    raw = _groq_raw_call(system, user, groq_key)
    if raw is None:
        return None
    if _looks_parseable(raw):
        return raw
    stern_user = user + "\n\nREMINDER: respond with ONLY the JSON object. No prose, no fences."
    return _groq_raw_call(system, stern_user, groq_key) or raw


def _looks_parseable(raw: str) -> bool:
    """Cheap pre-check so we don't burn a retry on obviously-fine output."""
    try:
        parse_llm_json(raw)
        return True
    except TaskPlanParseError:
        return False


# ═════════════════════════════════════════════════════════════════════════════
# DETERMINISTIC TEMPLATE FALLBACK
# ═════════════════════════════════════════════════════════════════════════════

def _template_plan(idea: str, research: dict) -> TaskPlan:
    """
    Generate a structured-but-generic TaskPlan with no LLM required.
    Task count adapts to what's actually present in the codebase — a repo
    with no test directory doesn't get a fabricated "write tests" task
    pointed at files that don't exist.
    """
    files  = list(research["file_contents"].keys())
    tree   = research.get("file_tree", [])
    has_ts = any(f.endswith((".ts", ".tsx", ".jsx", ".js")) for f in tree)
    has_tests = any("test" in f.lower() for f in tree)
    fe_note = "frontend (*.tsx / *.jsx)" if has_ts else "frontend/templates"

    primary = files[0] if files else "app.py"
    tasks = [
        {
            "id": "T1", "title": "Core logic",
            "description": f'Implement the core backend logic required for: "{idea}".',
            "target_files": [primary],
            "avoid_files": [],
            "depends_on": [],
            "acceptance_criteria": ["New functions have type hints and docstrings",
                                     "Logic is unit-testable in isolation"],
        },
        {
            "id": "T2", "title": "API / route layer",
            "description": "Expose the new functionality via API routes or an endpoint layer.",
            "target_files": [], "avoid_files": [primary],
            "depends_on": ["T1"],
            "acceptance_criteria": ["Endpoints return correct status codes",
                                     "Errors are handled gracefully"],
        },
    ]
    if has_ts:
        tasks.append({
            "id": "T3", "title": "Frontend integration",
            "description": f"Wire the {fe_note} to consume the new API endpoints.",
            "target_files": [], "avoid_files": [primary],
            "depends_on": ["T2"],
            "acceptance_criteria": ["UI renders the new feature, including loading/error states"],
        })
    if has_tests:
        tasks.append({
            "id": f"T{len(tasks)+1}", "title": "Tests",
            "description": f'Write unit + integration tests covering the new code paths for: "{idea}".',
            "target_files": [], "avoid_files": [],
            "depends_on": ["T1"],
            "acceptance_criteria": ["Test suite passes", "New code paths are covered"],
        })
    tasks.append({
        "id": f"T{len(tasks)+1}", "title": "Docs & cleanup",
        "description": "Document the new functionality and remove any dead code touched along the way.",
        "target_files": [], "avoid_files": [],
        "depends_on": ["T1"],
        "acceptance_criteria": ["README/docstrings updated", "No dead code left behind"],
    })

    plan_dict = {
        "idea": idea,
        "tasks": tasks,
        "integration_notes": (
            "No API key was configured, so this is a generic template — not "
            "codebase-aware beyond file/language detection. Run `supervisor "
            "verify` on it before executing, and set ANTHROPIC_API_KEY or "
            "GROQ_API_KEY for a plan that actually reasons about this repo."
        ),
    }
    return TaskPlan.from_dict(plan_dict)
