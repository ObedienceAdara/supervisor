"""
display.py — Rich CLI components for swarm-supervisor.

All terminal output flows through this module so the rest of the codebase
stays clean of print() noise. Every function has a plain-text fallback so
the tool still works with Rich uninstalled (and so tests can import the
package without it).
"""

from __future__ import annotations

from typing import Optional

from . import __version__

# ── Rich availability ─────────────────────────────────────────────────────────
try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.rule import Rule
    from rich.text import Text
    from rich.align import Align
    from rich.progress import (
        Progress, SpinnerColumn, TextColumn, TimeElapsedColumn,
    )
    from rich.markdown import Markdown
    from rich import box as rbox
    RICH = True
except ImportError:
    RICH = False

# ── Singleton console ─────────────────────────────────────────────────────────
console = Console(highlight=False, stderr=False) if RICH else None

# ── Palette cycled across however many tasks exist (not fixed at 7) ──────────
_TASK_COLORS = [
    ("bold cyan", "cyan"), ("bold green", "green"), ("bold yellow", "yellow"),
    ("bold magenta", "magenta"), ("bold blue", "blue"), ("bold red", "red"),
    ("bold white", "white"),
]

_VERDICT_STYLE = {
    "SAFE":     ("green",  "✓"),
    "RISKY":    ("yellow", "⚠"),
    "CONFLICT": ("red",    "✗"),
}


# ═════════════════════════════════════════════════════════════════════════════
# BANNER
# ═════════════════════════════════════════════════════════════════════════════

_ASCII_LOGO = r"""
 ░██████╗██╗   ██╗██████╗ ███████╗██████╗ ██╗   ██╗██╗███████╗ ██████╗ ██████╗ 
 ██╔════╝██║   ██║██╔══██╗██╔════╝██╔══██╗██║   ██║██║██╔════╝██╔═══██╗██╔══██╗
 ╚█████╗ ██║   ██║██████╔╝█████╗  ██████╔╝╚██╗ ██╔╝██║███████╗██║   ██║██████╔╝
  ╚═══██╗██║   ██║██╔═══╝ ██╔══╝  ██╔══██╗  ╚████╔╝ ██║╚════██║██║   ██║██╔══██╗
 ██████╔╝╚██████╔╝██║     ███████╗██║  ██║   ╚══╝  ██║███████║╚██████╔╝██║  ██║
 ╚═════╝  ╚═════╝ ╚═╝     ╚══════╝╚═╝  ╚═╝         ╚═╝╚══════╝ ╚═════╝ ╚═╝  ╚═╝
"""


def print_banner() -> None:
    """Print the opening banner."""
    if not RICH:
        _plain(f"""
╔══════════════════════════════════════════════════════════╗
║   SUPERVISOR  ·  Task Decomposition + Verification  v{__version__:<8}║
║   Agent-agnostic. Codebase-aware. Conflict-checked.       ║
╚══════════════════════════════════════════════════════════╝
""")
        return

    logo = Text(_ASCII_LOGO, style="bold cyan", justify="center")
    sub = Text(
        f"  Task decomposition + dependency-graph verification  ·  v{__version__}  ",
        style="bold white",
        justify="center",
    )
    console.print()
    console.print(Align.center(logo))
    console.print(
        Panel(Align.center(sub), border_style="cyan", box=rbox.HEAVY, padding=(0, 0))
    )
    console.print()


# ═════════════════════════════════════════════════════════════════════════════
# STEP HELPERS
# ═════════════════════════════════════════════════════════════════════════════

def step(msg: str, icon: str = "→") -> None:
    if RICH:
        console.print(f"  {icon} [bold white]{msg}[/bold white]")
    else:
        _plain(f"  {icon} {msg}")


def success(msg: str) -> None:
    if RICH:
        console.print(f"  [bold green]✓[/bold green] [green]{msg}[/green]")
    else:
        _plain(f"  ✓ {msg}")


def warn(msg: str) -> None:
    if RICH:
        console.print(f"  [bold yellow]⚠[/bold yellow] [yellow]{msg}[/yellow]")
    else:
        _plain(f"  ⚠ {msg}")


def error(msg: str) -> None:
    if RICH:
        console.print(f"  [bold red]✗[/bold red] [red]{msg}[/red]")
    else:
        _plain(f"  ✗ {msg}")


def dim(msg: str) -> None:
    if RICH:
        console.print(f"    [dim]{msg}[/dim]")
    else:
        _plain(f"    {msg}")


def rule(title: str = "", style: str = "cyan") -> None:
    if RICH:
        console.print(Rule(f"[bold {style}]{title}[/bold {style}]", style=style))
    else:
        _plain(f"\n{'─'*28} {title} {'─'*28}\n")


def blank() -> None:
    if RICH:
        console.print()
    else:
        print()


# ═════════════════════════════════════════════════════════════════════════════
# SPINNERS
# ═════════════════════════════════════════════════════════════════════════════

def make_spinner(label: str = "Working…"):
    if RICH:
        return Progress(
            SpinnerColumn(spinner_name="dots12", style="bold cyan"),
            TextColumn("[bold white]{task.description}"),
            TimeElapsedColumn(),
            console=console,
            transient=True,
        )
    return _NullProgress(label)


class _NullProgress:
    """Plain-text fallback when Rich is not installed."""
    def __init__(self, label: str):
        self._label = label

    def __enter__(self):
        print(f"  … {self._label}", end="", flush=True)
        return self

    def __exit__(self, *_):
        print(" done")

    def add_task(self, desc: str, **_):
        return 0

    def update(self, *_, **__):
        pass


# ═════════════════════════════════════════════════════════════════════════════
# CONTENT PANELS
# ═════════════════════════════════════════════════════════════════════════════

def display_idea(idea: str) -> None:
    if RICH:
        console.print()
        console.print(
            Panel(
                Align.center(Text(f'"{idea}"', style="bold white italic")),
                title="[bold cyan]🎯  YOUR IDEA[/bold cyan]",
                border_style="cyan", box=rbox.DOUBLE, padding=(1, 4),
            )
        )
        console.print()
    else:
        _plain(f'\n🎯 IDEA: "{idea}"\n')


def display_scan_stats(file_tree: list, file_contents: dict, function_map: dict,
                        total_chars: int, project_dir: str) -> None:
    if not RICH:
        _plain(f"  ✓ {len(file_tree)} files found · {len(file_contents)} read · "
               f"{total_chars:,} chars · {len(function_map)} Python modules mapped")
        return

    table = Table(box=rbox.SIMPLE, show_header=False, padding=(0, 2))
    table.add_column("key", style="dim white")
    table.add_column("val", style="bold white")
    table.add_row("Project", str(project_dir))
    table.add_row("Files found", str(len(file_tree)))
    table.add_row("Files read", str(len(file_contents)))
    table.add_row("Chars indexed", f"{total_chars:,}")
    table.add_row("Python modules", str(len(function_map)))

    console.print(
        Panel(table, title="[bold green]📁  CODEBASE INDEXED[/bold green]",
              border_style="green", padding=(0, 1))
    )
    console.print()


def display_verification(report) -> None:
    """Render a ConflictReport (verifier.ConflictReport)."""
    style, icon = _VERDICT_STYLE.get(report.verdict, ("white", "•"))

    if not RICH:
        _plain(f"\n=== DEPENDENCY-GRAPH VERIFICATION ===")
        _plain(f"  {icon} {report.verdict}  (score {report.score}/100)")
        if report.direct_conflicts:
            _plain(f"  ✗ {len(report.direct_conflicts)} direct file conflict(s):")
            for c in report.direct_conflicts:
                _plain(f"      {c['file']} — claimed by {', '.join(c['tasks'])}")
        if report.coupling_risks:
            _plain(f"  ⚠ {len(report.coupling_risks)} cross-task coupling edge(s)")
        if report.hotspot_hits:
            _plain(f"  ⚠ {len(report.hotspot_hits)} shared-surface file(s) touched by multiple tasks")
        _plain("")
        return

    lines = [f"[bold {style}]{icon} {report.verdict}[/bold {style}]  ·  score {report.score}/100"]
    if report.direct_conflicts:
        lines.append(f"[bold red]{len(report.direct_conflicts)} direct file conflict(s):[/bold red]")
        for c in report.direct_conflicts:
            lines.append(f"  [red]·[/red] `{c['file']}` claimed by {', '.join(c['tasks'])}")
    if report.coupling_risks:
        lines.append(f"[yellow]{len(report.coupling_risks)} cross-task coupling edge(s)[/yellow] "
                      f"(imports/calls spanning two tasks' files)")
    if report.hotspot_hits:
        lines.append(f"[yellow]{len(report.hotspot_hits)} shared-surface file(s) touched by "
                      f"multiple tasks:[/yellow]")
        for h in report.hotspot_hits:
            lines.append(f"  [yellow]·[/yellow] `{h['file']}` — tasks {', '.join(h['tasks'])}")
    for n in report.notes:
        lines.append(f"[dim]· {n}[/dim]")

    console.print()
    console.print(
        Panel("\n".join(lines), title="[bold cyan]🔗  DEPENDENCY-GRAPH VERIFICATION[/bold cyan]",
              border_style=style, box=rbox.ROUNDED, padding=(1, 2))
    )
    console.print()


def display_task_cards(plan) -> None:
    """Render each task in its own color-coded panel (any task count)."""
    if not plan.tasks:
        warn("No tasks found in the generated plan.")
        return

    if RICH:
        console.print()
        rule(f"{len(plan.tasks)} TASK{'S' if len(plan.tasks) != 1 else ''} — COPY INTO YOUR AGENT/ORCHESTRATOR OF CHOICE", style="cyan")
        console.print()
    else:
        _plain("\n" + "="*70)
        _plain(f"{len(plan.tasks)} TASKS")
        _plain("="*70)

    for i, t in enumerate(plan.tasks, 1):
        fg, border = _TASK_COLORS[(i - 1) % len(_TASK_COLORS)]
        body = t.description or "(no description)"
        if t.target_files:
            body += f"\n\nFiles: {', '.join(t.target_files)}"
        if t.avoid_files:
            body += f"\nDo not touch: {', '.join(t.avoid_files)}"
        if t.depends_on:
            body += f"\nDepends on: {', '.join(t.depends_on)}"
        if t.acceptance_criteria:
            body += "\nAcceptance criteria:\n" + "\n".join(f"  - {a}" for a in t.acceptance_criteria)

        if RICH:
            console.print(
                Panel(Text(body, style="white"),
                      title=f"[{fg}] {t.id}  {t.title} [/{fg}]",
                      border_style=border, box=rbox.ROUNDED, padding=(1, 2))
            )
            console.print()
        else:
            _plain(f"\n{'─'*70}")
            _plain(f" {t.id}  {t.title}")
            _plain("─"*70)
            _plain(body)


def display_summary_table(plan) -> None:
    if not RICH:
        return
    table = Table(title="[bold cyan]Task Roster[/bold cyan]", box=rbox.ROUNDED,
                  border_style="cyan", show_lines=True, padding=(0, 1))
    table.add_column("ID", style="bold cyan", width=6, justify="center")
    table.add_column("Title", style="bold white", min_width=20)
    table.add_column("Files", style="dim white", min_width=16)
    table.add_column("Depends on", style="dim white", width=14, justify="center")

    for t in plan.tasks:
        files = ", ".join(t.target_files[:3]) + (" …" if len(t.target_files) > 3 else "")
        table.add_row(t.id, t.title, files or "—", ", ".join(t.depends_on) or "—")

    console.print()
    console.print(Align.center(table))
    console.print()


def display_instructions(tasks_md_path: Optional[str] = None, json_path: Optional[str] = None) -> None:
    items = [
        "Feed [bold white]tasks.md[/bold white] into your agent orchestrator of choice "
        "(Claude Code, Vibe Kanban, Claude Squad, Conductor, ccswarm, or run each task by hand)",
        "Tasks in the same wave are marked [bold cyan][P][/bold cyan] — safe to run in parallel",
        "Run [bold yellow]supervisor verify[/bold yellow] again on any edited plan before executing it",
        "Collect results → run [bold yellow]supervisor --iterate[/bold yellow] for the next round",
    ]
    if tasks_md_path:
        items.append(f"tasks.md saved → [dim]{tasks_md_path}[/dim]")
    if json_path:
        items.append(f"plan.json saved → [dim]{json_path}[/dim]")

    if RICH:
        content = "\n".join(f"  [dim]›[/dim] {item}" for item in items)
        console.print(
            Panel(content, title="[bold yellow]📋  NEXT STEPS[/bold yellow]",
                  border_style="yellow", box=rbox.ROUNDED, padding=(1, 2))
        )
        console.print()
    else:
        _plain("\n📋 NEXT STEPS:")
        for item in items:
            _plain(f"  › {item}")
        _plain("")


def display_iteration_instructions() -> None:
    if RICH:
        console.print(
            Panel(
                "  [bold white]Paste the results from this round's tasks below[/bold white]\n"
                "  (diffs, summaries — whatever your agents/orchestrator produced).\n"
                "  When done, type [bold yellow]END[/bold yellow] on a new line and press Enter.",
                title="[bold yellow]⟳  TASK RESULTS INPUT[/bold yellow]",
                border_style="yellow", padding=(1, 2),
            )
        )
    else:
        _plain("\n>>> Paste this round's task results. Type END on a new line when done:\n")


def display_plan_summary(plan) -> None:
    """Short markdown-ish summary (idea + integration notes) shown before the task cards."""
    if RICH:
        console.print()
        rule("PLAN OVERVIEW", style="cyan")
        console.print(Markdown(f"**Idea:** {plan.idea}\n\n{plan.integration_notes or ''}"))
        console.print()
    else:
        _plain("\n=== PLAN OVERVIEW ===")
        _plain(f"Idea: {plan.idea}")
        if plan.integration_notes:
            _plain(plan.integration_notes)
        _plain("")


# ═════════════════════════════════════════════════════════════════════════════
# INTERNAL HELPERS
# ═════════════════════════════════════════════════════════════════════════════

def _plain(msg: str) -> None:
    print(msg)
