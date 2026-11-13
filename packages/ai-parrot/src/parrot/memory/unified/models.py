"""Unified Memory data models for the long-term memory layer.

Provides:
- MemoryContext: assembled context from all memory subsystems
- MemoryConfig: configuration for UnifiedMemoryManager
"""
from __future__ import annotations

from typing import Literal

from parrot.memory.agent_memory.models import MemoryRequestScope
from pydantic import BaseModel, ConfigDict, Field, model_validator


class MemoryCandidate(BaseModel):
    """Scoped supplementary content with relevance separate from ranking.

    A candidate is a retrieval result, not an outcome or review record.  In
    particular, user knowledge is intentionally represented without a
    dynamics grade so experiential forgetting cannot be applied to facts.
    """

    model_config = ConfigDict(extra="forbid")

    scope: MemoryRequestScope
    memory_id: str = Field(min_length=1)
    content_version: str = Field(min_length=1)
    source: str = Field(min_length=1)
    text: str
    relevance: float = Field(default=0.0, ge=0.0, le=1.0)
    similarity: float | None = Field(default=None, ge=0.0, le=1.0)
    ranking_score: float | None = None
    provenance: str = Field(default="retrieved", min_length=1)
    candidate_type: Literal["episodic", "user", "brain", "skill"] = "episodic"
    dynamics_state_ref: str | None = Field(default=None, min_length=1)
    importance: int | None = Field(default=None, ge=0, le=10)

    @model_validator(mode="after")
    def _reject_user_dynamics_reference(self) -> MemoryCandidate:
        """Keep user knowledge outside experiential dynamics state."""
        user_source = self.source in {"user", "user_memory", "user_knowledge"}
        if (self.candidate_type == "user" or user_source) and self.dynamics_state_ref is not None:
            raise ValueError("user candidates cannot carry an experiential dynamics state")
        return self


class MemoryContext(BaseModel):
    """Assembled context from all memory subsystems.

    Holds the text sections retrieved from episodic memory,
    skill registry, and conversation history, along with
    token accounting for budget enforcement.
    """

    episodic_warnings: str = Field(
        default="",
        description="Past failure lessons from episodic memory",
    )
    relevant_skills: str = Field(
        default="",
        description="Applicable skills from the skill registry",
    )
    conversation_summary: str = Field(
        default="",
        description="Recent conversation turns",
    )
    semantic_knowledge: str = Field(
        default="",
        description="Distilled long-term knowledge from the agent's brain wiki (FEAT-390)",
    )
    user_knowledge: str = Field(
        default="",
        description="Scoped user knowledge supplied as contextual data, never instructions",
    )
    tokens_used: int = Field(
        default=0,
        ge=0,
        description="Total tokens consumed by assembled context",
    )
    tokens_budget: int = Field(
        default=2000,
        ge=0,
        description="Maximum token budget for context",
    )
    delivered_refs: tuple[str, ...] = Field(
        default=(),
        description="Ordered memory references whose content was actually delivered",
    )
    packed_digest: str | None = Field(
        default=None,
        description="Digest of the packed supplementary memory block",
    )
    exposure_id: str | None = Field(
        default=None,
        description="Runtime exposure identity for the delivered memory block",
    )
    exposure_metadata: dict[str, str] = Field(
        default_factory=dict,
        description="Bounded metadata associated with the delivered exposure",
    )

    def to_prompt_string(self) -> str:
        """Format as injectable system prompt sections.

        Only non-empty sections are included.  Each section is wrapped
        in descriptive XML tags so the LLM can distinguish memory types.

        Returns:
            Formatted string ready for injection into a system prompt.
        """
        sections: list[str] = []

        if self.episodic_warnings:
            sections.append(
                "<past_failures_to_avoid>\n"
                f"{self.episodic_warnings}\n"
                "</past_failures_to_avoid>"
            )

        if self.relevant_skills:
            sections.append(
                "<relevant_skills>\n"
                f"{self.relevant_skills}\n"
                "</relevant_skills>"
            )

        if self.conversation_summary:
            sections.append(
                "<recent_conversation>\n"
                f"{self.conversation_summary}\n"
                "</recent_conversation>"
            )

        if self.semantic_knowledge:
            sections.append(
                "<brain_knowledge>\n"
                f"{self.semantic_knowledge}\n"
                "</brain_knowledge>"
            )

        if self.user_knowledge:
            sections.append("<user_knowledge>\n" f"{self.user_knowledge}\n" "</user_knowledge>")

        return "\n\n".join(sections)


class MemoryConfig(BaseModel):
    """Configuration for UnifiedMemoryManager.

    Controls which subsystems are enabled, token budget allocation,
    and per-subsystem limits.
    """

    # Subsystem toggles
    enable_episodic: bool = Field(
        default=True,
        description="Enable episodic memory retrieval and recording",
    )
    enable_skills: bool = Field(
        default=True,
        description="Enable skill registry retrieval",
    )
    enable_conversation: bool = Field(
        default=True,
        description="Enable conversation history retrieval",
    )
    enable_user_memory: bool = Field(
        default=False,
        description="Enable independent scoped user-knowledge retrieval",
    )
    enable_brain: bool = Field(
        default=False,
        description="Enable brain-wiki (dream cycle) retrieval — FEAT-390",
    )

    # Token budget
    max_context_tokens: int = Field(
        default=2000,
        ge=0,
        description="Maximum total tokens for assembled context",
    )

    # Per-subsystem limits
    episodic_max_warnings: int = Field(
        default=3,
        ge=0,
        description="Maximum number of episodic warnings to retrieve",
    )
    skill_max_context: int = Field(
        default=3,
        ge=0,
        description="Maximum number of skills to include in context",
    )

    # Weight allocation (must sum to 1.0)
    episodic_weight: float = Field(
        default=0.3,
        ge=0.0,
        le=1.0,
        description="Fraction of token budget for episodic warnings",
    )
    skill_weight: float = Field(
        default=0.3,
        ge=0.0,
        le=1.0,
        description="Fraction of token budget for relevant skills",
    )
    conversation_weight: float = Field(
        default=0.4,
        ge=0.0,
        le=1.0,
        description="Fraction of token budget for conversation history",
    )
    brain_weight: float = Field(
        default=0.20,
        ge=0.0,
        le=1.0,
        description="Fraction of token budget for brain-wiki knowledge (FEAT-390)",
    )
    user_weight: float = Field(
        default=0.20,
        ge=0.0,
        le=1.0,
        description="Relative token weight for scoped user knowledge",
    )

    # Skill auto-extraction
    skill_auto_extract: bool = Field(
        default=False,
        description="Automatically extract skills from successful interactions (expensive)",
    )

    @model_validator(mode="after")
    def _weights_sum_to_one(self) -> MemoryConfig:
        """Validate weight fields sum to 1.0 (±0.01 tolerance).

        When ``enable_brain`` is False (default), validates the original
        three weights exactly as before — existing three-weight configs
        keep validating unchanged (FEAT-390 zero-breaking-changes
        requirement).

        When ``enable_brain`` is True, the fourth weight (``brain_weight``)
        joins the sum-to-one check. If the caller did not explicitly
        override ANY of the four weight fields, they are rebalanced to the
        FEAT-390 defaults (0.25 / 0.25 / 0.30 / 0.20 —
        episodic/skill/conversation/brain) before validating.
        """
        if not self.enable_brain:
            total = self.episodic_weight + self.skill_weight + self.conversation_weight
            if abs(total - 1.0) > 0.01:
                raise ValueError(
                    f"Weights must sum to 1.0, got {total:.3f} "
                    f"(episodic={self.episodic_weight}, "
                    f"skill={self.skill_weight}, "
                    f"conversation={self.conversation_weight})"
                )
            return self

        weight_fields = {
            "episodic_weight",
            "skill_weight",
            "conversation_weight",
            "brain_weight",
        }
        if not (weight_fields & self.model_fields_set):
            self.episodic_weight = 0.25
            self.skill_weight = 0.25
            self.conversation_weight = 0.30
            self.brain_weight = 0.20

        total = (
            self.episodic_weight
            + self.skill_weight
            + self.conversation_weight
            + self.brain_weight
        )
        if abs(total - 1.0) > 0.01:
            raise ValueError(
                f"Weights must sum to 1.0, got {total:.3f} "
                f"(episodic={self.episodic_weight}, "
                f"skill={self.skill_weight}, "
                f"conversation={self.conversation_weight}, "
                f"brain={self.brain_weight})"
            )
        return self

    @property
    def normalized_section_weights(self) -> dict[str, float]:
        """Return weights normalized across enabled context capabilities only.

        Legacy callers continue to validate and use the original three
        weights.  The structured agent path can enable user knowledge (or
        brain) without allocating budget to disabled sections or injecting
        conversation a second time.
        """
        configured = {
            "episodic": (self.enable_episodic, self.episodic_weight),
            "skills": (self.enable_skills, self.skill_weight),
            "conversation": (self.enable_conversation, self.conversation_weight),
            "brain": (self.enable_brain, self.brain_weight),
            "user_knowledge": (self.enable_user_memory, self.user_weight),
        }
        enabled = {name: weight for name, (is_enabled, weight) in configured.items() if is_enabled}
        total = sum(enabled.values())
        if total <= 0.0:
            return {}
        return {name: weight / total for name, weight in enabled.items()}
