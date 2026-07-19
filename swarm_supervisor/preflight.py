"""
preflight.py — Pre-flight analysis + idea clarification engine.

Two responsibilities:

1. PRE-FLIGHT BRIEFING
   After the codebase is scanned, display a summary of what was found
   (stack detected, key files, language mix, dependency-graph hotspots,
   estimated complexity) and ask the user to confirm before calling the LLM.

2. IDEA CLARIFICATION
   Score the idea for vagueness. If it scores below a threshold, ask up to
   3 targeted follow-up questions and fold the answers into an enriched
   idea string before planning.
"""

from __future__ import annotations

import re
from pathlib import Path

from . import display as ui
from .depgraph import build_from_research

# ── Vagueness scoring ─────────────────────────────────────────────────────────
_VAGUE_WORDS = {
    "improve", "fix", "better", "update", "enhance", "clean", "refactor",
    "optimize", "upgrade", "change", "make", "do", "some",
    "things", "stuff", "something", "anything", "everything", "misc",
    "various", "general", "overall", "little",
}
_MIN_IDEA_WORDS      = 5     # fewer than this → always clarify
_VAGUENESS_THRESHOLD = 0.35  # ratio of vague tokens → clarify


# ═════════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ═════════════════════════════════════════════════════════════════════════════

def show_preflight(research: dict, idea: str) -> bool:
    """
    Display a pre-flight briefing (stack, key files, dependency-graph
    hotspots) and ask the user to confirm before calling the LLM.

    Returns True if the user confirmed, False if they aborted.
    """
    stack     = _detect_stack(research)
    key_files = _identify_key_files(research)
    stats     = _build_stats(research)
    graph     = build_from_research(research)

    _render_preflight(idea, stack, key_files, stats, graph.to_summary())
    return _ask_proceed()


def maybe_clarify(idea: str, research: dict, enabled: bool = True) -> str:
    """
    If the idea seems vague, ask targeted clarifying questions and return
    an enriched idea string. Returns the idea unchanged if disabled or
    already specific enough.
    """
    if not enabled:
        return idea

    score = _vagueness_score(idea)
    words = len(idea.split())

    if words >= _MIN_IDEA_WORDS and score < _VAGUENESS_THRESHOLD:
        return idea

    ui.blank()
    _render_clarification_header(idea, score, words)
    ui.blank()

    questions = _build_questions(idea, research)
    answers   = []

    for i, (q, hint) in enumerate(questions, 1):
        answer = _ask_question(i, len(questions), q, hint)
        if answer.strip():
            answers.append(f"{q.rstrip('?')}: {answer.strip()}")

    if not answers:
        return idea

    enriched = idea + "\n\nAdditional context from clarification:\n" + "\n".join(
        f"  - {a}" for a in answers
    )

    ui.blank()
    ui.success("Idea enriched with your answers.")
    return enriched


# ═════════════════════════════════════════════════════════════════════════════
# STACK DETECTION
# ═════════════════════════════════════════════════════════════════════════════

def _detect_stack(research: dict) -> dict:
    """Infer the tech stack from file extensions and dependency manifest."""
    files    = research.get("file_tree", [])
    deps     = research.get("deps", "").lower()
    suffixes = [Path(f).suffix.lower() for f in files]

    langs: list = []
    if ".py" in suffixes: langs.append("Python")
    if ".ts" in suffixes or ".tsx" in suffixes: langs.append("TypeScript")
    if ".js" in suffixes or ".jsx" in suffixes: langs.append("JavaScript")
    if ".go" in suffixes: langs.append("Go")
    if ".rs" in suffixes: langs.append("Rust")
    if ".rb" in suffixes: langs.append("Ruby")
    if ".java" in suffixes: langs.append("Java")

    frameworks: list = []
    if "fastapi"    in deps: frameworks.append("FastAPI")
    if "flask"      in deps: frameworks.append("Flask")
    if "django"     in deps: frameworks.append("Django")
    if "langchain"  in deps: frameworks.append("LangChain")
    if "langgraph"  in deps: frameworks.append("LangGraph")
    if "openai"     in deps: frameworks.append("OpenAI SDK")
    if "anthropic"  in deps: frameworks.append("Anthropic SDK")
    if "sqlalchemy" in deps: frameworks.append("SQLAlchemy")
    if "pydantic"   in deps: frameworks.append("Pydantic")
    if "celery"     in deps: frameworks.append("Celery")
    if "redis"      in deps: frameworks.append("Redis")
    if "faiss"      in deps: frameworks.append("FAISS")
    if "chromadb"   in deps: frameworks.append("ChromaDB")
    if "n8n"        in deps: frameworks.append("n8n")
    if "react"      in deps: frameworks.append("React")
    if "next"       in deps: frameworks.append("Next.js")
    if "vue"        in deps: frameworks.append("Vue")
    if "express"    in deps: frameworks.append("Express")

    file_count = len(files)
    if file_count < 10:
        complexity = "Small"
    elif file_count < 50:
        complexity = "Medium"
    elif file_count < 200:
        complexity = "Large"
    else:
        complexity = "Very Large"

    return {
        "languages":  langs or ["Unknown"],
        "frameworks": frameworks,
        "complexity": complexity,
        "file_count": file_count,
    }


def _identify_key_files(research: dict) -> list:
    """Return a short list of the most architecturally significant files."""
    key_patterns = [
        "app.py", "main.py", "server.py", "api.py", "routes.py",
        "views.py", "models.py", "schemas.py", "config.py", "settings.py",
        "index.ts", "index.js", "app.ts", "app.tsx",
        "Dockerfile", "docker-compose.yml", "docker-compose.yaml",
        "requirements.txt", "package.json", "pyproject.toml", "README.md",
    ]
    found    = []
    tree_set = {Path(f).name for f in research.get("file_tree", [])}
    for pat in key_patterns:
        if pat in tree_set:
            found.append(pat)
    for f in research.get("file_tree", []):
        name = Path(f).name.lower()
        if any(kw in name for kw in ("agent", "llm", "rag", "vector", "chain")):
            if f not in found:
                found.append(f)
    return found[:12]


def _build_stats(research: dict) -> dict:
    fm = research.get("function_map", {})
    return {
        "files_read":     len(research.get("file_contents", {})),
        "total_chars":    research.get("total_chars", 0),
        "python_modules": len(fm),
        "total_symbols":  sum(len(v) for v in fm.values()),
    }


# ═════════════════════════════════════════════════════════════════════════════
# RENDER PREFLIGHT
# ═════════════════════════════════════════════════════════════════════════════

def _render_preflight(idea: str, stack: dict, key_files: list, stats: dict, graph_summary: dict) -> None:
    hotspots = graph_summary.get("top_hotspots", [])

    if not ui.RICH:
        print("\n=== PRE-FLIGHT BRIEFING ===")
        print(f"Idea    : {_trunc(idea, 80)}")
        print(f"Stack   : {', '.join(stack['languages'])}")
        print(f"Files   : {stack['file_count']} found, {stats['files_read']} read")
        print(f"Key     : {', '.join(key_files[:6])}")
        print(f"Graph   : {graph_summary['edge_count']} edges "
              f"({graph_summary['import_edges']} import, {graph_summary['call_edges']} call)")
        if hotspots:
            print(f"Hotspots: {', '.join(h['file'] for h in hotspots[:5])}")
        print()
        return

    from rich.panel import Panel
    from rich.text import Text
    from rich import box as rbox

    kf_text = "\n".join(f"  [cyan]·[/cyan] {f}" for f in key_files) or "  [dim]none detected[/dim]"
    hs_text = (
        "\n".join(f"  [yellow]·[/yellow] {h['file']}  [dim]({h['reason']})[/dim]" for h in hotspots[:5])
        or "  [dim]none detected[/dim]"
    )

    ui.console.print()
    ui.console.print(
        Panel(
            Text.from_markup(
                f"[bold white]Idea:[/bold white]  [italic cyan]{_trunc(idea, 100)}[/italic cyan]\n\n"
                f"[bold white]Stack:[/bold white]  [white]{', '.join(stack['languages'])}[/white]"
                + (f"  ·  [dim]{', '.join(stack['frameworks'][:4])}[/dim]" if stack["frameworks"] else "")
                + f"\n[bold white]Size:[/bold white]   {stack['complexity']}  ({stack['file_count']} files, "
                f"{stats['total_chars']:,} chars, {stats['total_symbols']} symbols)\n\n"
                f"[bold white]Dependency graph:[/bold white]  {graph_summary['edge_count']} edges "
                f"({graph_summary['import_edges']} import · {graph_summary['call_edges']} call)\n\n"
                f"[bold white]Key files:[/bold white]\n{kf_text}\n\n"
                f"[bold white]Likely conflict hotspots:[/bold white]\n{hs_text}"
            ),
            title="[bold cyan]🛫  PRE-FLIGHT BRIEFING[/bold cyan]",
            border_style="cyan",
            box=rbox.ROUNDED,
            padding=(1, 2),
        )
    )


# ═════════════════════════════════════════════════════════════════════════════
# CLARIFICATION
# ═════════════════════════════════════════════════════════════════════════════

def _vagueness_score(idea: str) -> float:
    tokens = re.findall(r"\w+", idea.lower())
    if not tokens:
        return 1.0
    vague = sum(1 for t in tokens if t in _VAGUE_WORDS)
    return vague / len(tokens)


def _build_questions(idea: str, research: dict) -> list:
    """Generate up to 3 targeted questions based on the idea + codebase context."""
    stack = _detect_stack(research)
    qs: list = []
    idea_lower = idea.lower()

    if len(idea.split()) < 8 or any(w in idea_lower for w in ("improve", "fix", "better", "update")):
        qs.append((
            "What exactly do you want to change or add?",
            "e.g. 'Add FAISS vector search to the /query endpoint in app.py'"
            + (f" (detected stack: {', '.join(stack['languages'])})" if stack["languages"] else ""),
        ))

    if len(qs) < 3:
        qs.append((
            "Any constraints? (no new deps, backward compat, performance budget, etc.)",
            "e.g. 'No new Python packages', 'Must stay under 200ms', 'Keep existing API contract'",
        ))

    if len(qs) < 3:
        qs.append((
            "How will you know it's done? What's the success criteria?",
            "e.g. 'All existing tests pass + new benchmark shows <50ms latency'",
        ))

    return qs[:3]


def _render_clarification_header(idea: str, score: float, words: int) -> None:
    reason = (
        f"idea is only {words} word{'s' if words != 1 else ''}"
        if words < _MIN_IDEA_WORDS
        else f"~{int(score*100)}% vague tokens detected"
    )
    if not ui.RICH:
        print(f"\n[Clarification needed — {reason}]")
        print(f"Idea: {idea}")
        print("(Press Enter to skip any question)\n")
        return

    from rich.panel import Panel
    from rich.text import Text
    from rich import box as rbox

    ui.console.print(
        Panel(
            Text.from_markup(
                f"[bold white]Your idea:[/bold white] [italic]{_trunc(idea, 80)}[/italic]\n\n"
                f"[dim]({reason} — a few quick questions will help produce a tighter, "
                f"more useful task plan.)\n\n"
                f"Press Enter to skip any question.[/dim]"
            ),
            title="[bold yellow]❓  QUICK CLARIFICATION[/bold yellow]",
            border_style="yellow",
            box=rbox.ROUNDED,
            padding=(1, 2),
        )
    )


def _ask_question(n: int, total: int, question: str, hint: str) -> str:
    if ui.RICH:
        ui.console.print(f"\n  [bold cyan]Q{n}/{total}[/bold cyan] [bold white]{question}[/bold white]")
        ui.console.print(f"  [dim]{hint}[/dim]")
    else:
        print(f"\nQ{n}/{total}: {question}")
        print(f"  ({hint})")
    return input("  → ").strip()


def _ask_proceed() -> bool:
    ui.blank()
    if ui.RICH:
        from rich.prompt import Confirm
        return Confirm.ask("  [bold cyan]Looks good? Proceed with LLM planning?[/bold cyan]", default=True)
    ans = input("  Proceed with LLM planning? [Y/n]: ").strip().lower()
    return ans in ("", "y", "yes")


def _trunc(s: str, n: int) -> str:
    return s if len(s) <= n else s[:n-1] + "…"
