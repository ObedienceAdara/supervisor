"""
swarm-supervisor — agent-agnostic task decomposition + conflict verification
for AI coding agents.

v2 redesign: no longer tied to a fixed "7 agents" count or to Qwen Code.
Turns a codebase + a feature idea into a verified, dependency-graph-checked
task plan, rendered as a Spec-Kit-style tasks.md (or consumed directly as
JSON by any orchestrator) — and exposes the same decomposition + conflict
verification as an MCP server so other tools (Claude Code, Vibe Kanban,
Claude Squad, or anything else that speaks MCP) can call it directly.
"""

__version__ = "2.0.0"
__author__  = "Plex Hedge"
__email__   = "hello@plexhedge.com"
__url__     = "https://github.com/plexhedge/swarm-supervisor"
