"""
config.py — Credential storage and first-run onboarding wizard.

Config file lives at: ~/.supervisor/config.json

Structure
---------
{
    "setup_complete":      bool,
    "provider":            "anthropic" | "groq" | "none",
    "anthropic_api_key":   "sk-ant-..." | null,
    "groq_api_key":        "gsk_..."   | null,
    "default_model":       "claude-sonnet-4-6",
    "default_project_dir": "/path/to/project" | null,
    "auto_save_plans":     bool,
    "ask_clarification":   bool,
    "show_preflight":      bool,
    "created_at":          "ISO date",
    "version":             "1.0.0"
}
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from . import __version__
from . import display as ui

# ── Config location ───────────────────────────────────────────────────────────
CONFIG_DIR  = Path.home() / ".supervisor"
CONFIG_FILE = CONFIG_DIR / "config.json"

# ── Defaults ──────────────────────────────────────────────────────────────────
_DEFAULTS: dict = {
    "setup_complete":      False,
    "provider":            None,
    "anthropic_api_key":   None,
    "groq_api_key":        None,
    "default_model":       "claude-sonnet-4-6",
    "default_project_dir": None,
    "auto_save_plans":     True,
    "ask_clarification":   True,
    "show_preflight":      True,
    "created_at":          None,
    "version":             __version__,
}

# ── Model options ─────────────────────────────────────────────────────────────
ANTHROPIC_MODELS = [
    ("claude-sonnet-4-6",         "Sonnet 4.6  — Fast & smart  [recommended]"),
    ("claude-opus-4-6",           "Opus 4.6    — Max intelligence, complex codebases"),
    ("claude-haiku-4-5-20251001", "Haiku 4.5   — Fastest & cheapest"),
]
GROQ_MODELS = [
    ("llama-3.3-70b-versatile", "Llama 3.3 70B  — Best Groq model  [recommended]"),
    ("llama-3.1-8b-instant",    "Llama 3.1 8B   — Ultra-fast, lower quality"),
    ("mixtral-8x7b-32768",      "Mixtral 8x7B   — Long context"),
]


# ═════════════════════════════════════════════════════════════════════════════
# LOAD / SAVE
# ═════════════════════════════════════════════════════════════════════════════

def load_config() -> dict:
    """Load config from disk. Returns defaults if file doesn't exist."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if not CONFIG_FILE.exists():
        return dict(_DEFAULTS)
    try:
        raw = json.loads(CONFIG_FILE.read_text("utf-8"))
        # Merge with defaults so new keys added in later versions are present
        merged = dict(_DEFAULTS)
        merged.update(raw)
        return merged
    except (json.JSONDecodeError, OSError):
        return dict(_DEFAULTS)


def save_config(cfg: dict) -> None:
    """Persist config to disk."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def is_setup() -> bool:
    """Return True if the user has completed onboarding."""
    return load_config().get("setup_complete", False)


def reset_config() -> None:
    """Wipe stored config (used by `supervisor init --reset`)."""
    if CONFIG_FILE.exists():
        CONFIG_FILE.unlink()


# ═════════════════════════════════════════════════════════════════════════════
# KEY RESOLUTION  (config → env → None)
# ═════════════════════════════════════════════════════════════════════════════

def resolve_anthropic_key(override: Optional[str] = None) -> Optional[str]:
    if override:
        return override
    cfg = load_config()
    return cfg.get("anthropic_api_key") or os.getenv("ANTHROPIC_API_KEY") or None


def resolve_groq_key(override: Optional[str] = None) -> Optional[str]:
    if override:
        return override
    cfg = load_config()
    return cfg.get("groq_api_key") or os.getenv("GROQ_API_KEY") or None


def resolve_model(override: Optional[str] = None) -> str:
    if override:
        return override
    cfg = load_config()
    return cfg.get("default_model") or "claude-sonnet-4-6"


def resolve_provider() -> Optional[str]:
    cfg = load_config()
    return cfg.get("provider")


# ═════════════════════════════════════════════════════════════════════════════
# ONBOARDING WIZARD
# ═════════════════════════════════════════════════════════════════════════════

def run_onboarding(force: bool = False) -> dict:
    """
    Interactive first-run wizard.

    Walks the user through:
        1. Provider selection (Anthropic / Groq / Skip)
        2. API key entry + validation hint
        3. Default model selection
        4. Default project directory (optional)
        5. Feature preferences (clarification, preflight, auto-save)

    Returns the saved config dict.
    """
    cfg = load_config()

    if cfg.get("setup_complete") and not force:
        return cfg

    _wizard_header()

    # ── Step 1: Provider ──────────────────────────────────────────────────────
    ui.blank()
    ui.rule("STEP 1 / 5  —  Choose your AI provider", style="cyan")
    ui.blank()

    provider = _choose(
        "Which AI provider do you want to use?",
        choices=[
            ("anthropic", "Anthropic Claude  [best quality, requires paid API key]"),
            ("groq",       "Groq / Llama      [free tier available, good quality]"),
            ("none",       "Skip for now      [use template fallback — no AI]"),
        ],
    )
    cfg["provider"] = provider

    # ── Step 2: API Key ───────────────────────────────────────────────────────
    ui.blank()
    ui.rule("STEP 2 / 5  —  API Key", style="cyan")
    ui.blank()

    if provider == "anthropic":
        _print_hint(
            "Get your Anthropic API key at: https://console.anthropic.com/keys\n"
            "  It looks like: sk-ant-api03-..."
        )
        key = _ask_secret("Paste your Anthropic API key (or press Enter to skip): ")
        if key:
            cfg["anthropic_api_key"] = key
            ui.success("Anthropic key saved.")
        else:
            ui.warn("Skipped. You can set ANTHROPIC_API_KEY env var at any time.")

    elif provider == "groq":
        _print_hint(
            "Get your free Groq API key at: https://console.groq.com/keys\n"
            "  It looks like: gsk_..."
        )
        key = _ask_secret("Paste your Groq API key (or press Enter to skip): ")
        if key:
            cfg["groq_api_key"] = key
            ui.success("Groq key saved.")
        else:
            ui.warn("Skipped. You can set GROQ_API_KEY env var at any time.")

    else:
        ui.dim("No key needed for template mode.")

    # ── Step 3: Default model ─────────────────────────────────────────────────
    if provider in ("anthropic", "groq"):
        ui.blank()
        ui.rule("STEP 3 / 5  —  Default model", style="cyan")
        ui.blank()

        model_choices = ANTHROPIC_MODELS if provider == "anthropic" else GROQ_MODELS
        model = _choose(
            "Which model should supervisor use by default?",
            choices=[(m, label) for m, label in model_choices],
            default=model_choices[0][0],
        )
        cfg["default_model"] = model
        ui.success(f"Default model set to: {model}")
    else:
        ui.dim("Step 3 / 5 skipped (no provider selected).")

    # ── Step 4: Default project dir ───────────────────────────────────────────
    ui.blank()
    ui.rule("STEP 4 / 5  —  Default project directory (optional)", style="cyan")
    ui.blank()
    _print_hint(
        "If you always run supervisor from the same project, you can set a default.\n"
        "  Leave blank to always use the current working directory."
    )

    raw_dir = _ask("Default project path (blank = always use cwd): ").strip()
    if raw_dir:
        p = Path(raw_dir).expanduser().resolve()
        if p.is_dir():
            cfg["default_project_dir"] = str(p)
            ui.success(f"Default project dir set: {p}")
        else:
            ui.warn(f"Path not found: {p} — skipping.")
    else:
        ui.dim("Will use current working directory each run.")

    # ── Step 5: Feature preferences ───────────────────────────────────────────
    ui.blank()
    ui.rule("STEP 5 / 5  —  Behaviour preferences", style="cyan")
    ui.blank()

    cfg["ask_clarification"] = _yes_no(
        "Ask clarifying questions when your idea is vague?",
        default=True,
    )
    cfg["show_preflight"] = _yes_no(
        "Show a pre-flight briefing before calling the LLM?",
        default=True,
    )
    cfg["auto_save_plans"] = _yes_no(
        "Auto-save plans as Markdown files in your project folder?",
        default=True,
    )

    # ── Finalise ──────────────────────────────────────────────────────────────
    cfg["setup_complete"] = True
    cfg["created_at"]     = datetime.now().isoformat(timespec="seconds")
    cfg["version"]        = __version__

    save_config(cfg)

    ui.blank()
    _wizard_done(cfg)
    ui.blank()

    return cfg


def show_config() -> None:
    """Pretty-print current config (masking secret keys)."""
    cfg = load_config()
    if not cfg.get("setup_complete"):
        ui.warn("Setup not complete. Run: supervisor init")
        return

    _safe = dict(cfg)
    for field in ("anthropic_api_key", "groq_api_key"):
        if _safe.get(field):
            v = str(_safe[field])
            _safe[field] = v[:8] + "..." + v[-4:] if len(v) > 12 else "***"

    try:
        from rich.table import Table
        from rich import box as rbox
        from .display import console

        table = Table(box=rbox.ROUNDED, border_style="cyan", show_header=False, padding=(0, 1))
        table.add_column("Key",   style="dim white", min_width=24)
        table.add_column("Value", style="bold white")

        for k, v in _safe.items():
            if v is None:
                val = "[dim]—[/dim]"
            elif v is True:
                val = "[green]yes[/green]"
            elif v is False:
                val = "[red]no[/red]"
            else:
                val = str(v)
            table.add_row(k, val)

        console.print()
        from rich.panel import Panel
        console.print(Panel(table, title="[bold cyan]⚙  Current Config[/bold cyan]",
                            border_style="cyan"))
        console.print(f"[dim]  Config file: {CONFIG_FILE}[/dim]")
        console.print()
    except Exception:
        print(json.dumps(_safe, indent=2))
        print(f"\nConfig file: {CONFIG_FILE}")


# ═════════════════════════════════════════════════════════════════════════════
# WIZARD UI HELPERS
# ═════════════════════════════════════════════════════════════════════════════

def _wizard_header() -> None:
    try:
        from rich.panel import Panel
        from rich.text import Text
        from rich.align import Align
        from rich import box as rbox
        from .display import console

        console.print()
        console.print(
            Panel(
                Align.center(
                    Text(
                        "Welcome to swarm-supervisor!\n\n"
                        "This 5-step wizard will configure your API provider,\n"
                        "credentials, default model, and behaviour preferences.\n\n"
                        "Your config is saved to: ~/.supervisor/config.json\n"
                        "API keys are stored locally — never sent anywhere except\n"
                        "directly to Anthropic / Groq.",
                        style="white",
                        justify="center",
                    )
                ),
                title="[bold cyan]🧙  FIRST-RUN SETUP WIZARD[/bold cyan]",
                border_style="cyan",
                box=rbox.DOUBLE,
                padding=(1, 4),
            )
        )
    except Exception:
        print("\n" + "="*60)
        print("  SUPERVISOR — FIRST-RUN SETUP WIZARD")
        print("="*60)


def _wizard_done(cfg: dict) -> None:
    provider = cfg.get("provider", "none")
    model    = cfg.get("default_model", "—")
    try:
        from rich.panel import Panel
        from rich.text import Text
        from rich.align import Align
        from rich import box as rbox
        from .display import console

        body = (
            f"[bold white]Provider:[/bold white] [cyan]{provider}[/cyan]\n"
            f"[bold white]Model:[/bold white]    [cyan]{model}[/cyan]\n\n"
            "[bold green]You're ready to go![/bold green]\n\n"
            "Run:  [bold white]supervisor \"your idea here\"[/bold white]\n"
            "Help: [bold white]supervisor --help[/bold white]\n"
            "Edit: [bold white]supervisor init[/bold white]  (re-run this wizard)"
        )
        console.print(
            Panel(
                Align.center(Text.from_markup(body, justify="center")),
                title="[bold green]✓  SETUP COMPLETE[/bold green]",
                border_style="green",
                box=rbox.HEAVY,
                padding=(1, 4),
            )
        )
    except Exception:
        print(f"\n✓ Setup complete. Provider: {provider}, Model: {model}")
        print('Run: supervisor "your idea here"')


def _choose(prompt: str, choices: list[tuple[str, str]], default: Optional[str] = None) -> str:
    """
    Present a numbered list and return the chosen value.
    `choices` is a list of (value, display_label) tuples.
    """
    try:
        from rich.table import Table
        from rich import box as rbox
        from .display import console

        table = Table(box=rbox.SIMPLE, show_header=False, padding=(0, 1))
        table.add_column("#",     style="bold cyan",  width=4, justify="right")
        table.add_column("Option",style="bold white")

        for i, (_, label) in enumerate(choices, 1):
            table.add_row(str(i), label)

        console.print(f"  [bold yellow]{prompt}[/bold yellow]")
        console.print(table)

        while True:
            raw = _ask(f"  Enter number [1–{len(choices)}]: ").strip()
            if raw.isdigit() and 1 <= int(raw) <= len(choices):
                val = choices[int(raw) - 1][0]
                return val
            print(f"  Please enter a number between 1 and {len(choices)}.")
    except Exception:
        print(f"\n{prompt}")
        for i, (_, label) in enumerate(choices, 1):
            print(f"  {i}. {label}")
        while True:
            raw = input(f"  Enter number [1–{len(choices)}]: ").strip()
            if raw.isdigit() and 1 <= int(raw) <= len(choices):
                return choices[int(raw) - 1][0]


def _yes_no(prompt: str, default: bool = True) -> bool:
    default_str = "Y/n" if default else "y/N"
    raw = _ask(f"  {prompt} [{default_str}]: ").strip().lower()
    if not raw:
        return default
    return raw in ("y", "yes", "1", "true")


def _ask(prompt: str) -> str:
    try:
        from rich.prompt import Prompt
        # Use plain input so we can control the prompt string exactly
        pass
    except Exception:
        pass
    return input(prompt)


def _ask_secret(prompt: str) -> str:
    """Ask for a secret — hides input on supported terminals."""
    import getpass
    try:
        return getpass.getpass(prompt)
    except Exception:
        return input(prompt)


def _print_hint(text: str) -> None:
    try:
        from .display import console
        console.print(f"  [dim]{text}[/dim]")
    except Exception:
        print(f"  {text}")
