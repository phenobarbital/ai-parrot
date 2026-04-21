"""Tests for O365Tool Telegram permission-context credential bridge."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from parrot_tools.o365.base import O365AuthMode, O365Tool


class _DummyO365Tool(O365Tool):
    name = "dummy_o365"
    description = "dummy"

    async def _get_client(self, auth_mode=None, user_assertion=None, scopes=None):  # type: ignore[override]
        self._captured = {
            "auth_mode": auth_mode,
            "assertion": self.credentials.get("assertion"),
        }
        return object()

    async def _execute_graph_operation(self, client, **kwargs):  # type: ignore[override]
        return {"ok": True}


@pytest.mark.asyncio
async def test_permission_context_injects_assertion_and_obo_mode() -> None:
    tool = _DummyO365Tool(credentials={"client_id": "cid", "tenant_id": "tid"})
    pctx = SimpleNamespace(extra={"o365_access_token": "delegated-token"})

    result = await tool.execute(_permission_context=pctx)

    assert result.status == "success"
    assert tool._captured["auth_mode"] == O365AuthMode.OBO
    assert tool._captured["assertion"] == "delegated-token"

