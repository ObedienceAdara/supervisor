# swarm-supervisor

> **Karpathy-style AutoResearcher** — scan your codebase, think like an architect, generate 7 parallel Qwen Code agent prompts in seconds.

```
 ░██████╗██╗   ██╗██████╗ ███████╗██████╗ ██╗   ██╗██╗███████╗ ██████╗ ██████╗ 
 ██╔════╝██║   ██║██╔══██╗██╔════╝██╔══██╗██║   ██║██║██╔════╝██╔═══██╗██╔══██╗
 ╚█████╗ ██║   ██║██████╔╝█████╗  ██████╔╝╚██╗ ██╔╝██║███████╗██║   ██║██████╔╝
  ╚═══██╗██║   ██║██╔═══╝ ██╔══╝  ██╔══██╗  ╚████╔╝ ██║╚════██║██║   ██║██╔══██╗
 ██████╔╝╚██████╔╝██║     ███████╗██║  ██║   ╚══╝  ██║███████║╚██████╔╝██║  ██║
 ╚═════╝  ╚═════╝ ╚═╝     ╚══════╝╚═╝  ╚═╝         ╚═╝╚══════╝ ╚═════╝ ╚═╝  ╚═╝
```

[![PyPI version](https://img.shields.io/pypi/v/swarm-supervisor.svg)](https://pypi.org/project/swarm-supervisor/)
[![Python](https://img.shields.io/pypi/pyversions/swarm-supervisor.svg)](https://pypi.org/project/swarm-supervisor/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

---

## What it does

You type **one idea**. Supervisor:

1. **Scans your codebase** — builds a file tree, reads contents, extracts Python symbols with AST.
2. **Calls an LLM** (Claude or Groq) with the full codebase context + your idea.
3. **Generates 7 non-overlapping macro tasks** — no merge conflicts by design.
4. **Outputs 7 copy-paste-ready prompts** — one per Qwen Code agent window.
5. **Saves a timestamped Markdown plan** to your current folder.

Run all 7 agents in parallel → collect diffs → run `supervisor --iterate` for round 2.

---

## Install

```bash
pip install swarm-supervisor
```

> **Note:** The `supervisor` command may conflict with the `supervisor` process manager (`supervisord`) if you have it installed. If so, use the full path or a virtual environment.

---

## Quick Start

```bash
# Set your API key (one-time)
export ANTHROPIC_API_KEY="sk-ant-..."   # Claude (recommended)
# or
export GROQ_API_KEY="gsk_..."           # Groq / Llama (free tier)

# Run from your project root
cd /path/to/your/project
supervisor "Add real vector search with FAISS + SSE streaming responses"
```

That's it. 7 agent prompts printed and saved to `supervisor_plan_<timestamp>.md`.

---

## Usage

```
supervisor IDEA [PROJECT_DIR] [OPTIONS]
```

### Arguments

| Argument       | Description                                                      |
|---------------|------------------------------------------------------------------|
| `IDEA`         | Your high-level feature idea (quoted string). Prompted if omitted. |
| `PROJECT_DIR`  | Path to your project root. Defaults to current directory.        |

### Options

| Flag                    | Short | Description                                                    |
|------------------------|-------|----------------------------------------------------------------|
| `--project-dir DIR`     | `-p`  | Named form of PROJECT_DIR (overrides positional).              |
| `--api-key KEY`         | `-k`  | Anthropic API key (overrides `ANTHROPIC_API_KEY` env var).     |
| `--groq-key KEY`        |       | Groq API key (overrides `GROQ_API_KEY` env var).               |
| `--model MODEL`         | `-m`  | Anthropic model. Default: `claude-sonnet-4-6`.                 |
| `--output-dir DIR`      | `-o`  | Where to save the plan `.md` file. Default: current directory. |
| `--no-save`             |       | Skip saving the plan to disk.                                  |
| `--iterate`             |       | Enter iteration loop after first plan.                         |
| `--version`             | `-V`  | Show version and exit.                                         |
| `--help`                | `-h`  | Show help and exit.                                            |

### Examples

```bash
# Basic — scan current dir, use ANTHROPIC_API_KEY from env
supervisor "Add FAISS vector search with smart chunking"

# Explicit project path (positional shorthand)
supervisor "Refactor the authentication module" ./my-api

# Explicit project path (named flag)
supervisor "Add WebSocket support" --project-dir ~/projects/my-api

# Use Groq instead of Claude
supervisor "Add caching layer" --groq-key gsk_xxx

# Use Claude Opus for complex codebases
supervisor "Migrate from REST to GraphQL" --model claude-opus-4-6

# Save plan to a specific folder
supervisor "Add OAuth2 integration" --output-dir ./docs/plans

# Iterate (round 2 after agents finish)
supervisor "Add OAuth2 integration" --iterate

# Non-interactive (CI/CD usage — no Rich colors needed)
supervisor "Add rate limiting" --no-save 2>&1 | tee plan.txt
```

---

## API Keys

Supervisor supports two LLM backends:

### Claude (Anthropic) — Recommended

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

Models (pass via `--model`):
- `claude-sonnet-4-6` — default, fast and smart
- `claude-opus-4-6` — max intelligence for complex codebases
- `claude-haiku-4-5-20251001` — fastest, cheapest

### Groq (Llama) — Free tier available

```bash
export GROQ_API_KEY="gsk_..."
```

Uses `llama-3.3-70b-versatile` automatically. No extra flags needed — Supervisor falls back to Groq if no Anthropic key is set.

### No API key

If neither key is set, Supervisor generates a **deterministic template plan** — still useful for structuring your work, just not codebase-aware.

---

## How the 7 Agents are split

By default, Supervisor divides work across these non-overlapping domains:

| Agent | Domain                | Files Touched                          |
|------|-----------------------|----------------------------------------|
| 1    | Core Logic            | Primary backend module (e.g. `app.py`) |
| 2    | API / Route Layer     | Route / endpoint files                 |
| 3    | Frontend / UI         | Frontend files (`.tsx`, `.jsx`, etc.)  |
| 4    | Data Models / Schemas | Models, schemas, migrations            |
| 5    | Tests                 | `tests/` directory                     |
| 6    | Config & Deps         | `requirements.txt`, `.env.example`     |
| 7    | Docs & Cleanup        | `README.md`, docstrings, type hints    |

When you have an Anthropic or Groq key, the split is **codebase-aware** — Supervisor reads your actual files and tailors each agent's scope to your specific architecture.

---

## Iteration Mode

After all 7 agents finish:

```bash
supervisor "My original idea" --iterate
```

Supervisor will:
1. Ask if you want to run iteration 2
2. Prompt you to paste all 7 agent outputs (diffs, summaries)
3. Type `END` on a new line when done
4. Generate 7 new prompts for integration, conflict resolution, and remaining tasks

---

## Output Format

Every run saves a file like `supervisor_plan_20250115_142301.md` to your current directory:

```markdown
# Supervisor Plan — 2025-01-15 14:23:01

Generated by swarm-supervisor

---

=== AUTO-RESEARCHER PLAN ===
1. Implement FAISS index building in app.py ...
...

=== 7 AGENT PROMPTS (copy-paste ready) ===

**AGENT 1 - Core Vector Search Logic**
You are working ONLY on `app.py` ...

...

=== INSTRUCTIONS FOR ME ===
- Open 7 Qwen Code windows simultaneously
...
```

---

## Requirements

- Python 3.9+
- `rich` ≥ 13.0 (terminal UI)
- `anthropic` ≥ 0.25 (optional — for Claude backend)

Install Groq support (no extra package needed — uses stdlib `urllib`).

---

## Development

```bash
git clone https://github.com/plexhedge/swarm-supervisor
cd swarm-supervisor
pip install -e ".[dev]"

# Run tests
pytest

# Build for PyPI
python -m build
twine upload dist/*
```

---

## Project Structure

```
swarm_supervisor/
├── __init__.py     — version + metadata
├── cli.py          — argparse entry point + main()
├── researcher.py   — codebase scanner (AST + file tree)
├── planner.py      — LLM planner (Anthropic + Groq + fallback)
├── generator.py    — prompt extraction, file saving, iteration I/O
└── display.py      — Rich CLI components (banner, spinners, agent cards)
```

---

## License

MIT — see [LICENSE](LICENSE).

---

Built by **[Plex Hedge](https://plexhedge.com)** — AI automation & integration agency, Lagos.
