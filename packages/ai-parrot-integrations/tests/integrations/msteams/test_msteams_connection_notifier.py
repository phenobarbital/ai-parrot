"""FEAT-775 M4: Teams connection notifier (AC-6, AC-7)."""

from types import SimpleNamespace
from typing import Any, Dict, Optional

import pytest

from parrot.auth.oauth2.events import ConnectionEvent
from parrot.auth.oauth2.registry import OAuth2ProviderRegistry
from parrot.integrations.msteams.connections import MSTeamsConnectionNotifier, MSTeamsConversationRefStore


class FakeRedis:
    """Minimal async Redis fake that records expiry values."""

    def __init__(self) -> None:
        self.values: Dict[str, str] = {}
        self.expiries: Dict[str, int] = {}

    async def set(self, key: str, value: str, *, ex: int) -> None:
        """Store one string and its expiry."""
        self.values[key] = value
        self.expiries[key] = ex

    async def get(self, key: str) -> Optional[str]:
        """Return one stored string."""
        return self.values.get(key)


class FakeTurnContext:
    """Capture proactive activities sent by a fake adapter."""

    def __init__(self) -> None:
        self.activities: list[Any] = []

    async def send_activity(self, activity: Any) -> None:
        """Record one outgoing activity."""
        self.activities.append(activity)


class FakeAdapter:
    """Record proactive sends and execute their callbacks."""

    def __init__(self, *, raises: bool = False) -> None:
        self.raises = raises
        self.calls: list[tuple[Any, str]] = []
        self.turn_context = FakeTurnContext()

    async def continue_conversation(self, ref: Any, callback: Any, app_id: str) -> None:
        """Record the route and run the callback unless configured to fail."""
        if self.raises:
            raise RuntimeError("adapter failed")
        self.calls.append((ref, app_id))
        await callback(self.turn_context)


@pytest.fixture(autouse=True)
def provider_registry() -> None:
    """Give each test an isolated provider display-name registry."""
    OAuth2ProviderRegistry._reset()
    OAuth2ProviderRegistry()._providers["jira"] = SimpleNamespace(display_name="Jira")
    yield
    OAuth2ProviderRegistry._reset()


@pytest.fixture
def conversation_reference() -> Dict[str, Any]:
    """Return a serialized personal conversation reference owned by app-2."""
    return {
        "activity_id": "activity-1",
        "user": {"id": "29:user"},
        "bot": {"id": "28:app-2"},
        "conversation": {"id": "conversation-1", "conversation_type": "personal"},
        "channel_id": "msteams",
        "service_url": "https://smba.trafficmanager.net/emea/",
    }


def make_event(kind: str, *, reason: str = "secret failure reason") -> ConnectionEvent:
    """Build one Teams connection event."""
    return ConnectionEvent(
        kind=kind,
        user_id="nav-1",
        provider="jira",
        account_id="account-1",
        display_name="Ada",
        channel="msteams",
        occurred_at=1.0,
        reason=reason,
    )


@pytest.mark.asyncio
async def test_notifier_completed_uses_state_ref(conversation_reference: Dict[str, Any]) -> None:
    """Callback state routes a completed message through its explicit app id."""
    adapter = FakeAdapter()
    notifier = MSTeamsConnectionNotifier(ref_store=None)
    notifier.attach("app-1", adapter)

    await notifier.notify(
        make_event("connection.completed"),
        {"extra": {"conversation_reference": conversation_reference, "bot_app_id": "app-1"}},
    )

    assert [call[1] for call in adapter.calls] == ["app-1"]
    assert adapter.turn_context.activities[0].text == "Jira connected as **Ada**. Ask again to use it."


@pytest.mark.asyncio
async def test_notifier_refresh_failed_uses_ref_store(conversation_reference: Dict[str, Any]) -> None:
    """Out-of-turn refresh failures load the reference by Navigator user id."""
    redis = FakeRedis()
    store = MSTeamsConversationRefStore(redis)
    await store.save("nav-1", conversation_reference)
    adapter = FakeAdapter()
    notifier = MSTeamsConnectionNotifier(store)
    notifier.attach("app-2", adapter)

    await notifier.notify(make_event("connection.refresh_failed"), {})

    assert adapter.turn_context.activities[0].text == "Jira access expired — `/connect jira` to reconnect."


@pytest.mark.asyncio
async def test_notifier_revoked_text(conversation_reference: Dict[str, Any]) -> None:
    """Revocation uses the exact provider-disconnected text."""
    adapter = FakeAdapter()
    notifier = MSTeamsConnectionNotifier(ref_store=None)
    notifier.attach("app-2", adapter)

    await notifier.notify(make_event("connection.revoked"), {"extra": {"conversation_reference": conversation_reference}})

    assert adapter.turn_context.activities[0].text == "Jira disconnected."


@pytest.mark.asyncio
async def test_notifier_multi_bot_routing(conversation_reference: Dict[str, Any]) -> None:
    """The reference bot id selects only the owning bot's adapter."""
    adapter_1 = FakeAdapter()
    adapter_2 = FakeAdapter()
    notifier = MSTeamsConnectionNotifier(ref_store=None)
    notifier.attach("app-1", adapter_1)
    notifier.attach("app-2", adapter_2)

    await notifier.notify(make_event("connection.revoked"), {"extra": {"conversation_reference": conversation_reference}})

    assert adapter_1.calls == []
    assert [call[1] for call in adapter_2.calls] == ["app-2"]


@pytest.mark.asyncio
async def test_notifier_never_raises(conversation_reference: Dict[str, Any], caplog: pytest.LogCaptureFixture) -> None:
    """Adapter failures, missing references, and unknown app ids are logged and swallowed."""
    failing = MSTeamsConnectionNotifier(ref_store=None)
    failing.attach("app-2", FakeAdapter(raises=True))
    await failing.notify(make_event("connection.completed"), {"extra": {"conversation_reference": conversation_reference}})

    await MSTeamsConnectionNotifier(ref_store=None).notify(make_event("connection.revoked"), {})
    await MSTeamsConnectionNotifier(ref_store=None).notify(
        make_event("connection.refresh_failed"), {"extra": {"conversation_reference": conversation_reference}}
    )

    assert "Teams notifier failed" in caplog.text
    assert "no conversation reference" in caplog.text
    assert "no adapter attached" in caplog.text
    assert "secret failure reason" not in caplog.text


@pytest.mark.asyncio
async def test_ref_store_round_trip_and_ttl(conversation_reference: Dict[str, Any]) -> None:
    """Conversation references round-trip as JSON with the 30-day TTL."""
    redis = FakeRedis()
    store = MSTeamsConversationRefStore(redis)

    await store.save("nav-1", conversation_reference)

    assert await store.get("nav-1") == conversation_reference
    assert redis.expiries["msteams:convref:nav-1"] == 30 * 86400
