# Changelog

## 2.0.0 — Agent-agnostic redesign

**Breaking changes, ground-up redesign of the planning/output layer.**

### Removed
- Fixed "exactly 7 agents" output — task count is now adaptive (typically
  1–10, scoped to what the idea actually needs).
- "Qwen Code" hardcoded into every generated prompt — output is now
  tool-agnostic (Spec-Kit-style `tasks.md` + plain JSON).
- Regex-based `**AGENT N - Role**` parsing of LLM output — replaced with
  structured JSON output from the model, validated against a schema.

### Added
- `depgraph.py` — real dependency graph from Python import/call resolution
  and JS/TS relative-import resolution. Detects hotspots (high in-degree or
  pattern-matched shared-surface files).
- `verifier.py` — scores any task plan against the dependency graph for
  direct file conflicts, cross-task coupling, and hotspot overlap. Works
  independently of this package's own LLM planner.
- `supervisor verify` — standalone CLI command, no API key required, works
  on a plan from any source. Scriptable exit codes (0/1/2).
- `mcp_server.py` + `supervisor mcp` — exposes `scan_codebase`,
  `decompose_idea`, `verify_task_plan`, `render_tasks_markdown` as MCP
  tools for Claude Code, Vibe Kanban, Claude Squad, or any MCP client.
- Pre-flight briefing now shows dependency-graph hotspots up front, not
  just file/language counts.
- Iteration rounds now feed the previous round's verification report back
  into the next planning call, so flagged conflicts get corrected instead
  of silently repeated.
- Test suite: 33 tests covering the dependency graph, task parsing/waves,
  conflict scoring, the scanner, config permissions, and CLI dispatch.

### Fixed
- **API keys are no longer stored world/group-readable.**
  `~/.supervisor/config.json` and session history files are now written
  with `chmod 600` (owner read/write only).
- **`supervisor "your idea"` — the tool's own headline usage — could crash
  with `invalid choice`.** argparse's `add_subparsers()` combined with a
  free-form `idea` positional caused any idea string not matching a
  subcommand name to be misparsed as an invalid subcommand selector.
  Confirmed present in 1.x. Fixed by dispatching manually on the first CLI
  token instead of relying on argparse subparsers for this shape.
- `pyproject.toml` version no longer disagrees with `__init__.py`
  (was `1.0.0` vs `1.1.0`).
- `pytest` config referenced a `tests/` directory that didn't exist in the
  package at all — it exists now, with real coverage.

### Known limitations (unchanged philosophy, stated plainly)
- The call-graph edge heuristic is name-based, not scope-resolved — it can
  over-flag generically-named functions defined in multiple files. It's
  deliberately biased toward more caution, not fewer false positives.
- The 40,000-character codebase read budget is unchanged from v1 — large
  repos still get truncated context for LLM-based planning. Verification
  (`supervisor verify`, the MCP `verify_task_plan` tool) is unaffected by
  this, since it operates on the full file tree's resolved graph, not the
  truncated LLM context.
- API keys are still stored in a local plaintext file (now permission-
  restricted, not encrypted or in an OS keychain). Fine for a single-user
  machine; not a substitute for a real secrets manager.

---

## 1.1.0 / 1.0.0 — Original release

Karpathy-style AutoResearcher: scanned a codebase, called Claude or Groq,
and generated exactly 7 markdown-formatted prompts for pasting into 7
parallel Qwen Code agent windows.
