"""Pluggable importance scoring strategies for episodic memory.

Defines the ImportanceScorer protocol and provides two implementations:
- HeuristicScorer: normalized version of the original inline logic in store.py
- ValueScorer: port of AgentCoreMemory's ValueScorer, adapted for EpisodicMemory
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field

from .models import EpisodeOutcome, EpisodicMemory

# Known error types that boost importance (mirrors store.py logic)
_KNOWN_ERROR_TYPES = {
    "timeout",
    "rate_limit",
    "permission",
    "connection",
    "validation",
}


@runtime_checkable
class ImportanceScorer(Protocol):
    """Protocol for pluggable importance scoring strategies.

    Implementations return a float in [0.0, 1.0] representing the
    importance of an episode (0 = trivial, 1 = critical).
    """

    def score(self, episode: EpisodicMemory) -> float:
        """Return importance score for the given episode.

        Args:
            episode: The episode to score.

        Returns:
            Importance score in [0.0, 1.0].
        """
        ...


class HeuristicScorer:
    """Heuristic importance scorer based on outcome and error type.

    Mirrors the inline logic in EpisodicMemoryStore.record_episode() and
    normalizes the 1-10 scale to [0.0, 1.0].

    Episodes with FAILURE or TIMEOUT outcome score higher (0.6-1.0),
    PARTIAL scores mid-range (0.4-0.8), and SUCCESS scores lower (0.2-0.5).
    Known error types (timeout, rate_limit, etc.) add a bonus.
    """

    def score(self, episode: EpisodicMemory) -> float:
        """Compute normalized [0.0, 1.0] importance from outcome and error type.

        Args:
            episode: The episode to score.

        Returns:
            Importance score in [0.0, 1.0].
        """
        if episode.outcome in (EpisodeOutcome.FAILURE, EpisodeOutcome.TIMEOUT):
            base = 7
        elif episode.outcome == EpisodeOutcome.PARTIAL:
            base = 5
        else:
            base = 3

        if (
            episode.error_type
            and episode.error_type.lower() in _KNOWN_ERROR_TYPES
        ):
            base = min(base + 2, 10)

        return base / 10.0


class ValueScorer(BaseModel):
    """Heuristic interaction value scorer ported from AgentCoreMemory.

    Assesses the value of an interaction using weighted signals:
    - Outcome (SUCCESS adds value, FAILURE subtracts)
    - Tool usage (non-conversational interactions add value)
    - Query length (longer queries are typically more substantive)
    - Response length (longer outcome_details indicate richer interactions)
    - Implicit feedback from outcome details

    All weights are configurable. Score is clamped to [0.0, 1.0].
    Scores below ``threshold`` are considered low-value.

    Args:
        outcome_weight: Weight for positive outcome signal. Default 0.3.
        tool_usage_weight: Weight for tool usage signal. Default 0.2.
        query_length_weight: Weight for substantive situation length. Default 0.1.
        response_length_weight: Weight for outcome_details length. Default 0.2.
        feedback_weight: Weight for explicit positive/negative signals. Default 0.3.
        threshold: Minimum score to be considered valuable. Default 0.4.
    """

    outcome_weight: float = Field(default=0.3, ge=0.0, le=1.0)
    tool_usage_weight: float = Field(default=0.2, ge=0.0, le=1.0)
    query_length_weight: float = Field(default=0.1, ge=0.0, le=1.0)
    response_length_weight: float = Field(default=0.2, ge=0.0, le=1.0)
    feedback_weight: float = Field(default=0.3, ge=0.0, le=1.0)
    threshold: float = Field(default=0.4, ge=0.0, le=1.0)

    def score(self, episode: EpisodicMemory) -> float:
        """Compute interaction value score for the given episode.

        Args:
            episode: The episode to score.

        Returns:
            Value score in [0.0, 1.0].
        """
        total = 0.0

        # Outcome signal: SUCCESS is positive, FAILURE is slightly negative
        if episode.outcome == EpisodeOutcome.SUCCESS:
            total += self.outcome_weight
        elif episode.outcome == EpisodeOutcome.FAILURE:
            total -= self.outcome_weight * 0.5

        # Tool usage signal: non-conversational episodes are more valuable
        if episode.related_tools:
            total += self.tool_usage_weight

        # Query length signal: substantive situations (> 5 words) add value
        situation_words = len(episode.situation.split())
        if situation_words > 5:
            total += self.query_length_weight

        # Response length signal: detailed outcome_details add value
        if episode.outcome_details and len(episode.outcome_details) > 100:
            total += self.response_length_weight

        # Implicit feedback from lesson_learned (positive signal)
        if episode.lesson_learned:
            total += self.feedback_weight * 0.5

        return max(0.0, min(total, 1.0))

    def is_valuable(self, episode: EpisodicMemory) -> bool:
        """Return True if the episode's value score meets the threshold.

        Args:
            episode: The episode to evaluate.

        Returns:
            True if score >= threshold.
        """
        return self.score(episode) >= self.threshold
