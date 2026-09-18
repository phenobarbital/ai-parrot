"""FEAT-099 (TASK-082): integration status reflects whether vault tokens are usable."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from parrot.auth.oauth2.models import IntegrationDescriptor
from parrot.auth.oauth2.service import IntegrationsService

PROVIDER = SimpleNamespace(
    provider_id="jira",
    display_name="Jira",
    icon=None,
    default_scopes=["read"],
)
ROW = SimpleNamespace(
    account_id="acc-1", display_name="Jira Account", email="a@b.c", connected_at=None
)


class FakeRead:
    def __init__(self, status):
        self.status = status
        self.tokens = {"access_token": "tok"} if status == "ok" else None


class FakeSync:
    def __init__(self, status="ok", error=None):
        self._status = status
        self._error = error
        self.calls = 0

    async def read_tokens_result(self, user_id, provider):
        self.calls += 1
        if self._error:
            raise self._error
        return FakeRead(self._status)


@pytest.fixture
def patched_registry():
    with patch("parrot.auth.oauth2.service.OAuth2ProviderRegistry") as registry:
        registry.return_value.all.return_value = [PROVIDER]
        with patch(
            "parrot.auth.oauth2.service.list_user_agent_toolkits",
            new=AsyncMock(return_value=[]),
        ):
            yield


async def list_one(sync, row=ROW):
    service = IntegrationsService(vault_token_sync=sync)
    with patch(
        "parrot.auth.oauth2.service.get_users_integration", new=AsyncMock(return_value=row)
    ), patch.object(IntegrationsService, "_check_pbac", new=AsyncMock(return_value=True)):
        items = await service.list_for_user("user-1", "agent-1", request=SimpleNamespace(app={}))
    return items[0]


@pytest.mark.asyncio
class TestListForUserStatus:
    async def test_readable_tokens_are_connected(self, patched_registry):
        item = await list_one(FakeSync("ok"))
        assert item.status == "connected" and item.connected is True
        assert item.account_id == "acc-1"

    @pytest.mark.parametrize("status", ["unreadable", "missing"])
    async def test_unusable_tokens_need_reconnect(self, patched_registry, status):
        item = await list_one(FakeSync(status))
        assert item.status == "needs_reconnect" and item.connected is False
        # metadata is still shown so the UI can render the account row
        assert item.account_id == "acc-1"

    async def test_no_row_is_disconnected(self, patched_registry):
        sync = FakeSync("ok")
        item = await list_one(sync, row=None)
        assert item.status == "disconnected" and item.connected is False
        assert sync.calls == 0  # no vault probe without a credential row

    async def test_vault_outage_does_not_hide_integrations(self, patched_registry):
        item = await list_one(FakeSync(status="unavailable"))
        assert item.status == "connected"

    async def test_probe_failure_is_swallowed(self, patched_registry, caplog):
        item = await list_one(FakeSync(error=RuntimeError("redis down")))
        assert item.status == "connected"

    async def test_probe_skipped_without_app(self, patched_registry):
        service = IntegrationsService()
        with patch(
            "parrot.auth.oauth2.service.get_users_integration", new=AsyncMock(return_value=ROW)
        ), patch.object(IntegrationsService, "_check_pbac", new=AsyncMock(return_value=True)):
            items = await service.list_for_user("user-1", "agent-1", request=None)
        assert items[0].status == "connected"


class TestDescriptorContract:
    def test_status_and_connected_stay_in_sync(self):
        assert IntegrationDescriptor(provider="p", display_name="P", connected=True).status == "connected"
        assert IntegrationDescriptor(provider="p", display_name="P").status == "disconnected"
        needs = IntegrationDescriptor(provider="p", display_name="P", status="needs_reconnect")
        assert needs.connected is False
        assert needs.model_dump(mode="json")["status"] == "needs_reconnect"

    def test_invalid_status_rejected(self):
        with pytest.raises(Exception):
            IntegrationDescriptor(provider="p", display_name="P", status="broken")
