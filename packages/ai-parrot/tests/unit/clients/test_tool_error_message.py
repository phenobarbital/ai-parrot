"""FEAT-500 (G3/AC5): the client never raises a message-less `ValueError`.

`AbstractClient._execute_tool` used to do `raise ValueError(result.error)`
verbatim. When the REPL worker layer failed with a bare `TimeoutError()`
(whose `str()` is `''`), that reached the agent as `ValueError('')` — the
"blank error" half of the cold-start incident (spec §1). The wrapper now
substitutes a readable fallback when a tool reports `status="error"` without
a message.

`_execute_tool` is exercised unbound against a minimal stand-in `self`: it
only touches `_tool_context`, `_permission_context`, `_tool_param_names`,
`tool_manager` and `logger`, so no provider client — and no network — is
needed.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from parrot.clients.base import AbstractClient
from parrot.tools.abstract import ToolResult


class _FakeToolManager:
    """Minimal ToolManager whose `execute_tool` returns a canned ToolResult."""

    def __init__(self, result: ToolResult):
        self._result = result
        self.calls: list[tuple] = []

    async def execute_tool(self, tool_name, parameters, permission_context=None):
        self.calls.append((tool_name, parameters, permission_context))
        return self._result


def _client_stub(result: ToolResult) -> SimpleNamespace:
    """A stand-in `self` carrying only what `_execute_tool` reads."""
    return SimpleNamespace(
        tool_manager=_FakeToolManager(result),
        logger=logging.getLogger("test.client"),
        _tool_context=None,
        _permission_context=None,
        _tool_param_names=lambda _name: None,
    )


async def test_client_value_error_never_blank():
    """An empty `error` becomes the fallback text, never `ValueError('')`."""
    stub = _client_stub(ToolResult(status="error", result=None, error=""))

    with pytest.raises(ValueError, match="without a message") as excinfo:
        await AbstractClient._execute_tool(stub, "python_repl_pandas", {})

    message = str(excinfo.value)
    assert message  # the whole point: never blank
    assert "python_repl_pandas" in message


async def test_client_value_error_preserves_a_real_message():
    """A tool that DOES report an error still surfaces its own message."""
    stub = _client_stub(ToolResult(status="error", result=None, error="repl_worker[pid=42]: boom"))

    with pytest.raises(ValueError, match="repl_worker\\[pid=42\\]: boom"):
        await AbstractClient._execute_tool(stub, "python_repl_pandas", {})


async def test_client_returns_result_on_success():
    """The success path is untouched."""
    stub = _client_stub(ToolResult(status="success", result="42", error=None))

    assert await AbstractClient._execute_tool(stub, "python_repl_pandas", {}) == "42"
