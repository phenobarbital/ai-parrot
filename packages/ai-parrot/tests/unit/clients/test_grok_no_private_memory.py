"""Grok carries no private conversation-memory path (FEAT-524, TASK-2814).

Spec §4 M5 row ``test_grok_has_no_private_memory_path``. Before FEAT-524
``grok.py`` was the *third* copy of turn persistence in the codebase: it did
not use the base class's ``_prepare_conversation_context`` /
``_update_conversation_memory`` at all, it hand-rolled its own
``self.conversation_memory.add_turn(...)`` in both ``ask`` and ``ask_stream``.
That is exactly the kind of drift this guard exists to catch, so the check is
source-level (AST + token scan) rather than behavioural.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from parrot.clients import grok as grok_module
from parrot.clients.grok import GrokClient

_SOURCE = Path(inspect.getfile(grok_module)).read_text(encoding="utf-8")
_TREE = ast.parse(_SOURCE)


def _code_lines_containing(token: str) -> list[str]:
    """Source lines mentioning ``token`` outside comments."""
    return [line.strip() for line in _SOURCE.splitlines() if token in line and not line.lstrip().startswith("#")]


@pytest.mark.parametrize(
    "token",
    [
        "conversation_memory",
        "ConversationTurn",
        "add_turn",
        "get_conversation",
        "get_messages_for_api",
    ],
)
def test_grok_has_no_private_memory_path(token: str):
    """No conversation-storage token survives anywhere in ``grok.py``."""
    assert _code_lines_containing(token) == []


def test_grok_does_not_import_memory_storage():
    """``grok.py`` imports no ``parrot.memory`` name except the render type."""
    imported: list[str] = []
    for node in ast.walk(_TREE):
        if isinstance(node, ast.ImportFrom) and node.module and "memory" in node.module:
            imported.extend(f"{node.module}.{alias.name}" for alias in node.names)

    assert imported == ["..memory.render.HistoryMessage"] or all(
        name.endswith(".HistoryMessage") for name in imported
    ), imported


def test_grok_ask_signature_is_memoryless():
    """``ask``/``ask_stream`` take ``history`` and neither id."""
    for name in ("ask", "ask_stream"):
        parameters = inspect.signature(getattr(GrokClient, name)).parameters
        assert "history" in parameters, name
        assert "user_id" not in parameters, name
        assert "session_id" not in parameters, name


def test_grok_replays_supplied_history():
    """Both entry points feed the ``history`` argument into the xAI chat.

    Grok does not use ``_build_messages`` — the xAI SDK wants ``chat.append()``
    calls rather than a message list — so the guard is that each method
    iterates ``history`` and dispatches on ``message.role``.
    """
    for name in ("ask", "ask_stream"):
        method = next(
            node
            for node in ast.walk(_TREE)
            if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == name
        )
        body = ast.dump(method)
        assert "'history'" in body, f"{name} never reads history"
        assert "assistant_fn" in body, f"{name} never appends assistant turns"
