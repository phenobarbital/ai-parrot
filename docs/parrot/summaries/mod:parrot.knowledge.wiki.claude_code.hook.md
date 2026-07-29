---
type: Wiki Summary
title: parrot.knowledge.wiki.claude_code.hook
id: mod:parrot.knowledge.wiki.claude_code.hook
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: PreToolUse hook runtime for the Claude Code wiki integration.
relates_to:
- concept: func:parrot.knowledge.wiki.claude_code.hook.build_nudge
  rel: defines
- concept: func:parrot.knowledge.wiki.claude_code.hook.run_pre_tool_use_hook
  rel: defines
- concept: mod:parrot.knowledge.wiki.claude_code.assets
  rel: references
- concept: mod:parrot.knowledge.wiki.project
  rel: references
- concept: mod:parrot.knowledge.wiki.repo_scan
  rel: references
---

# `parrot.knowledge.wiki.claude_code.hook`

PreToolUse hook runtime for the Claude Code wiki integration.

Invoked by Claude Code as ``wikitoolkit claude-hook`` before
search-style tool calls (``Grep``/``Glob``/``Read``).  Reads the hook
payload from stdin and — when the repository has a built wiki plane —
emits a non-blocking JSON nudge (``hookSpecificOutput.additionalContext``)
steering the assistant toward ``wikitoolkit query "<question>"``
instead of scanning raw files.

Design constraints:

- **Never blocks**: no ``permissionDecision`` is emitted, so the
  normal permission flow is untouched; the nudge is context only.
- **Never breaks the session**: any error exits 0 silently.
- **Throttled**: at most one nudge per cooldown window (default 300 s,
  configurable via ``claude.nudge_cooldown_seconds`` in
  ``.parrot/wiki.json``) so search-heavy turns are not spammed.
- **Fast**: imports are dependency-light (stdlib + pydantic).

## Functions

- `def build_nudge(payload: dict[str, Any], root: Optional[Path]=None, config: Optional[WikiProjectConfig]=None, now: Optional[float]=None) -> Optional[dict[str, Any]]` — Decide whether the hook payload deserves a wiki nudge.
- `def run_pre_tool_use_hook(stdin: Optional[TextIO]=None, stdout: Optional[TextIO]=None) -> int` — Entry point for ``wikitoolkit claude-hook`` / ``parrot claude hook``.
