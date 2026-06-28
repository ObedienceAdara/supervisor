"""
display.py — Enhanced Rich CLI components for swarm-supervisor.

All terminal output flows through this module so the rest of the
codebase stays clean of print() noise.
"""

from __future__ import annotations

import sys
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
        Progress, SpinnerColumn, TextColumn,
        BarColumn, TimeElapsedColumn,
    )
    from rich.markdown import Markdown
    from rich.columns import Columns
    from rich.padding import Padding
    from rich import box as rbox
    RICH = True
except ImportError:
    RICH = False

# ── Singleton console ─────────────────────────────────────────────────────────
console = Console(highlight=False, stderr=False) if RICH else None

# ── Per-agent color palette (7 distinct colors) ───────────────────────────────
_AGENT_COLORS = [
    ("bold cyan",    "cyan"),
    ("bold green",   "green"),
    ("bold yellow",  "yellow"),
    ("bold magenta", "magenta"),
    ("bold blue",    "blue"),
    ("bold red",     "red"),
    ("bold white",   "white"),
]

_AGENT_ICONS = ["①", "②", "③", "④", "⑤", "⑥", "⑦"]


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
        _plain("""
╔══════════════════════════════════════════════════════════╗
║   SUPERVISOR  ·  Karpathy AutoResearcher  v{v}        ║
║   7-Agent Qwen Code Swarm Controller                     ║
╚══════════════════════════════════════════════════════════╝
""".format(v=__version__))
        return

    logo = Text(_ASCII_LOGO, style="bold cyan", justify="center")
    sub = Text(
        f"  Karpathy AutoResearcher  ·  7-Agent Qwen Code Swarm  ·  v{__version__}  ",
        style="bold white",
        justify="center",
    )
    console.print()
    console.print(Align.center(logo))
    console.print(
        Panel(
            Align.center(sub),
            border_style="cyan",
            box=rbox.HEAVY,
            padding=(0, 0),
        )
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
    """
    Returns a Rich Progress spinner as a context manager.
    Usage:
        with make_spinner("Scanning...") as p:
            t = p.add_task("")
            ... do work ...
    Falls back to a no-op context manager when Rich is unavailable.
    """
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
    """Render the user's idea in a prominent panel."""
    if RICH:
        console.print()
        console.print(
            Panel(
                Align.center(Text(f'"{idea}"', style="bold white italic")),
                title="[bold cyan]🎯  YOUR IDEA[/bold cyan]",
                border_style="cyan",
                box=rbox.DOUBLE,
                padding=(1, 4),
            )
        )
        console.print()
    else:
        _plain(f'\n🎯 IDEA: "{idea}"\n')


def display_scan_stats(
    file_tree: list,
    file_contents: dict,
    function_map: dict,
    total_chars: int,
    project_dir: str,
) -> None:
    """Show a compact scan-results card."""
    if not RICH:
        _plain(f"  ✓ {len(file_tree)} files found · {len(file_contents)} read · {total_chars:,} chars · {len(function_map)} Python modules mapped")
        return

    table = Table(box=rbox.SIMPLE, show_header=False, padding=(0, 2))
    table.add_column("key", style="dim white")
    table.add_column("val", style="bold white")

    table.add_row("Project",         str(project_dir))
    table.add_row("Files found",     str(len(file_tree)))
    table.add_row("Files read",      str(len(file_contents)))
    table.add_row("Chars indexed",   f"{total_chars:,}")
    table.add_row("Python modules",  str(len(function_map)))

    console.print(
        Panel(table, title="[bold green]📁  CODEBASE INDEXED[/bold green]",
              border_style="green", padding=(0, 1))
    )
    console.print()


def display_plan_overview(plan_text: str) -> None:
    """Render the AUTO-RESEARCHER PLAN section."""
    # Extract only the plan block
    plan_block = _extract_section(plan_text, "=== AUTO-RESEARCHER PLAN ===", "===")
    if not plan_block:
        plan_block = plan_text[:800]

    if RICH:
        console.print()
        rule("EXECUTION PLAN", style="cyan")
        console.print(Markdown(plan_block))
        console.print()
    else:
        _plain("\n=== EXECUTION PLAN ===")
        _plain(plan_block)
        _plain("")


def display_agent_cards(prompts: list[str]) -> None:
    """Render each agent in its own color-coded panel."""
    if not prompts:
        warn("No agent prompts found in the generated plan.")
        return

    if RICH:
        console.print()
        rule("7 AGENT PROMPTS  ·  COPY-PASTE INTO QWEN CODE", style="cyan")
        console.print()
    else:
        _plain("\n" + "="*70)
        _plain("7 AGENT PROMPTS — COPY INTO QWEN CODE")
        _plain("="*70)

    for i, prompt in enumerate(prompts, 1):
        fg, border = _AGENT_COLORS[(i - 1) % 7]
        icon = _AGENT_ICONS[(i - 1) % 7]

        lines      = prompt.strip().splitlines()
        header     = lines[0].strip() if lines else f"AGENT {i}"
        body       = "\n".join(lines[1:]).strip() if len(lines) > 1 else prompt

        if RICH:
            console.print(
                Panel(
                    Text(body, style="white"),
                    title=f"[{fg}] {icon}  {header} [/{fg}]",
                    border_style=border,
                    box=rbox.ROUNDED,
                    padding=(1, 2),
                )
            )
            console.print()
        else:
            _plain(f"\n{'─'*70}")
            _plain(f" {icon}  {header}")
            _plain("─"*70)
            _plain(body)


def display_summary_table(prompts: list[str]) -> None:
    """Compact table listing all 7 agents and their roles."""
    if not RICH:
        return

    table = Table(
        title="[bold cyan]Agent Roster[/bold cyan]",
        box=rbox.ROUNDED,
        border_style="cyan",
        show_lines=True,
        padding=(0, 1),
    )
    table.add_column("#",    style="bold cyan",  width=4,  justify="center")
    table.add_column("Icon", style="bold white", width=4,  justify="center")
    table.add_column("Role", style="bold white", min_width=24)
    table.add_column("Status", style="bold green", width=10, justify="center")

    for i, prompt in enumerate(prompts, 1):
        fg, _ = _AGENT_COLORS[(i - 1) % 7]
        icon  = _AGENT_ICONS[(i - 1) % 7]
        lines = prompt.strip().splitlines()
        first = lines[0] if lines else f"AGENT {i}"
        # Strip markdown bold / "AGENT N - " prefix
        role = first.replace(f"**AGENT {i} - ", "").replace("**", "").strip()
        table.add_row(str(i), f"[{fg}]{icon}[/{fg}]", role, "[green]✓ READY[/green]")

    console.print()
    console.print(Align.center(table))
    console.print()


def display_instructions(saved_path: Optional[str] = None) -> None:
    """Final CTA panel."""
    items = [
        "Open [bold cyan]7 Qwen Code windows[/bold cyan] simultaneously",
        "Paste [bold white]one prompt per window[/bold white] — they are non-overlapping",
        "Run all 7 in [bold green]parallel[/bold green]",
        "Collect diffs → run [bold yellow]supervisor --iterate[/bold yellow] for round 2",
    ]
    if saved_path:
        items.append(f"Plan saved → [dim]{saved_path}[/dim]")

    if RICH:
        content = "\n".join(f"  [dim]›[/dim] {item}" for item in items)
        console.print(
            Panel(
                content,
                title="[bold yellow]📋  NEXT STEPS[/bold yellow]",
                border_style="yellow",
                box=rbox.ROUNDED,
                padding=(1, 2),
            )
        )
        console.print()
        console.print(
            Align.center(
                Panel(
                    Align.center(
                        Text("⚡  SUPERVISOR DONE. FEED THE PROMPTS. SHIP THE CODE.  ⚡",
                             style="bold cyan")
                    ),
                    border_style="cyan",
                    box=rbox.HEAVY,
                    padding=(0, 2),
                )
            )
        )
        console.print()
    else:
        _plain("\n📋 NEXT STEPS:")
        for item in items:
            _plain(f"  › {item}")
        _plain("\n⚡  SUPERVISOR DONE. FEED THE PROMPTS. SHIP THE CODE.\n")


def display_iteration_instructions() -> None:
    if RICH:
        console.print(
            Panel(
                "  [bold white]Paste the output from ALL 7 agents below.[/bold white]\n"
                "  When done, type [bold yellow]END[/bold yellow] on a new line and press Enter.",
                title="[bold yellow]⟳  AGENT RESULTS INPUT[/bold yellow]",
                border_style="yellow",
                padding=(1, 2),
            )
        )
    else:
        _plain("\n>>> Paste all 7 agent outputs. Type END on a new line when done:\n")


# ═════════════════════════════════════════════════════════════════════════════
# INTERNAL HELPERS
# ═════════════════════════════════════════════════════════════════════════════

def _plain(msg: str) -> None:
    print(msg)


def _extract_section(text: str, start_marker: str, end_marker: str) -> str:
    """Return text between start_marker line and next line starting with end_marker."""
    lines  = text.splitlines()
    inside = False
    out    = []
    for line in lines:
        if not inside:
            if line.strip().startswith(start_marker):
                inside = True
                out.append(line)
        else:
            if line.strip().startswith(end_marker) and line.strip() != start_marker:
                break
            out.append(line)
    return "\n".join(out).strip()
