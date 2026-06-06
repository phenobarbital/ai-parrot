"""End-to-end + no-regression tests for OrchestratorAgent conferencing (FEAT-223).

Locks in the behavior of ``confer()`` with a realistic 3-specialist panel and
guarantees the existing LLM-driven ``ask()`` path is unchanged (``confer()`` is
purely additive).
"""
import logging
from types import SimpleNamespace

from parrot.bots.flows.agents import OrchestratorAgent
from parrot.models.conference import PeerVote, ConferenceResult
from parrot.models.responses import AIMessage


class _Spec:
    """Specialist whose ``ask`` returns an AIMessage-like with a ``PeerVote``."""

    def __init__(self, name, answer, label, conf):
        self.name = name
        self._a = answer
        self._l = label
        self._c = conf

    async def ask(self, question, structured_output=None, **kw):
        return SimpleNamespace(
            content=self._a,
            is_structured=True,
            structured_output=PeerVote(
                chosen_label=self._l,
                revised_answer=self._a,
                confidence=self._c,
                rationale="r",
            ),
        )


class _OscillatingSpec:
    """Specialist whose chosen label flips A/B on every successive vote."""

    def __init__(self, name, answer):
        self.name = name
        self._a = answer
        self._calls = 0

    async def ask(self, question, structured_output=None, **kw):
        label = "A" if self._calls % 2 == 0 else "B"
        self._calls += 1
        return SimpleNamespace(
            content=self._a,
            is_structured=True,
            structured_output=PeerVote(
                chosen_label=label,
                revised_answer=self._a,
                confidence=80,
                rationale="r",
            ),
        )


def _make_orch(specialists):
    """OrchestratorAgent with a logger (test conftest stubs the heavy base)."""
    o = OrchestratorAgent(name="orch")
    o.logger = logging.getLogger("test.conference.integration")
    o.specialist_agents = dict(specialists)
    return o


async def test_confer_three_specialists():
    o = _make_orch({
        "alpha": _Spec("alpha", "Paris", "A", 95),
        "beta": _Spec("beta", "Paris", "A", 70),
        "gamma": _Spec("gamma", "London", "A", 55),
    })
    msg = await o.confer("What is the capital of France?", max_rounds=3)

    # AIMessage shape + ConferenceResult payload.
    assert isinstance(msg, AIMessage)
    assert isinstance(msg.structured_output, ConferenceResult)
    assert msg.is_structured is True
    result = msg.structured_output
    assert msg.content == result.final_answer

    # Winner = highest aggregated confidence (all chose label A -> alpha).
    assert result.winner_agent == "alpha"
    assert result.final_answer == "Paris"

    # Each round persisted in ExecutionMemory.
    assert len(o._execution_memory.results) == len(result.rounds)
    assert len(result.rounds) >= 1


def test_peer_block_is_anonymous():
    o = _make_orch({
        "alpha": _Spec("alpha", "Paris", "A", 95),
        "beta": _Spec("beta", "London", "B", 70),
        "gamma": _Spec("gamma", "Berlin", "C", 55),
    })
    block, mapping = o._build_anonymous_peer_block(
        {"alpha": "Paris", "beta": "London", "gamma": "Berlin"}
    )
    # No author names anywhere in the text the LLM sees.
    for name in ("alpha", "beta", "gamma"):
        assert name not in block
    # Labels present; internal mapping correlates labels -> agents.
    assert set(mapping) == {"A", "B", "C"}
    assert mapping["A"] == "alpha"
    assert "Answer A" in block and "Answer C" in block


async def test_confer_max_rounds_cap_oscillating():
    # Oscillating winners never converge -> exactly max_rounds rounds.
    o = _make_orch({
        "alpha": _OscillatingSpec("alpha", "x"),
        "beta": _OscillatingSpec("beta", "y"),
        "gamma": _OscillatingSpec("gamma", "z"),
    })
    msg = await o.confer("Q", max_rounds=3, until_convergence=True)
    result = msg.structured_output
    assert len(result.rounds) == 3
    assert result.converged is False


async def test_ask_no_regression(monkeypatch):
    """confer() must not change the ReAct ask() path (purely additive)."""
    o = _make_orch({})  # no specialists -> ask returns the base response as-is
    sentinel = SimpleNamespace(content="sentinel-react-answer")

    # Stub the base class ask (``super().ask`` inside OrchestratorAgent.ask).
    base_cls = type(o).__mro__[1]

    async def _fake_ask(self, question, **kwargs):
        return sentinel

    monkeypatch.setattr(base_cls, "ask", _fake_ask, raising=False)

    result = await o.ask("hello world")

    # ask() still routes through super().ask() and returns its response
    # untouched when there are no agent results — confer() did not alter it.
    assert result is sentinel
