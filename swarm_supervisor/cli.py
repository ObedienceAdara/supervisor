"""
cli.py — Entry point for the `supervisor` command.

Subcommands
-----------
    supervisor "idea"              — main flow (default)
    supervisor init                — run / re-run onboarding wizard
    supervisor config              — show current config
    supervisor history             — show session history
    supervisor history --clear     — clear all history

Usage examples
--------------
    supervisor "Add FAISS vector search with SSE streaming"
    supervisor "Add FAISS" ./my-project
    supervisor "Add FAISS" --model claude-opus-4-6 --iterate
    supervisor init
    supervisor init --reset
    supervisor config
    supervisor history
    supervisor history --clear
    supervisor --help
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Optional

from . import __version__
from . import display as ui
from .config    import (
    load_config, run_onboarding, show_config,
    resolve_anthropic_key, resolve_groq_key, resolve_model,
    reset_config,
)
from .memory    import (
    save_session, show_last_session_hint, show_history, clear_history,
)
from .preflight  import show_preflight, maybe_clarify
from .researcher import research_codebase
from .planner    import create_execution_plan, plan_next_iteration
from .generator  import extract_agent_prompts, save_plan, collect_agent_results


# ═════════════════════════════════════════════════════════════════════════════
# ARGUMENT PARSER
# ═════════════════════════════════════════════════════════════════════════════

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="supervisor",
        description=(
            "swarm-supervisor — Karpathy AutoResearcher\n"
            "Scan your codebase, think, clarify, then generate\n"
            "7 parallel Qwen Code agent prompts.\n\n"
            "Subcommands:\n"
            "  (default)       Run the main planning flow\n"
            "  init            First-run setup / re-configure\n"
            "  config          Show current configuration\n"
            "  history         Show session history\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subparsers = parser.add_subparsers(dest="subcommand")

    # ── init ─────────────────────────────────────────────────────────────────
    init_p = subparsers.add_parser("init", help="Run / re-run the setup wizard.")
    init_p.add_argument("--reset", action="store_true", help="Wipe config and start fresh.")

    # ── config ───────────────────────────────────────────────────────────────
    subparsers.add_parser("config", help="Show current configuration (keys masked).")

    # ── history ──────────────────────────────────────────────────────────────
    hist_p = subparsers.add_parser("history", help="Browse session history.")
    hist_p.add_argument("--clear", action="store_true", help="Delete ALL stored history.")
    hist_p.add_argument("--project-dir", "-p", type=str, default=None)
    hist_p.add_argument("--n", type=int, default=10)

    # ── main flow ─────────────────────────────────────────────────────────────
    parser.add_argument(
        "idea", nargs="?", default=None, metavar="IDEA",
        help='Feature idea (quoted string). Prompted interactively if omitted.',
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


# ═════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═════════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = _build_parser()
    args   = parser.parse_args()

    if args.subcommand == "init":
        _cmd_init(args)
        return

    if args.subcommand == "config":
        ui.print_banner()
        show_config()
        return

    if args.subcommand == "history":
        ui.print_banner()
        _cmd_history(args)
        return

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


# ═════════════════════════════════════════════════════════════════════════════
# MAIN PLANNING FLOW
# ═════════════════════════════════════════════════════════════════════════════

def _cmd_main(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:

    # 1. Banner
    ui.print_banner()

    # 2. First-run check — trigger wizard if needed
    cfg = _ensure_setup(args)

    # 3. Resolve project directory (with confirmation)
    project_dir = _resolve_project_dir(args, cfg)

    # 4. Resolve output directory
    output_dir = getattr(args, "output_dir", None) or project_dir

    # 5. Show memory hint (last session for this project)
    show_last_session_hint(project_dir)

    # 6. Get idea
    idea = _resolve_idea(args)
    ui.display_idea(idea)

    # 7. Scan codebase
    ui.step("Indexing codebase…", "🔍")
    ui.dim(f"Directory: {project_dir}")
    research = research_codebase(project_dir)

    # 8. Clarification — enrich vague ideas with follow-up questions
    clarify_on = (
        cfg.get("ask_clarification", True)
        and not getattr(args, "no_clarify", False)
        and not getattr(args, "yes", False)
    )
    idea = maybe_clarify(idea, research, enabled=clarify_on)

    # 9. Pre-flight briefing — show what was found, ask to proceed
    preflight_on = (
        cfg.get("show_preflight", True)
        and not getattr(args, "no_preflight", False)
        and not getattr(args, "yes", False)
    )
    if preflight_on:
        confirmed = show_preflight(research, idea)
        if not confirmed:
            ui.warn("Aborted at pre-flight. Run with --no-preflight to skip.")
            sys.exit(0)

    # 10. Resolve credentials + model
    ant_key  = resolve_anthropic_key(getattr(args, "api_key",  None))
    groq_key = resolve_groq_key(     getattr(args, "groq_key", None))
    model    = resolve_model(        getattr(args, "model",    None))
    provider = "anthropic" if ant_key else ("groq" if groq_key else "template")

    ui.step(f"Planning via {provider}  [{model}]…", "🧠")

    # 11. Generate plan
    plan_text = create_execution_plan(
        idea=idea, research=research,
        api_key=ant_key, model=model, groq_key=groq_key,
    )

    # 12. Display plan + agent cards
    ui.display_plan_overview(plan_text)
    prompts = extract_agent_prompts(plan_text)

    if not prompts:
        ui.warn("Prompt extraction failed — displaying raw output.")
        _display_raw(plan_text)
    else:
        ui.display_agent_cards(prompts)
        ui.display_summary_table(prompts)
        ui.success(f"{len(prompts)} agent prompts ready.")

    # 13. Save plan
    do_save    = not getattr(args, "no_save", False) and cfg.get("auto_save_plans", True)
    saved_path: Optional[str] = None
    if do_save:
        saved_path = save_plan(plan_text, output_dir)
        ui.dim(f"Plan saved → {saved_path}")

    # 14. Save to memory
    _persist_session(project_dir, idea, plan_text, prompts, model, provider, research, 1)

    # 15. Iteration loop
    if getattr(args, "iterate", False):
        _run_iteration_loop(
            idea=idea, plan_text=plan_text, research=research,
            ant_key=ant_key, groq_key=groq_key, model=model, provider=provider,
            project_dir=project_dir, output_dir=output_dir,
            do_save=do_save, yes=getattr(args, "yes", False),
        )

    # 16. Final instructions
    ui.display_instructions(saved_path)


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
    """
    Priority: --project-dir flag > positional arg > configured default > cwd.
    Always shows the resolved path and (unless --yes) asks the user to confirm.
    """
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
    """Show the detected path and let the user confirm or enter a different one."""
    try:
        from rich.prompt import Confirm, Prompt
        from .display import console
        console.print(
            f"\n  [bold white]Detected project directory:[/bold white]  [cyan]{path}[/cyan]"
        )
        ok = Confirm.ask("  [bold yellow]Scan this directory?[/bold yellow]", default=True)
        if ok:
            return path
        new = Prompt.ask("  [bold yellow]Enter the correct path[/bold yellow]").strip()
    except Exception:
        print(f"\n  Project directory: {path}")
        ok = input("  Scan this directory? [Y/n]: ").strip().lower()
        if ok in ("", "y", "yes"):
            return path
        new = input("  Enter the correct path: ").strip()

    if not new:
        return path
    p = Path(new).expanduser().resolve()
    if p.is_dir():
        return p
    ui.warn(f"Path not found: {p} — using original: {path}")
    return path


def _ask_for_valid_dir() -> Path:
    ui.blank()
    try:
        from rich.prompt import Prompt
        raw = Prompt.ask("[bold yellow]  Enter a valid project path[/bold yellow]").strip()
    except Exception:
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
    try:
        from rich.prompt import Prompt
        idea = Prompt.ask("  [bold yellow]🎯  What do you want to build or change?[/bold yellow]")
    except Exception:
        idea = input("  🎯  What do you want to build or change? → ")
    if not idea or not idea.strip():
        ui.error("No idea provided. Exiting.")
        sys.exit(1)
    return idea.strip()


def _persist_session(
    project_dir, idea, plan, prompts, model, provider, research, iteration
) -> None:
    try:
        save_session(
            project_dir=project_dir, idea=idea, plan=plan, prompts=prompts,
            model=model, provider=provider, iteration=iteration,
            files_scanned=len(research.get("file_tree", [])),
            total_chars=research.get("total_chars", 0),
        )
    except Exception as e:
        ui.dim(f"Session save skipped: {e}")


def _display_raw(plan_text: str) -> None:
    try:
        from rich.markdown import Markdown
        from .display import console
        if console:
            console.print(Markdown(plan_text))
            return
    except Exception:
        pass
    print(plan_text)


def _run_iteration_loop(
    idea, plan_text, research,
    ant_key, groq_key, model, provider,
    project_dir, output_dir, do_save, yes,
) -> None:
    current_plan = plan_text
    iteration    = 1

    while True:
        iteration += 1
        ui.blank()
        if not yes and not _ask_continue(iteration):
            break

        agent_results = collect_agent_results()
        if not agent_results.strip():
            ui.warn("No results pasted — skipping iteration.")
            continue

        current_plan = plan_next_iteration(
            idea=idea, original_plan=current_plan,
            agent_results=agent_results, research=research,
            api_key=ant_key, model=model, groq_key=groq_key,
        )

        ui.display_plan_overview(current_plan)
        prompts = extract_agent_prompts(current_plan)
        if prompts:
            ui.display_agent_cards(prompts)
            ui.display_summary_table(prompts)
            ui.success(f"Iteration {iteration}: {len(prompts)} prompts ready.")

        if do_save:
            saved = save_plan(current_plan, output_dir)
            ui.dim(f"Iteration {iteration} plan → {saved}")

        _persist_session(project_dir, idea, current_plan, prompts,
                         model, provider, research, iteration)


def _ask_continue(iteration: int) -> bool:
    try:
        from rich.prompt import Confirm
        return Confirm.ask(
            f"\n  [bold yellow]Run iteration {iteration}?[/bold yellow]", default=False
        )
    except Exception:
        return input(f"\n  Run iteration {iteration}? (y/N) → ").strip().lower() == "y"
