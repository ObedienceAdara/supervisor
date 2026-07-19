"""
memory.py — Session history and per-project recall.

Storage layout
--------------
~/.supervisor/
    config.json
    history/
        <project_hash>/
            session_20260719_142301.json
            ...

Each session file (chmod 600, same as config.json — this is still plaintext
on disk, so treat it the same way you'd treat any local file containing
excerpts of your source: fine on a machine only you use, not something to
sync to a shared or backed-up location without thinking about it)
--------------------------------------------------------------------------
{
    "id":            "uuid4",
    "timestamp":     "ISO datetime",
    "project_dir":   "/abs/path",
    "project_hash":  "sha1 of project_dir",
    "idea":          "original idea text",
    "task_plan":     {...TaskPlan.to_dict()...},
    "verification":  {...ConflictReport.to_dict()...} | null,
    "model":         "claude-sonnet-4-6",
    "provider":      "anthropic",
    "iteration":     1,
    "files_scanned": 12,
    "total_chars":   34512,
    "version":       "2.0.0"
}
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from . import __version__
from . import display as ui
from .config import CONFIG_DIR, _harden

# ── Storage paths ─────────────────────────────────────────────────────────────
HISTORY_DIR = CONFIG_DIR / "history"
MAX_SESSIONS_PER_PROJECT = 20   # keep the last N per project


# ═════════════════════════════════════════════════════════════════════════════
# SESSION SAVE / LOAD
# ═════════════════════════════════════════════════════════════════════════════

def save_session(
    project_dir:   str,
    idea:          str,
    task_plan:     dict,
    verification:  Optional[dict],
    model:         str,
    provider:      str,
    iteration:     int = 1,
    files_scanned: int = 0,
    total_chars:   int = 0,
) -> str:
    """Persist a session to disk. Returns the path of the saved session file."""
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    phash    = _project_hash(project_dir)
    proj_dir = HISTORY_DIR / phash
    proj_dir.mkdir(exist_ok=True)

    ts      = datetime.now().strftime("%Y%m%d_%H%M%S")
    session = {
        "id":            str(uuid.uuid4()),
        "timestamp":     datetime.now().isoformat(timespec="seconds"),
        "project_dir":   project_dir,
        "project_hash":  phash,
        "idea":          idea,
        "task_plan":     task_plan,
        "verification":  verification,
        "model":         model,
        "provider":      provider,
        "iteration":     iteration,
        "files_scanned": files_scanned,
        "total_chars":   total_chars,
        "version":       __version__,
    }

    path = proj_dir / f"session_{ts}.json"
    path.write_text(json.dumps(session, indent=2, ensure_ascii=False), encoding="utf-8")
    _harden(path)
    _harden(proj_dir, dir_mode=True)

    _prune(proj_dir)
    return str(path)


def load_last_session(project_dir: str) -> Optional[dict]:
    """Load the most recent session for a given project directory."""
    phash    = _project_hash(project_dir)
    proj_dir = HISTORY_DIR / phash
    if not proj_dir.exists():
        return None

    sessions = sorted(proj_dir.glob("session_*.json"), reverse=True)
    if not sessions:
        return None

    try:
        return json.loads(sessions[0].read_text("utf-8"))
    except Exception:
        return None


def load_recent_sessions(project_dir: str, n: int = 5) -> list:
    """Return the last `n` sessions for a project, newest first."""
    phash    = _project_hash(project_dir)
    proj_dir = HISTORY_DIR / phash
    if not proj_dir.exists():
        return []

    sessions = sorted(proj_dir.glob("session_*.json"), reverse=True)[:n]
    result = []
    for s in sessions:
        try:
            result.append(json.loads(s.read_text("utf-8")))
        except Exception:
            pass
    return result


def load_all_recent(n: int = 10) -> list:
    """Return the last `n` sessions across ALL projects, newest first."""
    if not HISTORY_DIR.exists():
        return []

    all_files = sorted(HISTORY_DIR.rglob("session_*.json"), reverse=True)[:n * 3]
    sessions = []
    for f in all_files:
        try:
            sessions.append(json.loads(f.read_text("utf-8")))
        except Exception:
            pass
    sessions.sort(key=lambda s: s.get("timestamp", ""), reverse=True)
    return sessions[:n]


def session_count(project_dir: str) -> int:
    phash    = _project_hash(project_dir)
    proj_dir = HISTORY_DIR / phash
    if not proj_dir.exists():
        return 0
    return len(list(proj_dir.glob("session_*.json")))


def clear_history(project_dir: Optional[str] = None) -> int:
    """Delete history for a specific project (or all projects if None)."""
    import shutil
    if project_dir:
        phash    = _project_hash(project_dir)
        proj_dir = HISTORY_DIR / phash
        if proj_dir.exists():
            count = len(list(proj_dir.glob("session_*.json")))
            shutil.rmtree(proj_dir)
            return count
        return 0
    else:
        if not HISTORY_DIR.exists():
            return 0
        count = len(list(HISTORY_DIR.rglob("session_*.json")))
        shutil.rmtree(HISTORY_DIR)
        return count


# ═════════════════════════════════════════════════════════════════════════════
# DISPLAY HELPERS
# ═════════════════════════════════════════════════════════════════════════════

def show_last_session_hint(project_dir: str) -> None:
    """If a previous session exists for this project, show a compact reminder."""
    session = load_last_session(project_dir)
    if not session:
        return

    ts    = session.get("timestamp", "")[:16].replace("T", "  ")
    idea  = session.get("idea", "")
    model = session.get("model", "?")
    count = session_count(project_dir)

    if ui.RICH:
        from rich.panel import Panel
        from rich.text import Text
        from rich import box as rbox

        body = (
            f"[dim]Last run:[/dim]  [white]{ts}[/white]\n"
            f"[dim]Idea:[/dim]      [italic white]{_truncate(idea, 70)}[/italic white]\n"
            f"[dim]Model:[/dim]     [cyan]{model}[/cyan]  "
            f"[dim]·  {count} session{'s' if count != 1 else ''} stored for this project[/dim]"
        )
        ui.console.print(
            Panel(Text.from_markup(body), title="[bold dim]📂  Previous session found[/bold dim]",
                  border_style="dim", box=rbox.SIMPLE, padding=(0, 2))
        )
        ui.console.print()
    else:
        print(f"\n[Last session] {ts}  |  {_truncate(idea, 60)}\n")


def show_history(project_dir: Optional[str] = None, n: int = 10) -> None:
    """Print a table of recent sessions."""
    sessions = (
        load_recent_sessions(project_dir, n)
        if project_dir
        else load_all_recent(n)
    )

    if not sessions:
        print("No history found.")
        return

    if ui.RICH:
        from rich.table import Table
        from rich.panel import Panel
        from rich import box as rbox

        table = Table(box=rbox.ROUNDED, border_style="dim", show_lines=True, padding=(0, 1))
        table.add_column("Date",    style="dim white",  width=16)
        table.add_column("Project", style="cyan",       min_width=18, max_width=30)
        table.add_column("Idea",    style="white",      min_width=28, max_width=50)
        table.add_column("Model",   style="dim cyan",   width=18)
        table.add_column("Verdict", style="bold white", width=10, justify="center")
        table.add_column("Iter",    style="bold white", width=5, justify="center")

        for s in sessions:
            pdir = s.get("project_dir", "?")
            verification = s.get("verification") or {}
            table.add_row(
                s.get("timestamp", "")[:16].replace("T", " "),
                _truncate(Path(pdir).name, 28),
                _truncate(s.get("idea", ""), 48),
                s.get("model", "?"),
                verification.get("verdict", "—"),
                str(s.get("iteration", 1)),
            )

        ui.console.print()
        ui.console.print(Panel(table, title="[bold cyan]📜  Session History[/bold cyan]",
                                border_style="cyan"))
        ui.console.print()
    else:
        for s in sessions:
            print(f"  {s.get('timestamp','')[:16]}  {s.get('idea','')[:60]}")


# ═════════════════════════════════════════════════════════════════════════════
# INTERNAL HELPERS
# ═════════════════════════════════════════════════════════════════════════════

def _project_hash(project_dir: str) -> str:
    """Stable 10-char SHA-1 prefix from the absolute project path."""
    return hashlib.sha1(str(Path(project_dir).resolve()).encode()).hexdigest()[:10]


def _prune(proj_dir: Path) -> None:
    """Keep only the newest MAX_SESSIONS_PER_PROJECT session files."""
    files = sorted(proj_dir.glob("session_*.json"), reverse=True)
    for old in files[MAX_SESSIONS_PER_PROJECT:]:
        try:
            old.unlink()
        except Exception:
            pass


def _truncate(text: str, n: int) -> str:
    return text if len(text) <= n else text[:n - 1] + "…"
