"""Follow-up suggestion chip models (FEAT-752)."""
from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .outputs import OutputMode


class SuggestionKind(str, Enum):
    """What the chip does when clicked."""

    FOLLOWUP = "followup"
    PRESENTATION = "presentation"
    ACTION = "action"


class SuggestionSource(str, Enum):
    """Who produced the chip."""

    LLM = "llm"
    SKILL = "skill"
    PROVIDER = "provider"


ALLOWED_ACTIONS: frozenset[str] = frozenset({"explain"})


class Suggestion(BaseModel):
    """One follow-up chip. Wire shape is identical for every channel (FEAT-752)."""

    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    label: str = Field(min_length=1, max_length=40, description="Chip text (<= 40 chars)")
    prompt: str = Field(min_length=1, max_length=500, description="Text sent through the normal chat path on click")
    output_mode: Optional[OutputMode] = Field(default=None, description="Explicit mode for the click turn, if any")
    kind: SuggestionKind = SuggestionKind.FOLLOWUP
    source: SuggestionSource = SuggestionSource.PROVIDER
    action: Optional[str] = Field(default=None, description='Client action id; v1 allows only "explain" (kind=action)')

    @field_validator("label", "prompt", mode="before")
    @classmethod
    def _strip_nonempty(cls, v: str) -> str:
        """Collapse internal whitespace, strip, and reject blank values."""
        if not isinstance(v, str):
            return v
        value = " ".join(v.split())
        if not value:
            raise ValueError("must not be blank")
        return value

    @model_validator(mode="after")
    def _action_consistency(self) -> "Suggestion":
        """Reject invalid action and kind combinations."""
        if self.kind == SuggestionKind.ACTION.value:
            if self.action is None:
                raise ValueError("action is required when kind is action")
            if self.action not in ALLOWED_ACTIONS:
                raise ValueError("action is not allowed")
        elif self.action is not None:
            raise ValueError("action requires kind=action")
        return self


class SuggestionBatch(BaseModel):
    """Structured output requested from the lightweight model (LLM lane)."""

    suggestions: List[Suggestion] = Field(default_factory=list, max_length=4)
