"""Unit tests for OrchestratorAgent multi-party conferencing (FEAT-223).

Covers the broadcast + anonymized peer-block helpers (TASK-1476). Extended with
structured voting / weighted tally / convergence tests in TASK-1477.
"""
import logging
from types import SimpleNamespace

import pytest

from parrot.bots.flows.agents import OrchestratorAgent
from parrot.models.conference import PeerVote, ConferenceResult


class _FakeAgent:
    """Minimal specialist whose ``ask`` returns an AIMessage-like object."""

    def __init__(self, name, answer):
        self.name = name
        self._answer = answer

    async def ask(self, question, **kw):
        return SimpleNamespace(content=self._answer)


class _VotingAgent:
    """Specialist whose ``ask`` returns an AIMessage-like with a ``PeerVote``."""

    def __init__(self, name, answer, chosen_label, confidence):
        self.name = name
        self._answer = answer
        self._label = chosen_label
        self._conf = confidence

    async def ask(self, question, structured_output=None, **kw):
        return SimpleNamespace(
            content=self._answer,
            is_structured=True,
            structured_output=PeerVote(
                chosen_label=self._label,
                revised_answer=self._answer,
                confidence=self._conf,
                rationale="r",
            ),
        )


class _NoStructuredAgent:
    """Specialist that ignores ``structured_output`` (no structured payload)."""

    def __init__(self, name, answer):
        self.name = name
        self._answer = answer

    async def ask(self, question, structured_output=None, **kw):
        return SimpleNamespace(content=self._answer)


class _OscillatingAgent:
    """Specialist whose chosen label flips A/B on every successive vote."""

    def __init__(self, name, answer):
        self.name = name
        self._answer = answer
        self._calls = 0

    async def ask(self, question, structured_output=None, **kw):
        label = "A" if self._calls % 2 == 0 else "B"
        self._calls += 1
        return SimpleNamespace(
            content=self._answer,
            is_structured=True,
            structured_output=PeerVote(
                chosen_label=label,
                revised_answer=self._answer,
                confidence=80,
                rationale="r",
            ),
        )


def _make_orch(specialists):
    """Build an OrchestratorAgent with a logger and the given specialists.

    The test conftest stubs the heavy BasicAgent base (no ``logger``); production
    BasicAgent provides ``self.logger``, so the test supplies one here.
    """
    o = OrchestratorAgent(name="orch")
    o.logger = logging.getLogger("test.conference")
    o.specialist_agents = dict(specialists)
    return o


@pytest.fixture(scope="module")
def orch():
    return _make_orch({
        "data": _FakeAgent("data", "answer-from-data"),
        "policy": _FakeAgent("policy", "answer-from-policy"),
    })


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


# ── TASK-1477: voting, weighted tally, convergence, confer() ─────────────────

class TestVotingAndConfer:
    def test_weighted_tally_winner(self, orch):
        votes = {
            "data": PeerVote(chosen_label="A", revised_answer="x",
                             confidence=90, rationale="r"),
            "policy": PeerVote(chosen_label="B", revised_answer="y",
                               confidence=40, rationale="r"),
        }
        winner, breakdown = orch._tally_weighted_votes(votes)
        assert winner == "A" and breakdown["A"] == 90

    def test_tie_break_lowest_label(self, orch):
        votes = {
            "data": PeerVote(chosen_label="B", revised_answer="y",
                             confidence=50, rationale="r"),
            "policy": PeerVote(chosen_label="A", revised_answer="x",
                               confidence=50, rationale="r"),
        }
        winner, _ = orch._tally_weighted_votes(votes)
        assert winner == "A"

    def test_weighted_tally_self_vote(self, orch):
        # Two agents both keep their own answer (label A); their confidence sums.
        votes = {
            "data": PeerVote(chosen_label="A", revised_answer="x",
                             confidence=30, rationale="r"),
            "policy": PeerVote(chosen_label="A", revised_answer="x",
                               confidence=25, rationale="r"),
        }
        winner, breakdown = orch._tally_weighted_votes(votes)
        assert winner == "A" and breakdown["A"] == 55

    async def test_vote_fallback_no_structured(self):
        o = _make_orch({
            "data": _VotingAgent("data", "a-data", "A", 90),
            "policy": _NoStructuredAgent("policy", "a-policy"),
        })
        answers = {"data": "a-data", "policy": "a-policy"}
        block, label_to_agent = o._build_anonymous_peer_block(answers)
        votes = await o._collect_votes("Q", block, label_to_agent, None)
        assert set(votes) == {"data", "policy"}
        # Specialist without structured output -> normalized vote, conf 50,
        # keeps its own label (B), round does not fail.
        assert votes["policy"].confidence == 50
        assert votes["policy"].chosen_label == "B"
        assert votes["data"].confidence == 90

    async def test_confer_end_to_end(self):
        o = _make_orch({
            "data": _VotingAgent("data", "best-answer", "A", 95),
            "policy": _VotingAgent("policy", "best-answer", "A", 60),
        })
        msg = await o.confer("Q", max_rounds=3)
        assert isinstance(msg.structured_output, ConferenceResult)
        assert msg.is_structured is True
        assert msg.content == msg.structured_output.final_answer
        assert msg.structured_output.converged is True
        assert msg.structured_output.winner_agent == "data"
        # Each round persisted to ExecutionMemory.
        assert len(o._execution_memory.results) == len(msg.structured_output.rounds)

    async def test_convergence_stops_early(self):
        o = _make_orch({
            "data": _VotingAgent("data", "best-answer", "A", 95),
            "policy": _VotingAgent("policy", "best-answer", "A", 60),
        })
        msg = await o.confer("Q", max_rounds=3, until_convergence=True)
        result = msg.structured_output
        assert result.converged is True
        # Stable winner converges on the second round (2 < max_rounds=3).
        assert len(result.rounds) == 2

    async def test_max_rounds_cap_no_convergence(self):
        # until_convergence=False -> always run the full cap, converged False.
        o = _make_orch({
            "data": _VotingAgent("data", "x", "A", 95),
            "policy": _VotingAgent("policy", "y", "B", 60),
        })
        msg = await o.confer("Q", max_rounds=2, until_convergence=False)
        result = msg.structured_output
        assert len(result.rounds) == 2
        assert result.converged is False

    async def test_max_rounds_cap_oscillating(self):
        # Oscillating winners never converge -> exactly max_rounds rounds.
        o = _make_orch({
            "data": _OscillatingAgent("data", "x"),
            "policy": _OscillatingAgent("policy", "y"),
        })
        msg = await o.confer("Q", max_rounds=3, until_convergence=True)
        result = msg.structured_output
        assert len(result.rounds) == 3
        assert result.converged is False
