"""
cli.py — Entry point for the `supervisor` command.

Subcommands
-----------
    supervisor "idea"                     — main flow (default): scan, plan, verify
    supervisor verify --tasks plan.json   — verify ANY task plan against this
                                             codebase's dependency graph, no LLM
                                             call required. Works on a plan this
                                             tool produced, or one handed to it by
                                             any other tool.
    supervisor mcp                        — run as an MCP server (stdio transport)
                                             so Claude Code, Vibe Kanban, Claude
                                             Squad, etc. can call decompose/verify
                                             directly.
    supervisor init                       — run / re-run onboarding wizard
    supervisor config                     — show current config
    supervisor history                    — show session history
    supervisor history --clear            — clear all history

Usage examples
--------------
    supervisor "Add FAISS vector search with SSE streaming"
    supervisor "Add FAISS" ./my-project
    supervisor "Add FAISS" --model claude-opus-4-6 --iterate
    supervisor verify --project-dir . --tasks tasks_20260719.json
    supervisor mcp
    supervisor init
    supervisor init --reset
    supervisor config
    supervisor history
    supervisor history --clear
    supervisor --help
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Optional

from . import __version__
from . import display as ui
from .config     import (
    load_config, run_onboarding, show_config,
    resolve_anthropic_key, resolve_groq_key, resolve_model,
    reset_config,
)
from .memory     import save_session, show_last_session_hint, show_history, clear_history
from .preflight   import show_preflight, maybe_clarify
from .researcher  import research_codebase
from .depgraph    import build_from_research
from .planner     import create_task_plan, plan_next_iteration
from .generator   import save_tasks_md, save_plan_json, collect_iteration_results
from .tasks       import TaskPlan, TaskPlanParseError
from .verifier    import verify_task_plan


# ═════════════════════════════════════════════════════════════════════════════
# ARGUMENT PARSER
# ═════════════════════════════════════════════════════════════════════════════
#
# NOTE ON DESIGN: this does NOT use argparse's add_subparsers() combined with
# a free-form positional `idea` argument. That combination is broken — when
# a subparsers action and an optional positional both exist, argparse's
# positional-matching tries to consume the first token as the subcommand
# selector and raises "invalid choice" for any idea string that doesn't
# happen to match a subcommand name. That meant `supervisor "add caching"`
# — the tool's own headline usage example — would crash. Confirmed present
# in v1 as well; it wasn't introduced by this rewrite, but it's fixed here.
#
# Fix: check the first CLI token against a known set of subcommand names
# BEFORE building any parser, and dispatch to a small dedicated parser per
# subcommand. The main-flow parser (with the free-form `idea` positional)
# is only ever built when the first token isn't a subcommand name.

_SUBCOMMAND_NAMES = ("init", "config", "history", "verify", "mcp")


def _build_main_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="supervisor",
        description=(
            "swarm-supervisor — task decomposition + dependency-graph verification\n"
            "Scan your codebase, decompose an idea into an independently-checked\n"
            "task plan, and render it as a Spec-Kit-style tasks.md that works with\n"
            "whatever agent or orchestrator you already use.\n\n"
            "Subcommands:\n"
            "  (default)       Run the main planning flow\n"
            "  verify          Check a task plan for conflicts — no LLM required\n"
            "  mcp             Run as an MCP server\n"
            "  init            First-run setup / re-configure\n"
            "  config          Show current configuration\n"
            "  history         Show session history\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "idea", nargs="?", default=None, metavar="IDEA",
        help="Feature idea (quoted string). Prompted interactively if omitted.",
    )
    parser.add_argument(
        "project_dir_pos", nargs="?", default=None, metavar="PROJECT_DIR",
        help="Project root path (positional). Defaults to current directory.",
    )
    parser.add_argument("--project-dir", "-p", type=str, default=None, dest="project_dir")
    parser.add_argument("--api-key",     "-k", type=str, default=None, dest="api_key")
    parser.add_argument("--groq-key",         type=str, default=None, dest="groq_key")
    parser.add_argument("--model",       "-m", type=str, default=None, dest="model")
    parser.add_argument("--no-save",          action="store_true", dest="no_save")
    parser.add_argument("--output-dir",  "-o", type=str, default=None, dest="output_dir")
    parser.add_argument("--iterate",          action="store_true")
    parser.add_argument("--no-clarify",       action="store_true", dest="no_clarify")
    parser.add_argument("--no-preflight",     action="store_true", dest="no_preflight")
    parser.add_argument("--yes",         "-y", action="store_true", dest="yes",
                         help="Auto-confirm all prompts (CI / non-interactive mode).")
    parser.add_argument("--version",     "-V", action="version",
                         version=f"swarm-supervisor {__version__}")
    return parser


def _build_init_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="supervisor init", description="Run / re-run the setup wizard.")
    p.add_argument("--reset", action="store_true", help="Wipe config and start fresh.")
    return p


def _build_config_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(prog="supervisor config", description="Show current configuration (keys masked).")


def _build_history_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="supervisor history", description="Browse session history.")
    p.add_argument("--clear", action="store_true", help="Delete ALL stored history.")
    p.add_argument("--project-dir", "-p", type=str, default=None)
    p.add_argument("--n", type=int, default=10)
    return p


def _build_verify_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="supervisor verify",
        description="Check a task plan (ours or another tool's) against this codebase's dependency graph.",
    )
    p.add_argument("--project-dir", "-p", type=str, default=None)
    p.add_argument("--tasks", "-t", type=str, required=True,
                    help="Path to a plan.json ({idea, tasks:[...]}) or '-' for stdin.")
    p.add_argument("--write-tasks-md", type=str, default=None,
                    help="If set, also render an annotated tasks.md to this path.")
    return p


def _build_mcp_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(prog="supervisor mcp", description="Run as an MCP server (stdio transport).")


# ═════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═════════════════════════════════════════════════════════════════════════════

def main() -> None:
    argv = sys.argv[1:]

    if argv and argv[0] in _SUBCOMMAND_NAMES:
        cmd, rest = argv[0], argv[1:]

        if cmd == "init":
            _cmd_init(_build_init_parser().parse_args(rest))
        elif cmd == "config":
            _build_config_parser().parse_args(rest)
            ui.print_banner()
            show_config()
        elif cmd == "history":
            ui.print_banner()
            _cmd_history(_build_history_parser().parse_args(rest))
        elif cmd == "verify":
            _cmd_verify(_build_verify_parser().parse_args(rest))
        elif cmd == "mcp":
            _build_mcp_parser().parse_args(rest)
            _cmd_mcp()
        return

    parser = _build_main_parser()
    args   = parser.parse_args(argv)
    _cmd_main(args, parser)


# ═════════════════════════════════════════════════════════════════════════════
# SUBCOMMAND HANDLERS
# ═════════════════════════════════════════════════════════════════════════════

def _cmd_init(args: argparse.Namespace) -> None:
    if getattr(args, "reset", False):
        reset_config()
        ui.warn("Config wiped. Starting fresh…")
    ui.print_banner()
    run_onboarding(force=True)


def _cmd_history(args: argparse.Namespace) -> None:
    if getattr(args, "clear", False):
        n = clear_history()
        ui.success(f"Cleared {n} session file{'s' if n != 1 else ''}.")
        return
    pdir = getattr(args, "project_dir", None) or os.getcwd()
    show_history(project_dir=pdir, n=getattr(args, "n", 10))


def _cmd_verify(args: argparse.Namespace) -> None:
    """
    Standalone conflict check — the piece meant to be genuinely useful on
    its own. Takes a plan from ANY source (this tool, Claude Code's own
    decomposition, a hand-written tasks.json, whatever) and scores it
    against this codebase's real dependency graph. No API key needed.

    Exit code 0 = SAFE, 1 = RISKY, 2 = CONFLICT — scriptable by CI or by
    another orchestrator deciding whether to proceed.
    """
    ui.print_banner()
    project_dir = str(Path(getattr(args, "project_dir", None) or os.getcwd()).expanduser().resolve())

    raw = sys.stdin.read() if args.tasks == "-" else Path(args.tasks).read_text(encoding="utf-8")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        ui.error(f"Could not parse {args.tasks} as JSON: {exc}")
        sys.exit(2)

    try:
        plan = TaskPlan.from_dict(data)
    except Exception as exc:
        ui.error(f"Could not read a TaskPlan from {args.tasks}: {exc}")
        sys.exit(2)

    if not plan.tasks:
        ui.error("No tasks found in the given plan.")
        sys.exit(2)

    ui.step(f"Scanning {project_dir}…", "🔍")
    research = research_codebase(project_dir)
    graph = build_from_research(research)

    report = verify_task_plan(plan, graph)
    ui.display_verification(report)

    if getattr(args, "write_tasks_md", None):
        from .tasks import render_tasks_md
        Path(args.write_tasks_md).write_text(render_tasks_md(plan, report), encoding="utf-8")
        ui.dim(f"Annotated tasks.md → {args.write_tasks_md}")

    sys.exit({"SAFE": 0, "RISKY": 1, "CONFLICT": 2}[report.verdict])


def _cmd_mcp() -> None:
    """Launch the MCP server. Requires `pip install mcp`."""
    try:
        from .mcp_server import run_server
    except ImportError as exc:
        ui.error(f"MCP server requires the `mcp` package: {exc}\n    Run: pip install mcp")
        sys.exit(1)
    run_server()


# ═════════════════════════════════════════════════════════════════════════════
# MAIN PLANNING FLOW
# ═════════════════════════════════════════════════════════════════════════════

def _cmd_main(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    ui.print_banner()
    cfg = _ensure_setup(args)

    project_dir = _resolve_project_dir(args, cfg)
    output_dir  = getattr(args, "output_dir", None) or project_dir

    show_last_session_hint(project_dir)

    idea = _resolve_idea(args)
    ui.display_idea(idea)

    ui.step("Indexing codebase…", "🔍")
    ui.dim(f"Directory: {project_dir}")
    research = research_codebase(project_dir)

    clarify_on = (
        cfg.get("ask_clarification", True)
        and not getattr(args, "no_clarify", False)
        and not getattr(args, "yes", False)
    )
    idea = maybe_clarify(idea, research, enabled=clarify_on)

    preflight_on = (
        cfg.get("show_preflight", True)
        and not getattr(args, "no_preflight", False)
        and not getattr(args, "yes", False)
    )
    if preflight_on:
        if not show_preflight(research, idea):
            ui.warn("Aborted at pre-flight. Run with --no-preflight to skip.")
            sys.exit(0)

    ant_key  = resolve_anthropic_key(getattr(args, "api_key",  None))
    groq_key = resolve_groq_key(     getattr(args, "groq_key", None))
    model    = resolve_model(        getattr(args, "model",    None))
    provider = "anthropic" if ant_key else ("groq" if groq_key else "template")

    ui.step(f"Planning via {provider}  [{model}]…", "🧠")

    plan = create_task_plan(idea=idea, research=research, api_key=ant_key, model=model, groq_key=groq_key)

    ui.display_plan_summary(plan)

    graph  = build_from_research(research)
    report = verify_task_plan(plan, graph)
    ui.display_verification(report)

    if report.verdict == "CONFLICT" and provider != "template" and not getattr(args, "yes", False):
        if _ask_replan():
            plan = _replan_after_conflict(idea, research, report, ant_key, groq_key, model)
            report = verify_task_plan(plan, graph)
            ui.display_verification(report)

    ui.display_task_cards(plan)
    ui.display_summary_table(plan)
    ui.success(f"{len(plan.tasks)} task(s) ready — verdict: {report.verdict}.")

    do_save = not getattr(args, "no_save", False) and cfg.get("auto_save_plans", True)
    tasks_md_path: Optional[str] = None
    json_path:     Optional[str] = None
    if do_save:
        tasks_md_path = save_tasks_md(plan, report, output_dir)
        json_path     = save_plan_json(plan, report, output_dir)
        ui.dim(f"tasks.md → {tasks_md_path}")
        ui.dim(f"plan.json → {json_path}")

    _persist_session(project_dir, idea, plan, report, model, provider, research, 1)

    if getattr(args, "iterate", False):
        _run_iteration_loop(
            idea=idea, plan=plan, report=report, research=research, graph=graph,
            ant_key=ant_key, groq_key=groq_key, model=model, provider=provider,
            project_dir=project_dir, output_dir=output_dir,
            do_save=do_save, yes=getattr(args, "yes", False),
        )

    ui.display_instructions(tasks_md_path, json_path)


def _replan_after_conflict(idea, research, report, ant_key, groq_key, model) -> TaskPlan:
    conflict_note = "\n\nThe previous plan had direct file conflicts that MUST be avoided this time:\n" + "\n".join(
        f"  - {c['file']} was claimed by {', '.join(c['tasks'])}" for c in report.direct_conflicts
    )
    ui.step("Replanning to resolve conflicts…", "🔁")
    try:
        return create_task_plan(idea=idea + conflict_note, research=research,
                                 api_key=ant_key, model=model, groq_key=groq_key)
    except TaskPlanParseError as exc:
        ui.error(f"Replan failed to parse: {exc} — keeping the original plan.")
        return create_task_plan(idea=idea, research=research, api_key=ant_key, model=model, groq_key=groq_key)


# ═════════════════════════════════════════════════════════════════════════════
# HELPERS
# ═════════════════════════════════════════════════════════════════════════════

def _ensure_setup(args: argparse.Namespace) -> dict:
    cfg = load_config()
    if cfg.get("setup_complete"):
        return cfg

    if getattr(args, "yes", False):
        ui.warn("First run — skipping wizard (--yes flag). Run `supervisor init` to configure.")
        return cfg

    ui.blank()
    ui.warn("First run detected! Let's configure your API credentials. (~60 seconds)")
    ui.blank()
    return run_onboarding()


def _resolve_project_dir(args: argparse.Namespace, cfg: dict) -> str:
    raw = (
        getattr(args, "project_dir", None)
        or getattr(args, "project_dir_pos", None)
        or cfg.get("default_project_dir")
        or os.getcwd()
    )
    path = Path(raw).expanduser().resolve()

    if not path.exists() or not path.is_dir():
        ui.error(f"Not a valid directory: {path}")
        path = _ask_for_valid_dir()

    explicitly_set = getattr(args, "project_dir", None) or getattr(args, "project_dir_pos", None)
    if not explicitly_set and not getattr(args, "yes", False):
        path = _confirm_or_change_dir(path)

    return str(path)


def _confirm_or_change_dir(path: Path) -> Path:
    if ui.RICH:
        from rich.prompt import Confirm, Prompt
        ui.console.print(f"\n  [bold white]Detected project directory:[/bold white]  [cyan]{path}[/cyan]")
        ok = Confirm.ask("  [bold yellow]Scan this directory?[/bold yellow]", default=True)
        new = "" if ok else Prompt.ask("  [bold yellow]Enter the correct path[/bold yellow]").strip()
    else:
        print(f"\n  Project directory: {path}")
        ok_raw = input("  Scan this directory? [Y/n]: ").strip().lower()
        ok = ok_raw in ("", "y", "yes")
        new = "" if ok else input("  Enter the correct path: ").strip()

    if ok or not new:
        return path
    p = Path(new).expanduser().resolve()
    if p.is_dir():
        return p
    ui.warn(f"Path not found: {p} — using original: {path}")
    return path


def _ask_for_valid_dir() -> Path:
    ui.blank()
    if ui.RICH:
        from rich.prompt import Prompt
        raw = Prompt.ask("[bold yellow]  Enter a valid project path[/bold yellow]").strip()
    else:
        raw = input("  Enter a valid project path: ").strip()
    p = Path(raw).expanduser().resolve()
    if not p.is_dir():
        ui.error(f"Still not a valid directory: {p}")
        sys.exit(1)
    return p


def _resolve_idea(args: argparse.Namespace) -> str:
    idea = getattr(args, "idea", None)
    if idea and idea.strip():
        return idea.strip()
    ui.blank()
    if ui.RICH:
        from rich.prompt import Prompt
        idea = Prompt.ask("  [bold yellow]🎯  What do you want to build or change?[/bold yellow]")
    else:
        idea = input("  🎯  What do you want to build or change? → ")
    if not idea or not idea.strip():
        ui.error("No idea provided. Exiting.")
        sys.exit(1)
    return idea.strip()


def _ask_replan() -> bool:
    ui.blank()
    if ui.RICH:
        from rich.prompt import Confirm
        return Confirm.ask(
            "  [bold red]Direct file conflicts detected. Ask the LLM to replan?[/bold red]",
            default=True,
        )
    ans = input("  Direct file conflicts detected. Ask the LLM to replan? [Y/n]: ").strip().lower()
    return ans in ("", "y", "yes")


def _ask_continue(iteration: int) -> bool:
    if ui.RICH:
        from rich.prompt import Confirm
        return Confirm.ask(f"\n  [bold yellow]Run iteration {iteration}?[/bold yellow]", default=False)
    return input(f"\n  Run iteration {iteration}? (y/N) → ").strip().lower() == "y"


def _persist_session(project_dir, idea, plan: TaskPlan, report, model, provider, research, iteration) -> None:
    try:
        save_session(
            project_dir=project_dir, idea=idea,
            task_plan=plan.to_dict(), verification=report.to_dict() if report else None,
            model=model, provider=provider, iteration=iteration,
            files_scanned=len(research.get("file_tree", [])),
            total_chars=research.get("total_chars", 0),
        )
    except Exception as e:
        ui.dim(f"Session save skipped: {e}")


def _run_iteration_loop(
    idea, plan: TaskPlan, report, research, graph,
    ant_key, groq_key, model, provider,
    project_dir, output_dir, do_save, yes,
) -> None:
    current_plan   = plan
    current_report = report
    iteration      = 1

    while True:
        iteration += 1
        ui.blank()
        if not yes and not _ask_continue(iteration):
            break

        results_text = collect_iteration_results()
        if not results_text.strip():
            ui.warn("No results pasted — skipping iteration.")
            continue

        current_plan = plan_next_iteration(
            idea=idea, previous_plan=current_plan, results_text=results_text,
            research=research, verification=current_report.to_dict() if current_report else None,
            api_key=ant_key, model=model, groq_key=groq_key,
        )

        current_report = verify_task_plan(current_plan, graph)

        ui.display_plan_summary(current_plan)
        ui.display_verification(current_report)
        ui.display_task_cards(current_plan)
        ui.display_summary_table(current_plan)
        ui.success(f"Iteration {iteration}: {len(current_plan.tasks)} task(s) — verdict: {current_report.verdict}.")

        if do_save:
            md_path   = save_tasks_md(current_plan, current_report, output_dir, filename=f"tasks_iter{iteration}.md")
            json_path = save_plan_json(current_plan, current_report, output_dir, filename=f"plan_iter{iteration}.json")
            ui.dim(f"Iteration {iteration}: {md_path}, {json_path}")

        _persist_session(project_dir, idea, current_plan, current_report, model, provider, research, iteration)
