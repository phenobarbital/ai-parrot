"""Data models for multi-party conferencing (FEAT-223).

These Pydantic v2 models are the typed contract for the OrchestratorAgent's
deterministic conferencing mode:

- :class:`PeerVote` — a single agent's structured vote after seeing the
  anonymized answers of its peers.
- :class:`ConferenceRound` — the state of one cross-pollination + vote round.
- :class:`ConferenceResult` — the aggregated outcome of a conference.

The ``label_to_agent`` mapping on :class:`ConferenceRound` is an internal
bookkeeping structure: it correlates anonymous labels (``A``/``B``/``C``...)
back to the agent that produced each answer. It MUST NEVER be serialized into
a prompt shown to an LLM, to avoid reintroducing authority bias.
"""
from typing import Dict, List

from pydantic import BaseModel, Field


class PeerVote(BaseModel):
    """Structured vote of an agent after seeing the anonymous peer answers."""

    chosen_label: str = Field(
        ...,
        description=(
            "Anonymous label (A, B, C...) of the answer the agent keeps. "
            "May be the agent's own answer."
        ),
    )
    revised_answer: str = Field(
        ...,
        description=(
            "Agent's final answer (it may keep its own or adopt another's)."
        ),
    )
    confidence: float = Field(
        ...,
        ge=0,
        le=100,
        description="Agent's confidence in its choice, 0-100.",
    )
    rationale: str = Field(
        ...,
        description="Brief justification of the choice.",
    )


class ConferenceRound(BaseModel):
    """State of one cross-pollination + vote round."""

    round_index: int = Field(
        ...,
        description="1-based index of this round within the conference.",
    )
    answers: Dict[str, str] = Field(
        ...,
        description="Anonymous label -> answer text for this round.",
    )
    label_to_agent: Dict[str, str] = Field(
        ...,
        description=(
            "Anonymous label -> agent name. Internal mapping; NEVER exposed "
            "to the LLM."
        ),
    )
    votes: Dict[str, PeerVote] = Field(
        ...,
        description="Agent name -> the vote that agent cast this round.",
    )


class ConferenceResult(BaseModel):
    """Aggregated outcome of a multi-party conference."""

    winner_agent: str = Field(
        ...,
        description="Name of the agent whose answer won the final round.",
    )
    final_answer: str = Field(
        ...,
        description="The winning agent's revised answer.",
    )
    confidence_score: float = Field(
        ...,
        description="Aggregated confidence score of the winner.",
    )
    rounds: List[ConferenceRound] = Field(
        ...,
        description="Full audit trail of every conference round.",
    )
    vote_breakdown: Dict[str, float] = Field(
        ...,
        description=(
            "Label/agent -> accumulated confidence of the final round."
        ),
    )
    converged: bool = Field(
        ...,
        description="Whether the conference converged before max_rounds.",
    )
