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
    compaction: fast-jev-compaction plugin wiring (Jev-guided verbatim
        compaction; installed by default, ``--no-compaction`` to skip).
    cli: ``parrot claude`` click command group.
"""

from typing import Any

__all__ = [
    "install_claude_integration",
    "uninstall_claude_integration",
    "integration_status",
]


def __getattr__(name: str) -> Any:
    """Resolve the installer API lazily (PEP 562).

    Importing ``claude_code.hook`` runs this package's ``__init__`` first;
    an eager ``installer`` import would put the installer (and the pydantic
    config) on every PreToolUse hook launch (FEAT-595).
    """
    if name in __all__:
        from parrot.knowledge.wiki.claude_code import installer

        return getattr(installer, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
