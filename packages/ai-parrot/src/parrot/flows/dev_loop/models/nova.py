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

import logging
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from parrot.flows.dev_loop.models.llm import LLMCodeDispatchProfile

#: Default Bedrock Converse model for BOTH no-tools Nova seats (adversarial
#: review + mechanical PR summary).
#:
#: Amazon's own Nova model, not a ``us.anthropic.*`` id: Bedrock gates every
#: Anthropic model behind a per-account "Anthropic use case details" form, so
#: an account with a valid Bedrock API key still gets
#: ``ResourceNotFoundException`` on the first call until an operator fills
#: that form in. A *Nova* backend defaulting to a model that needs a separate
#: Anthropic entitlement is a footgun; native Nova ids need no form.
#:
#: The ``us.`` geo prefix is REQUIRED — Nova 2 Lite has no in-region access
#: (spec ``novaclient-amazon-aws`` §"Verified AWS Facts"). Nova Premier is
#: deliberately not used here: Legacy on Bedrock, EOL 2026-09-14.
#:
#: Kept byte-identical to ``conf.DEV_LOOP_NOVA_REVIEW_MODEL`` /
#: ``conf.DEV_LOOP_NOVA_MECHANICAL_MODEL``'s fallbacks — the ``models``
#: package deliberately does not import ``parrot.conf`` (no module under
#: ``flows/dev_loop/models/`` does), so the two literals are pinned equal by
#: ``test_nova_profiles.py`` instead of shared by import.
NOVA_DEFAULT_CONVERSE_MODEL: str = "us.amazon.nova-2-lite-v1:0"

# Verified per-model output-token ceilings (AWS Bedrock model cards,
# 2026-08-03, FEAT-405 Module 4). Models absent from this map are passed
# through unclamped by ``effective_max_tokens()`` — "unknown" is not
# treated as "wrong".
MODEL_MAX_OUTPUT_TOKENS: dict[str, int] = {
    "minimax.minimax-m2.5": 8_192,
    "moonshotai.kimi-k2.5": 16_384,
    "zai.glm-5": 131_072,
    "anthropic.claude-opus-5": 131_072,
}


def effective_max_tokens(
    model: str, requested: int, logger: logging.Logger
) -> int:
    """Clamp ``requested`` to ``model``'s verified output ceiling.

    Clamps — never raises (spec Q5): a profile requesting more tokens than
    a model can return must still run, at the model's actual ceiling,
    rather than fail mid-dispatch against Bedrock.

    Args:
        model: The bare Bedrock model id (no ``nova:`` provider prefix, no
            geo/global inference-profile prefix).
        requested: The profile's requested ``max_tokens``.
        logger: Logger used to warn when a clamp takes effect. Silent on
            the happy path (requested within the ceiling, or the model is
            absent from :data:`MODEL_MAX_OUTPUT_TOKENS`).

    Returns:
        ``requested`` unchanged when it fits (or the model is unmapped);
        otherwise the model's ceiling.
    """
    ceiling = MODEL_MAX_OUTPUT_TOKENS.get(model)
    if ceiling is None or requested <= ceiling:
        return requested
    logger.warning(
        "Model %s caps output at %d tokens; clamping requested %d to %d.",
        model,
        ceiling,
        requested,
        ceiling,
    )
    return ceiling


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
        default=NOVA_DEFAULT_CONVERSE_MODEL,
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
        default=NOVA_DEFAULT_CONVERSE_MODEL,
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
