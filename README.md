# swarm-supervisor

**Agent-agnostic task decomposition + dependency-graph conflict verification
for AI coding agents.**


```
 ░██████╗██╗   ██╗██████╗ ███████╗██████╗ ██╗   ██╗██╗███████╗ ██████╗ ██████╗ 
 ██╔════╝██║   ██║██╔══██╗██╔════╝██╔══██╗██║   ██║██║██╔════╝██╔═══██╗██╔══██╗
 ╚█████╗ ██║   ██║██████╔╝█████╗  ██████╔╝╚██╗ ██╔╝██║███████╗██║   ██║██████╔╝
  ╚═══██╗██║   ██║██╔═══╝ ██╔══╝  ██╔══██╗  ╚████╔╝ ██║╚════██║██║   ██║██╔══██╗
 ██████╔╝╚██████╔╝██║     ███████╗██║  ██║   ╚══╝  ██║███████║╚██████╔╝██║  ██║
 ╚═════╝  ╚═════╝ ╚═╝     ╚══════╝╚═╝  ╚═╝         ╚═╝╚══════╝ ╚═════╝ ╚═╝  ╚═╝
```

Turn a feature idea and a codebase into a task plan that's actually checked
for conflicts — not just split by an LLM's best guess — and use it with
whatever agent or orchestrator you already run: Claude Code, Vibe Kanban,
Claude Squad, Conductor, ccswarm, or plain human hands across a few
terminal windows.

```
supervisor "Add rate limiting to the /upload endpoint"
```

That's it. No fixed task count, no target-tool lock-in.

---

## What changed in v2

v1 of this tool always produced *exactly 7* prompts, hardcoded for pasting
into *Qwen Code* specifically. That was a narrow, single-tool niche in an
ecosystem that has since filled up with general-purpose orchestrators and
official spec-driven standards (GitHub's Spec-Kit, the AGENTS.md standard).

v2 narrows to the one thing that ecosystem still doesn't do well:
**verifying that a proposed task split is actually independent**, using a
real dependency graph built from your code — not an LLM's prose promise
that it "won't touch" a file.

- No fixed task count — plans adapt from 1 to ~10 tasks based on scope.
- No tool name baked into output — plans render as a Spec-Kit-style
  `tasks.md`, or as JSON any orchestrator can consume.
- A real dependency graph (Python import/call resolution + JS/TS relative
  import resolution) scores every plan for direct file conflicts, cross-task
  coupling, and shared "hotspot" files — before you run anything.
- Ships as a CLI **and** an MCP server, so the same verification is callable
  by Claude Code, Vibe Kanban, or any other MCP-capable client directly.
- `supervisor verify` works standalone — hand it a task plan from *any*
  source (not just this tool) and get a conflict report back. No API key
  required for verification; it's local static analysis.

---

## Install

```bash
pip install swarm-supervisor
# or, to also use it as an MCP server:
pip install swarm-supervisor[mcp]
```

First run walks you through a short setup wizard (API provider, key,
default model). Skip it entirely and the tool still works via a
deterministic template — you just lose codebase-aware planning, not
verification.

```bash
supervisor init          # (re-)run the setup wizard
```

---

## Usage

### Plan + verify in one go

```bash
supervisor "Add FAISS vector search to the /query endpoint"
supervisor "Add FAISS vector search" ./my-project --model claude-opus-4-6
```

This scans the codebase, decomposes the idea into a task plan, checks it
against the dependency graph, and saves both `tasks.md` (human/agent
readable) and `plan.json` (machine readable) to your project folder.

### Verify a plan from anywhere — no LLM needed

```bash
supervisor verify --project-dir . --tasks plan.json
supervisor verify --project-dir . --tasks - < claude_codes_own_plan.json
```

`--tasks` accepts any JSON with a `tasks` list matching the schema below —
including a plan you wrote by hand, or one another tool produced. Exit
codes are scriptable: `0` = SAFE, `1` = RISKY, `2` = CONFLICT.

### Run as an MCP server

```bash
supervisor mcp
```

Exposes four tools: `scan_codebase`, `decompose_idea`, `verify_task_plan`,
`render_tasks_markdown`. Point any MCP client at it (stdio transport) to
call decomposition and verification directly from your existing agent or
orchestrator, instead of shelling out to a separate CLI.

### Iterate

```bash
supervisor "Add FAISS vector search" --iterate
```

After the first round, paste back what happened (diffs, summaries — from
whatever ran the tasks), and the next round's plan is generated with that
context plus the previous round's verification report, so repeated
conflicts get corrected instead of repeated.

---

## The task plan schema

```json
{
  "idea": "Add rate limiting to the /upload endpoint",
  "tasks": [
    {
      "id": "T1",
      "title": "Rate-limit middleware",
      "description": "Implement a token-bucket limiter as FastAPI middleware.",
      "target_files": ["app/middleware/rate_limit.py"],
      "avoid_files": ["app/routes/upload.py"],
      "depends_on": [],
      "acceptance_criteria": ["429 returned after limit exceeded", "unit tests pass"]
    }
  ],
  "integration_notes": "Wire the middleware into app/main.py after T1 lands."
}
```

Plain JSON, no tool-specific fields. `supervisor verify` and the MCP
`verify_task_plan` tool only require the `tasks` list with `id` and
`target_files` on each entry — everything else is optional.

---

## How verification works

`depgraph.py` resolves two kinds of edges from your actual source:

- **Import edges** — Python dotted-module resolution (absolute + relative),
  JS/TS relative-path resolution with extension guessing.
- **Call edges** — Python only, name-based: if file A calls a function
  named `X` and file B defines a function/class named `X`, that's a
  candidate edge. This is a heuristic (no real scope resolution), so it can
  over-flag common names — it errs toward more caution, not less.

`verifier.py` then scores a task plan:

| Check | What it means |
|---|---|
| **Direct conflicts** | Same file claimed by 2+ tasks — always `CONFLICT`. |
| **Coupling risks** | An import/call edge crosses two tasks' file sets — real entanglement, not assumed. |
| **Hotspot hits** | A high-in-degree or pattern-matched shared-surface file (`config.py`, `routes.py`, `__init__.py`, ...) claimed by more than one task. |

Score starts at 100 and is docked per finding; verdict is `SAFE` / `RISKY`
/ `CONFLICT`. None of this requires an LLM call — it's static analysis
over what your code actually imports and calls.

**Known limitation:** this is heuristic, not a language server. It won't
catch every semantic conflict (e.g. two tasks relying on incompatible
assumptions about a shared file neither one edits), and the call-graph
heuristic can produce false positives on generically-named functions. It's
meaningfully more grounded than trusting an LLM's promise, not a
replacement for actually running the tasks and testing the result.

---

## Development

```bash
pip install -e ".[dev,mcp]"
pytest
```

The test suite (33 tests) covers the dependency graph resolver, task
parsing/rendering, conflict scoring, the codebase scanner, config file
permissions, and the CLI argument dispatch — all without needing API keys,
since none of it depends on a live LLM call.

---

## License

MIT — see [LICENSE](LICENSE).
adata
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
