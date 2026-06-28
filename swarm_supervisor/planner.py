"""
planner.py — LLM planner for swarm-supervisor.

Builds the prompt context from codebase research, then calls
Claude (via Anthropic SDK) or Groq (raw HTTP) to generate the
7-agent execution plan.  Falls back to a deterministic template
when no API key is present.
"""

from __future__ import annotations

import json
import os
import textwrap
import urllib.error
import urllib.request
from typing import Optional

from . import display as ui

# ── Model defaults ────────────────────────────────────────────────────────────
DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-4-6"
DEFAULT_GROQ_MODEL      = "llama-3.3-70b-versatile"

# ── Lazy Anthropic import ─────────────────────────────────────────────────────
try:
    import anthropic as _anthropic_sdk
    HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False


# ═════════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ═════════════════════════════════════════════════════════════════════════════

def create_execution_plan(
    idea:       str,
    research:   dict,
    api_key:    Optional[str] = None,
    model:      Optional[str] = None,
    groq_key:   Optional[str] = None,
) -> str:
    """
    Analyse the codebase research snapshot and generate the 7-agent plan.

    Priority:
        1. Anthropic Claude  (ANTHROPIC_API_KEY env or --api-key flag)
        2. Groq              (GROQ_API_KEY env or --groq-key flag)
        3. Deterministic template fallback

    Parameters
    ----------
    idea      : the developer's high-level feature idea
    research  : output of researcher.research_codebase()
    api_key   : Anthropic API key (overrides env)
    model     : Anthropic model string (default: claude-sonnet-4-6)
    groq_key  : Groq API key (overrides env)

    Returns
    -------
    str — full plan text following the === AUTO-RESEARCHER PLAN === format
    """
    with ui.make_spinner("Generating 7-agent execution plan…") as sp:
        sp.add_task("")

        # ── 1. Try Anthropic ──────────────────────────────────────────────
        ant_key = api_key or os.getenv("ANTHROPIC_API_KEY", "")
        if ant_key and HAS_ANTHROPIC:
            result = _call_anthropic(idea, research, ant_key, model or DEFAULT_ANTHROPIC_MODEL)
            ui.success(f"Plan generated via Claude ({model or DEFAULT_ANTHROPIC_MODEL})")
            return result

        if ant_key and not HAS_ANTHROPIC:
            ui.warn("ANTHROPIC_API_KEY set but `anthropic` package not installed. "
                    "Run: pip install anthropic")

        # ── 2. Try Groq ───────────────────────────────────────────────────
        g_key = groq_key or os.getenv("GROQ_API_KEY", "")
        if g_key:
            result = _call_groq(idea, research, g_key)
            if result:
                ui.success(f"Plan generated via Groq ({DEFAULT_GROQ_MODEL})")
                return result

        # ── 3. Fallback template ──────────────────────────────────────────
        ui.warn(
            "No API key detected. Using deterministic template.\n"
            "    Set ANTHROPIC_API_KEY or GROQ_API_KEY for AI-powered planning."
        )
        return _template_plan(idea, research)


# ═════════════════════════════════════════════════════════════════════════════
# PROMPT BUILDER
# ═════════════════════════════════════════════════════════════════════════════

def build_planner_prompt(idea: str, research: dict) -> tuple[str, str]:
    """
    Construct (system_prompt, user_prompt) for the planning LLM call.

    Returns
    -------
    (system: str, user: str)
    """
    file_tree_str    = "\n".join(research["file_tree"][:100])
    function_map_str = json.dumps(research["function_map"], indent=2)

    # Summarise each file (first 40 lines to keep prompt manageable)
    content_blocks = []
    for fname, content in research["file_contents"].items():
        lines   = content.splitlines()
        preview = "\n".join(lines[:40])
        tail    = "\n..." if len(lines) > 40 else ""
        content_blocks.append(f"### {fname}\n```\n{preview}{tail}\n```")
    contents_str = "\n\n".join(content_blocks)

    system = textwrap.dedent("""
        You are a senior systems architect and elite prompt engineer.
        Your job is to:
          1. Analyse a developer's codebase snapshot.
          2. Understand the high-level feature idea.
          3. Produce a precise, opinionated execution plan.
          4. Generate EXACTLY 7 parallel, non-overlapping Qwen Code agent prompts.

        Output ONLY the structured plan — no preamble, no commentary, no apologies.
        Follow the output format EXACTLY as specified in the user message.
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

        ## Dependency Manifests
        ```
        {research['deps']}
        ```

        ## File Contents (truncated previews)
        {contents_str}

        ---

        ## Your Task

        Step 1 — Analyse the codebase and the idea above deeply.
        Step 2 — Create a numbered execution plan with EXACTLY 7 non-overlapping macro tasks.
        Step 3 — For each task, write one Qwen Code agent prompt that:
            • Is high-level but extremely precise.
            • Explicitly states what the agent MUST NOT touch (to prevent merge conflicts).
            • References exact filenames and function names from the codebase above.
            • Includes clear, binary success criteria.
            • Instructs the agent to output clean diffs and "Ask before edits" when uncertain.
        Step 4 — End with a short integration checklist.

        ## REQUIRED OUTPUT FORMAT (reproduce EXACTLY — no deviation):

        === AUTO-RESEARCHER PLAN ===
        1. [Task 1 description]
        2. [Task 2 description]
        3. [Task 3 description]
        4. [Task 4 description]
        5. [Task 5 description]
        6. [Task 6 description]
        7. [Task 7 description]

        === 7 AGENT PROMPTS (copy-paste ready) ===

        **AGENT 1 - [Clear Role Name]**
        [Full prompt text — minimum 5 sentences. Include: files to touch, files NOT to touch, functions to implement, success criteria, diff + ask-before-edits instruction.]

        **AGENT 2 - [Clear Role Name]**
        [Full prompt text]

        **AGENT 3 - [Clear Role Name]**
        [Full prompt text]

        **AGENT 4 - [Clear Role Name]**
        [Full prompt text]

        **AGENT 5 - [Clear Role Name]**
        [Full prompt text]

        **AGENT 6 - [Clear Role Name]**
        [Full prompt text]

        **AGENT 7 - [Clear Role Name]**
        [Full prompt text]

        === INSTRUCTIONS FOR ME ===
        - [Step-by-step integration checklist for after all 7 agents finish]
    """).strip()

    return system, user


# ═════════════════════════════════════════════════════════════════════════════
# LLM BACKENDS
# ═════════════════════════════════════════════════════════════════════════════

def _call_anthropic(idea: str, research: dict, api_key: str, model: str) -> str:
    system, user = build_planner_prompt(idea, research)
    client  = _anthropic_sdk.Anthropic(api_key=api_key)
    message = client.messages.create(
        model=model,
        max_tokens=4096,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return message.content[0].text


def _call_groq(idea: str, research: dict, groq_key: str) -> Optional[str]:
    """Call Groq's OpenAI-compatible endpoint using stdlib only (no SDK)."""
    system, user = build_planner_prompt(idea, research)

    payload = json.dumps({
        "model": DEFAULT_GROQ_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
        "max_tokens": 4096,
        "temperature": 0.3,
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=payload,
        headers={
            "Content-Type":  "application/json",
            "Authorization": f"Bearer {groq_key}",
        },
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


# ═════════════════════════════════════════════════════════════════════════════
# DETERMINISTIC TEMPLATE FALLBACK
# ═════════════════════════════════════════════════════════════════════════════

def _template_plan(idea: str, research: dict) -> str:
    """Generate a structured-but-generic plan with no LLM required."""
    files   = list(research["file_contents"].keys())
    primary = files[0] if files else "app.py"
    second  = files[1] if len(files) > 1 else "utils.py"
    deps    = research.get("deps", "")
    has_ts  = any(f.endswith((".ts", ".tsx", ".jsx", ".js")) for f in files)
    fe_note = "frontend (*.tsx / *.jsx)" if has_ts else "frontend/templates"

    return textwrap.dedent(f"""
        === AUTO-RESEARCHER PLAN ===
        1. Implement core data-layer logic for "{idea}" in {primary}
        2. Expose new functionality via API routes / endpoint layer
        3. Integrate new endpoints into {fe_note}
        4. Add / update data models, schemas, and DB migrations
        5. Write unit + integration tests covering all new code paths
        6. Update configuration, env vars, and dependency manifest
        7. Write docs, type-hints, inline comments; clean dead code

        === 7 AGENT PROMPTS (copy-paste ready) ===

        **AGENT 1 - Core Logic**
        You are working ONLY on `{primary}`.
        Implement the core backend logic required for: "{idea}".
        DO NOT touch: API route files, {fe_note} files, test files, config files.
        Your deliverable: new functions/classes that can be imported by the route layer.
        Success criteria: all new functions have type hints, docstrings, and are unit-testable in isolation.
        Output a clean unified diff. Ask before making any irreversible structural change.

        **AGENT 2 - API / Route Layer**
        You are working ONLY on the API or route files (e.g. routes.py, api.py, views.py, or equivalent).
        Add/update HTTP endpoints to expose the functionality built by Agent 1.
        DO NOT touch: {primary}, {fe_note} files, data-model files, test files.
        Success criteria: all endpoints return correct HTTP status codes, JSON schemas, and handle errors gracefully.
        Output a clean unified diff. Ask before edits.

        **AGENT 3 - Frontend / UI**
        You are working ONLY on {fe_note} files.
        Wire the UI to consume the new API endpoints from Agent 2.
        DO NOT touch: backend Python files, data models, test files, config.
        Success criteria: UI renders new feature correctly, including loading and error states.
        Output a clean unified diff. Ask before edits.

        **AGENT 4 - Data Models / Schemas**
        You are working ONLY on model, schema, or database layer files (e.g. models.py, schemas.py).
        Add or update data structures required by: "{idea}".
        DO NOT touch: route files, {fe_note} files, test files, {primary}.
        Success criteria: models validated (Pydantic / SQLAlchemy / equivalent), migrations run cleanly.
        Output a clean unified diff. Ask before edits.

        **AGENT 5 - Tests**
        You are working ONLY on the test suite (tests/ directory or test_*.py files).
        Write unit + integration tests covering all new functions added for: "{idea}".
        DO NOT modify any non-test source files.
        Success criteria: `pytest` passes with >80% coverage on new code paths.
        Output a clean unified diff. Ask before edits.

        **AGENT 6 - Config & Dependencies**
        You are working ONLY on requirements.txt, .env.example, config files, and Dockerfile (if present).
        Add new dependencies, environment variables, and configuration blocks needed for: "{idea}".
        DO NOT touch application logic or test files.
        Success criteria: project runs from a fresh clone with your updated setup instructions alone.
        Output a clean unified diff. Ask before edits.

        **AGENT 7 - Docs, Types & Cleanup**
        You are working ONLY on README.md, docstrings, inline comments, and type annotations.
        Document all new functionality. Remove dead code. Add missing type hints.
        DO NOT change any runtime logic.
        Success criteria: a new developer can fully understand the feature from docs and type hints alone.
        Output a clean unified diff. Ask before edits.

        === INSTRUCTIONS FOR ME ===
        - Open 7 Qwen Code windows simultaneously
        - Paste one agent prompt into each window — they work on non-overlapping files
        - Run all 7 in parallel
        - When all 7 finish: collect their diffs, apply them in order (4 → 1 → 2 → 3 → 5 → 6 → 7)
        - Run test suite to confirm green
        - Paste all results back and run `supervisor --iterate` for the next integration round
    """).strip()


# ═════════════════════════════════════════════════════════════════════════════
# ITERATION PLANNER
# ═════════════════════════════════════════════════════════════════════════════

def plan_next_iteration(
    idea:          str,
    original_plan: str,
    agent_results: str,
    research:      dict,
    api_key:       Optional[str] = None,
    model:         Optional[str] = None,
    groq_key:      Optional[str] = None,
) -> str:
    """
    Given the results from round 1 agents, plan round 2.

    Builds a new prompt from the combined context (original idea +
    previous plan + agent outputs) and fires the same LLM chain.
    """
    system = (
        "You are a senior systems architect running iteration 2 of an "
        "automated 7-agent code swarm. Analyse what was built, identify "
        "integration points and remaining gaps, then generate a NEW set "
        "of exactly 7 non-overlapping agent prompts following the same "
        "=== AUTO-RESEARCHER PLAN === format."
    )

    user = textwrap.dedent(f"""
        ## Original Idea
        {idea}

        ## Round 1 Execution Plan
        {original_plan}

        ## Round 1 Agent Results (diffs / summaries from all 7 agents)
        {agent_results}

        ---

        Identify:
        1. What was successfully completed.
        2. What needs integration or conflict resolution.
        3. What new tasks remain.

        Then produce the next 7-agent plan in EXACTLY the same format as before.
    """).strip()

    with ui.make_spinner("Planning iteration 2…") as sp:
        sp.add_task("")

        ant_key = api_key or os.getenv("ANTHROPIC_API_KEY", "")
        if ant_key and HAS_ANTHROPIC:
            client  = _anthropic_sdk.Anthropic(api_key=ant_key)
            message = client.messages.create(
                model=model or DEFAULT_ANTHROPIC_MODEL,
                max_tokens=4096,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            ui.success("Iteration 2 plan generated via Claude")
            return message.content[0].text

        g_key = groq_key or os.getenv("GROQ_API_KEY", "")
        if g_key:
            payload = json.dumps({
                "model": DEFAULT_GROQ_MODEL,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user",   "content": user},
                ],
                "max_tokens": 4096,
                "temperature": 0.3,
            }).encode("utf-8")
            req = urllib.request.Request(
                "https://api.groq.com/openai/v1/chat/completions",
                data=payload,
                headers={
                    "Content-Type":  "application/json",
                    "Authorization": f"Bearer {g_key}",
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=90) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                ui.success(f"Iteration 2 plan generated via Groq ({DEFAULT_GROQ_MODEL})")
                return data["choices"][0]["message"]["content"]
            except Exception as exc:
                ui.error(f"Groq iteration call failed: {exc}")

    ui.warn("No API key — returning empty iteration plan.")
    return "No API key available for iteration 2 planning."
