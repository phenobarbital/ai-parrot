"""Offline regression coverage for Studio conversation retention and worker reuse."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from parrot.handlers.studio import conversation, meta_agent


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, 86400),
        ("", 86400),
        ("600", 600),
        ("0", None),
        ("-1", 86400),
        ("0.5", 86400),
        ("inf", 86400),
        ("nan", 86400),
        ("bad", 86400),
    ],
)
def test_retention_settings(monkeypatch: pytest.MonkeyPatch, raw: str | None, expected: int | None) -> None:
    """Only explicit zero disables expiry; omitted content has bounded retention too."""
    settings = {conversation.BACKEND_SETTING: "redis", conversation.TTL_SETTING: raw}
    monkeypatch.setattr(conversation, "config", SimpleNamespace(get=settings.get))
    kwargs = conversation.studio_conversation_kwargs()
    assert kwargs["memory_type"] == "redis"
    assert kwargs["memory_config"].get("history_ttl") == expected
    assert kwargs["memory_config"].get("omission_ttl") == expected


def test_default_memory_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    """A host without Redis settings keeps the existing in-process backend."""
    monkeypatch.setattr(conversation, "config", SimpleNamespace(get=lambda key: None))
    assert conversation.studio_conversation_kwargs() == {}


def _worker() -> meta_agent.StudioAssistantHandler:
    """An independent worker cache without database or HTTP services."""
    handler = meta_agent.StudioAssistantHandler(make_mocked_request("POST", "/assistant", app=web.Application()))
    handler._declarative_only = AsyncMock(return_value=False)
    return handler


@pytest.mark.asyncio
async def test_alternating_workers_reuse_their_instances(monkeypatch: pytest.MonkeyPatch) -> None:
    """Returning to a worker must not create another client/toolset for the same conversation."""
    factory = Mock(side_effect=lambda **kw: SimpleNamespace(**kw, configure=AsyncMock()))
    monkeypatch.setattr(meta_agent, "AgentStudioAgent", factory)
    monkeypatch.setattr(meta_agent, "studio_conversation_kwargs", dict)
    first, second = _worker(), _worker()
    session = {}
    partition = meta_agent.Partition("acme", "u1")
    one = await first._get_or_create_assistant(session, api_key=None, identity=partition)
    original_entry = session[meta_agent.SESSION_KEY][partition.key].copy()
    two = await second._get_or_create_assistant(session, api_key=None, identity=partition)
    assert one is not two
    for worker, expected in [(first, one), (second, two), (first, one)]:
        assert await worker._get_or_create_assistant(session, api_key=None, identity=partition) is expected
    assert session[meta_agent.SESSION_KEY][partition.key] == original_entry
    assert factory.call_count == 2
    assert len(first._instances()) == len(second._instances()) == 1


@pytest.mark.asyncio
async def test_wrong_partition_still_gets_a_fresh_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reusing names for absent instances never reuses an instance from another partition."""
    monkeypatch.setattr(meta_agent, "AgentStudioAgent", lambda **kw: SimpleNamespace(**kw, configure=AsyncMock()))
    monkeypatch.setattr(meta_agent, "studio_conversation_kwargs", dict)
    worker = _worker()
    partition = meta_agent.Partition("acme", "u1")
    stolen = SimpleNamespace(name="other", _assistant_partition=meta_agent.Partition("globex", "u1"))
    worker._instances()[(*partition, "other")] = stolen
    session = {meta_agent.SESSION_KEY: {partition.key: {"instance": "other", "session_id": "s"}}}
    agent = await worker._get_or_create_assistant(session, api_key=None, identity=partition)
    assert agent is not stolen
    assert agent.name != stolen.name
    assert agent._assistant_partition == partition
