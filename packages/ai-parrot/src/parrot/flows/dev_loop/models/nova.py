"""Nova (AWS Bedrock) dispatch profiles for the dev-loop flow (FEAT-405).

Three seats, three shapes:

- :class:`NovaCodeDispatchProfile` — the tool-using development seat,
  routed via the ``bedrock-mantle`` OpenAI-compatible endpoint. Subclasses
  :class:`~parrot.flows.dev_loop.models.llm.LLMCodeDispatchProfile` so it
  flows through the inherited ``LLMCodeDispatcher`` loop unchanged (mirrors
  :class:`~parrot.flows.dev_loop.models.moonshot.MoonshotCodeDispatchProfile`).
- :class:`NovaAdversarialReviewProfile` — read-only by construction: it
  exposes NO tool configuration, so the model can never be handed a tool
  regardless of how the dispatcher is wired.
- :class:`NovaMechanicalProfile` — short, no-tools text generation for PR
  summary enrichment (TASK-2092).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from parrot.flows.dev_loop.models.llm import LLMCodeDispatchProfile


class NovaCodeDispatchProfile(LLMCodeDispatchProfile):
    """Development-seat profile; routes via the ``bedrock-mantle`` endpoint.

    Subclasses :class:`LLMCodeDispatchProfile` so it flows through the
    inherited ``LLMCodeDispatcher`` tool loop unchanged; ``NovaCodeDispatcher``
    only overrides ``_completion_args``/``_chat_completion`` to target the
    OpenAI-compatible ``bedrock-mantle`` base URL.
    """

    model: str = Field(
        default="minimax.minimax-m2.5",
        description=(
            "Convenience field; kept in sync with ``llm`` (nova:<model>). "
            "Bedrock-native vendor id — never region-prefixed (no inference "
            "profile for MiniMax/Kimi/GLM)."
        ),
    )
    llm: str = "nova:minimax.minimax-m2.5"
    max_tokens: int = Field(
        default=4096,
        ge=256,
        le=32768,
        description=(
            "Requested output token budget. Clamped to the model's actual "
            "ceiling at dispatch time (TASK-2085's MODEL_MAX_OUTPUT_TOKENS) "
            "— this bound only constrains the profile's declared range."
        ),
    )

    @model_validator(mode="after")
    def _sync_llm_with_model(self) -> NovaCodeDispatchProfile:
        """Derive ``llm`` from ``model`` unless the caller set ``llm`` explicitly."""
        if "llm" not in self.model_fields_set:
            self.llm = f"nova:{self.model}"
        return self


class NovaAdversarialReviewProfile(BaseModel):
    """Read-only by construction: NO tools are ever passed to the model.

    Consumed by ``NovaAdversarialReviewDispatcher.build_review_profile()``.
    Deliberately a fresh ``BaseModel`` (not a subclass of
    ``LLMCodeDispatchProfile`` or ``CodexAdversarialReviewProfile``) so it
    structurally cannot carry ``tools``/``allowed_commands``/``sandbox``
    fields — the security property is that a tool configuration field does
    not exist on this class, not that enforcement code remembers to omit it.
    """

    model: str = Field(
        default="us.anthropic.claude-opus-5",
        description="Bedrock Converse model id for the adversarial reviewer.",
    )
    review_scope: Literal["uncommitted", "base", "commit"] = Field(
        default="uncommitted",
        description="Which diff the reviewer evaluates.",
    )
    review_base: str = Field(
        default="",
        description="Base ref/branch to diff against when review_scope == 'base'.",
    )
    review_commit: str = Field(
        default="",
        description="Commit SHA to review when review_scope == 'commit'.",
    )
    max_tokens: int = Field(
        default=8192,
        ge=256,
        le=131072,
        description="Output token budget for the review verdict.",
    )
    max_diff_chars: int = Field(
        default=200_000,
        ge=1000,
        description="Deterministic truncation bound for the diff sent to the model.",
    )


class NovaMechanicalProfile(BaseModel):
    """Short, no-tools text generation (PR summary section, TASK-2092).

    A fresh ``BaseModel`` for the same reason as
    :class:`NovaAdversarialReviewProfile` — no tool configuration field
    exists on this class.
    """

    model: str = Field(
        default="us.anthropic.claude-haiku-4-5-20251001-v1:0",
        description="Bedrock Converse model id for mechanical text generation.",
    )
    max_tokens: int = Field(
        default=1024,
        ge=64,
        le=8192,
        description="Output token budget — short PR-summary text only.",
    )
    timeout_seconds: int = Field(
        default=60,
        ge=5,
        le=600,
        description="Call timeout; any failure/timeout falls back to the deterministic template.",
    )
