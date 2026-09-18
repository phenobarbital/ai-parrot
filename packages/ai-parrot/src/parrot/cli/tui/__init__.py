"""Textual full-screen workspace for ``parrot agent`` (FEAT-573, spec §3 M11-M12).

Import cost matters: ``parrot.cli.agent_repl`` imports ``parrot.cli.tui.app``
lazily and only when the resolved UI mode is TUI (AC22). This package module
therefore re-exports its public names through ``__getattr__`` so importing the
package itself never imports ``textual``.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "AgentWorkspaceApp",
    "Composer",
    "LogDrawer",
    "StatusBar",
    "ToolActivity",
    "TranscriptView",
    "TurnPanel",
]

_WIDGETS = {"Composer", "LogDrawer", "StatusBar", "ToolActivity", "TranscriptView", "TurnPanel"}


def __getattr__(name: str) -> Any:
    """Resolve public names lazily (PEP 562)."""
    if name in _WIDGETS:
        from parrot.cli.tui import widgets  # noqa: PLC0415

        return getattr(widgets, name)
    if name == "AgentWorkspaceApp":
        from parrot.cli.tui.app import AgentWorkspaceApp  # noqa: PLC0415  (TASK-3412)

        return AgentWorkspaceApp
    raise AttributeError(name)
