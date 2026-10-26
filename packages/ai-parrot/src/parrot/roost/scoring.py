"""Contract Net bid scoring (FEAT-747 M2). Pure, deterministic, no I/O."""
from __future__ import annotations

from typing import Literal, Optional, Protocol, Sequence

from pydantic import BaseModel, Field


class Bid(BaseModel):
    """One ``propose`` reduced to the fields the harness scores."""

    agent_name: str
    cost: float
    time_ms: float
    confidence: float = Field(ge=0.0, le=1.0)
    message_id: str


class Award(BaseModel):
    """Outcome of a bid window."""

    winner: Optional[Bid] = None
    decided_by: Literal["rule", "llm"] = "rule"
    rejected: list[Bid] = Field(default_factory=list)


class BidScorer(Protocol):
    """Per-channel deterministic strategy where higher scores are better."""

    def score(self, bid: Bid, *, cost_norm: float, time_norm: float) -> float:
        """Return the score for one bid using window-normalized values."""


class FixedWeightScorer:
    """Score bids with confidence, normalized cost, and normalized time weights."""

    def __init__(self, *, w_confidence: float = 0.5, w_cost: float = 0.3, w_time: float = 0.2) -> None:
        self.w_confidence = w_confidence
        self.w_cost = w_cost
        self.w_time = w_time

    def score(self, bid: Bid, *, cost_norm: float, time_norm: float) -> float:
        """Return this scorer's weighted score for *bid*."""
        return self.w_confidence * bid.confidence - self.w_cost * cost_norm - self.w_time * time_norm


def rank_bids(bids: Sequence[Bid], scorer: Optional[BidScorer] = None, *, tie_epsilon: float = 1e-6) -> Award:
    """Score *bids* and return an award, delegating ties within *tie_epsilon* to an LLM."""
    if not bids:
        return Award()

    scorer = scorer or FixedWeightScorer()
    costs = [bid.cost for bid in bids]
    times = [bid.time_ms for bid in bids]
    min_cost, max_cost = min(costs), max(costs)
    min_time, max_time = min(times), max(times)
    cost_span = max_cost - min_cost
    time_span = max_time - min_time

    scored_bids = [
        (
            scorer.score(
                bid,
                cost_norm=(bid.cost - min_cost) / cost_span if cost_span else 0.0,
                time_norm=(bid.time_ms - min_time) / time_span if time_span else 0.0,
            ),
            bid,
        )
        for bid in bids
    ]
    scored_bids.sort(key=lambda scored_bid: (-scored_bid[0], scored_bid[1].agent_name))

    if len(scored_bids) > 1 and abs(scored_bids[0][0] - scored_bids[1][0]) <= tie_epsilon:
        return Award(decided_by="llm")

    return Award(winner=scored_bids[0][1], rejected=[bid for _, bid in scored_bids[1:]])
