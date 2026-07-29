---
type: Wiki Summary
title: parrot.knowledge.wiki.claude_code
id: mod:parrot.knowledge.wiki.claude_code
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Claude Code integration for the LLM Wiki (FEAT-260 follow-up).
relates_to:
- concept: mod:parrot.knowledge.wiki.claude_code.installer
  rel: references
---

# `parrot.knowledge.wiki.claude_code`

Claude Code integration for the LLM Wiki (FEAT-260 follow-up).

Installs the repository knowledge graph as coding-assistant
infrastructure, graphify-style:

- ``parrot claude install`` — writes a managed CLAUDE.md section, a
  PreToolUse nudge hook, the ``/parrotwiki`` slash command, and an
  optional git ``post-commit`` auto-upsert hook;
- ``wikitoolkit claude-hook`` — the PreToolUse hook runtime that
  nudges the assistant toward ``wikitoolkit query "<question>"``
  before search-style tool calls.

Modules:
    assets: Managed file templates and markers.
    installer: Idempotent install/uninstall/status operations.
    hook: PreToolUse hook runtime (fast, dependency-light).
    cli: ``parrot claude`` click command group.
