"""Unit tests for OrchestratorAgent multi-party conferencing (FEAT-223).

Covers the broadcast + anonymized peer-block helpers (TASK-1476). Extended with
structured voting / weighted tally / convergence tests in TASK-1477.
"""
import logging
from types import SimpleNamespace

import pytest

from parrot.bots.flows.agents import OrchestratorAgent


class _FakeAgent:
    """Minimal specialist whose ``ask`` returns an AIMessage-like object."""

    def __init__(self, name, answer):
        self.name = name
        self._answer = answer

    async def ask(self, question, **kw):
        return SimpleNamespace(content=self._answer)


@pytest.fixture(scope="module")
def orch():
    # The test conftest stubs the heavy BasicAgent base (no ``logger``), so the
    # fixture supplies one — production BasicAgent provides ``self.logger``.
    o = OrchestratorAgent(name="orch")
    o.logger = logging.getLogger("test.conference")
    o.specialist_agents = {
        "data": _FakeAgent("data", "answer-from-data"),
        "policy": _FakeAgent("policy", "answer-from-policy"),
    }
    return o


# ── TASK-1476: broadcast + anonymous peer block ──────────────────────────────

class TestBroadcastAndBlock:
    async def test_broadcast_parallel(self, orch):
        out = await orch._broadcast_round("Q")
        assert set(out) == {"data", "policy"}
        assert out["data"] == "answer-from-data"
        assert out["policy"] == "answer-from-policy"

    async def test_broadcast_subset(self, orch):
        out = await orch._broadcast_round("Q", agents=["data"])
        assert set(out) == {"data"}

    def test_anonymous_block(self, orch):
        # NOTE: answer text deliberately does NOT embed the agent names
        # ("data"/"policy") so the anonymity assertion is meaningful — the
        # task's literal sample answers ("answer-from-data") contained the
        # agent name as a substring, which no correct block could exclude.
        block, mapping = orch._build_anonymous_peer_block(
            {"data": "the sky is blue", "policy": "the grass is green"}
        )
        assert "data" not in block and "policy" not in block  # no author names
        assert set(mapping) == {"A", "B"}
        assert mapping["A"] == "data" and mapping["B"] == "policy"
        assert "Answer A" in block and "Answer B" in block

    def test_truncation(self, orch):
        block, _ = orch._build_anonymous_peer_block({"data": "x" * 5000})
        assert "[truncated]" in block
        # The truncated body keeps at most 2000 chars of the original answer.
        assert block.count("x") == 2000

    def test_resolve_unknown_agent_raises(self, orch):
        with pytest.raises(ValueError):
            orch._resolve_agents(["nope"])

    def test_resolve_none_returns_all(self, orch):
        assert set(orch._resolve_agents(None)) == {"data", "policy"}
