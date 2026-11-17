"""Behavioral acceptance tests for User knowledge models and bounded extraction."""

import json
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

from parrot.memory.agent_memory.models import MemoryEvent, MemoryRequestScope
from parrot.memory.user.extraction import extract_user_knowledge
from parrot.memory.user.models import UserKnowledgeCandidate, UserKnowledgeCommand

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


class FakeClient:
    """Duck-typed AbstractClient double returning a canned response."""

    model = "fake-model"

    def __init__(self, reply: Any) -> None:
        self.reply = reply
        self.calls: list[dict[str, Any]] = []

    async def ask(self, prompt: str, model: str, **kwargs: Any) -> Any:
        self.calls.append({"prompt": prompt, "model": model, **kwargs})
        if isinstance(self.reply, Exception):
            raise self.reply
        return SimpleNamespace(output=self.reply)


def _event(user_id: str | None = "u1", **payload: Any) -> MemoryEvent:
    scope = MemoryRequestScope(
        tenant_id="t1",
        agent_id="a1",
        user_id=user_id,
        turn_id="turn-1",
        identity_provenance="server_resolved",
    )
    body = {"user_message": "I prefer metric units", **payload}
    return MemoryEvent(event_id="e1", kind="user_knowledge", scope=scope, observed_at=NOW, payload=body)


@pytest.mark.asyncio
async def test_explicit_vs_inferred_and_temporary() -> None:
    """Explicit may be active, inference pending, temporary statements keep validity."""
    reply = json.dumps(
        [
            {"kind": "preference", "value": "metric", "provenance": "explicit"},
            {"kind": "fact", "value": "likes hiking", "provenance": "inferred"},
            {
                "kind": "goal",
                "value": "ship beta",
                "provenance": "explicit",
                "context": {"project": "apollo"},
                "valid_from": "2026-01-01T00:00:00+00:00",
                "expires_at": "2026-02-01T02:00:00+02:00",
            },
        ]
    )
    client = FakeClient(reply)
    result = await extract_user_knowledge(
        _event(user_message="I prefer metric units. I want to ship beta. Maybe I like hiking?"), client=client
    )
    assert [c.initial_status for c in result] == ["active", "pending", "active"]
    assert result[2].context == {"project": "apollo"}
    assert result[2].expires_at == datetime(2026, 2, 1, 0, 0, tzinfo=timezone.utc)
    assert all(c.evidence_refs == ("event:e1",) for c in result)
    assert client.calls[0]["model"] == "fake-model"


@pytest.mark.asyncio
async def test_candidate_cannot_override_principal() -> None:
    """Forged identity fields drop the item; missing identity or partial streams yield nothing."""
    forged = json.dumps(
        [
            {"kind": "fact", "value": "x", "provenance": "explicit", "user_id": "victim"},
            {"kind": "fact", "value": "ok", "provenance": "explicit", "evidence_refs": ["forged"]},
        ]
    )
    result = await extract_user_knowledge(_event(), client=FakeClient(forged))
    assert len(result) == 1
    assert result[0].evidence_refs == ("event:e1",)
    assert not hasattr(result[0], "user_id")
    with pytest.raises(ValidationError):
        UserKnowledgeCandidate(kind="fact", value="x", provenance="explicit", evidence_refs=("r",), tenant_id="other")
    client = FakeClient(forged)
    assert await extract_user_knowledge(_event(user_id=None), client=client) == []
    assert await extract_user_knowledge(_event(partial=True), client=client) == []
    assert client.calls == []


@pytest.mark.asyncio
async def test_malformed_or_oversized_extraction() -> None:
    """Malformed, oversized, naive-time or failing output never produces candidates."""
    assert await extract_user_knowledge(_event(), client=FakeClient("not json")) == []
    assert await extract_user_knowledge(_event(), client=FakeClient(RuntimeError("boom"))) == []
    big = json.dumps([{"kind": "fact", "value": "y" * 5000, "provenance": "explicit"}])
    assert await extract_user_knowledge(_event(), client=FakeClient(big)) == []
    naive = json.dumps([{"kind": "fact", "value": "v", "provenance": "explicit", "expires_at": "2026-01-01T00:00:00"}])
    assert await extract_user_knowledge(_event(), client=FakeClient(naive)) == []
    many = json.dumps([{"kind": "fact", "value": str(i), "provenance": "explicit"} for i in range(20)])
    assert len(await extract_user_knowledge(_event(), client=FakeClient(many))) == 8

    candidate = UserKnowledgeCandidate(kind="fact", value="v", provenance="explicit", evidence_refs=("r",))
    with pytest.raises(ValidationError):
        UserKnowledgeCommand(event_id="e1", operation="correct", candidate=candidate)
    with pytest.raises(ValidationError):
        UserKnowledgeCommand(
            event_id="e1", operation="forget", knowledge_id="k", expected_revision=0, candidate=candidate
        )
    command = UserKnowledgeCommand(
        event_id="e1", operation="correct", knowledge_id="k", expected_revision=2, candidate=candidate
    )
    assert command.expected_revision == 2


@pytest.mark.asyncio
async def test_extracts_from_runtime_response_event_payload() -> None:
    """The runtime response event carries the user text under ``query``, not ``user_message``."""
    scope = MemoryRequestScope(
        tenant_id="t1", agent_id="a1", user_id="u1", turn_id="turn-1", identity_provenance="server_resolved"
    )
    event = MemoryEvent(
        event_id="e2",
        kind="response",
        scope=scope,
        observed_at=NOW,
        payload={"query": "I prefer metric units", "response": "Noted."},
    )
    client = FakeClient(json.dumps([{"kind": "preference", "value": "metric", "provenance": "explicit"}]))
    result = await extract_user_knowledge(event, client=client)
    assert [c.value for c in result] == ["metric"]
    assert len(client.calls) == 1
