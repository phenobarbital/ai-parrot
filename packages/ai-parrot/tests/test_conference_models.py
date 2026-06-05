"""Unit tests for the conference data models (FEAT-223, TASK-1475)."""
import pytest
from pydantic import ValidationError

from parrot.models.conference import PeerVote, ConferenceRound, ConferenceResult


def _vote(**kw):
    base = dict(chosen_label="A", revised_answer="x", confidence=80, rationale="r")
    base.update(kw)
    return PeerVote(**base)


class TestPeerVote:
    def test_valid(self):
        assert _vote().confidence == 80

    def test_confidence_bounds(self):
        with pytest.raises(ValidationError):
            _vote(confidence=150)
        with pytest.raises(ValidationError):
            _vote(confidence=-1)

    def test_confidence_edges(self):
        assert _vote(confidence=0).confidence == 0
        assert _vote(confidence=100).confidence == 100


class TestConferenceModels:
    def test_round_roundtrip(self):
        r = ConferenceRound(
            round_index=1,
            answers={"A": "a1"},
            label_to_agent={"A": "agent_x"},
            votes={"agent_x": _vote()},
        )
        assert r.votes["agent_x"].chosen_label == "A"
        assert r.label_to_agent["A"] == "agent_x"

    def test_result_fields(self):
        res = ConferenceResult(
            winner_agent="agent_x",
            final_answer="a1",
            confidence_score=80.0,
            rounds=[],
            vote_breakdown={"A": 80.0},
            converged=True,
        )
        assert res.converged is True
        assert res.winner_agent == "agent_x"
        assert res.final_answer == "a1"

    def test_exported_from_package_root(self):
        from parrot.models import (
            PeerVote as P,
            ConferenceRound as CR,
            ConferenceResult as CRes,
        )
        assert P is PeerVote
        assert CR is ConferenceRound
        assert CRes is ConferenceResult
