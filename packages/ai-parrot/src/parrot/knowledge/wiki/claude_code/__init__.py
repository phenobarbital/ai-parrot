"""Claude Code integration for the LLM Wiki (FEAT-260 follow-up).

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
"""

from parrot.knowledge.wiki.claude_code.installer import (
    install_claude_integration,
    integration_status,
    uninstall_claude_integration,
)

__all__ = [
    "install_claude_integration",
    "uninstall_claude_integration",
    "integration_status",
]
