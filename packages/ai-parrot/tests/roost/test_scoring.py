"""Unit tests for Contract Net bid scoring."""

from parrot.roost.scoring import Bid, FixedWeightScorer, rank_bids


def _bid(name: str, cost: float, time_ms: float, confidence: float) -> Bid:
    """Build a bid with a stable message identifier."""
    return Bid(agent_name=name, cost=cost, time_ms=time_ms, confidence=confidence, message_id=name)


def test_rule_decides() -> None:
    """The default scorer picks the more confident, cheaper, faster bid."""
    award = rank_bids([_bid("a", 10, 100, 0.9), _bid("b", 20, 200, 0.5)])

    assert award.winner is not None
    assert award.winner.agent_name == "a"
    assert award.decided_by == "rule"
    assert len(award.rejected) == 1


def test_tie_wakes_llm() -> None:
    """Scores within the tie threshold leave selection to the requester LLM."""
    award = rank_bids([_bid("a", 1, 1, 0.5), _bid("b", 1, 1, 0.5)])

    assert award.winner is None
    assert award.decided_by == "llm"


def test_empty_window() -> None:
    """An empty bid window has no winner and remains rule-decided."""
    award = rank_bids([])

    assert award.winner is None
    assert award.decided_by == "rule"
    assert award.rejected == []


def test_custom_scorer() -> None:
    """A channel scorer overrides the default weighting rule."""

    class Cheapest:
        """Score lower absolute cost higher."""

        def score(self, bid: Bid, *, cost_norm: float, time_norm: float) -> float:
            """Return the inverse absolute bid cost."""
            return -bid.cost

    award = rank_bids([_bid("a", 5, 1, 1.0), _bid("b", 1, 1, 0.1)], Cheapest())

    assert award.winner is not None
    assert award.winner.agent_name == "b"
