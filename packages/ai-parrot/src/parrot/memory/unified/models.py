"""Unified Memory data models for the long-term memory layer.

Provides:
- MemoryContext: assembled context from all memory subsystems
- MemoryConfig: configuration for UnifiedMemoryManager
"""
from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


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

    # Skill auto-extraction
    skill_auto_extract: bool = Field(
        default=False,
        description="Automatically extract skills from successful interactions (expensive)",
    )

    @model_validator(mode="after")
    def _weights_sum_to_one(self) -> MemoryConfig:
        """Validate that the three weight fields sum to 1.0 (±0.01 tolerance)."""
        total = self.episodic_weight + self.skill_weight + self.conversation_weight
        if abs(total - 1.0) > 0.01:
            raise ValueError(
                f"Weights must sum to 1.0, got {total:.3f} "
                f"(episodic={self.episodic_weight}, "
                f"skill={self.skill_weight}, "
                f"conversation={self.conversation_weight})"
            )
        return self
