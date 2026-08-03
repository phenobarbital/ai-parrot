"""Moonshot (Kimi) dispatch profile for the dev-loop flow."""

from __future__ import annotations

from pydantic import Field, model_validator

from parrot.flows.dev_loop.models.llm import LLMCodeDispatchProfile


class MoonshotCodeDispatchProfile(LLMCodeDispatchProfile):
    """Declarative profile consumed by ``MoonshotCodeDispatcher.dispatch()``.

    Subclasses ``LLMCodeDispatchProfile`` so it flows through the inherited
    dispatch loop unchanged; Moonshot-native fields (``enable_thinking``,
    ``reasoning_effort``) are consumed by
    ``MoonshotCodeDispatcher._completion_args`` / ``_chat_completion``
    instead of the Nvidia-style ``extra_body.chat_template_kwargs`` block
    used by the base class.
    """

    model: str = Field(
        default="kimi-k3",
        description="Convenience field; kept in sync with ``llm`` (moonshot:<model>).",
    )
    llm: str = "moonshot:kimi-k3"
    enable_thinking: bool = Field(
        default=True,
        description=(
            "Moonshot thinking mode. Only kimi-k2.6 accepts an explicit "
            "thinking dict; kimi-k3 and the kimi-k2.7-code variants always "
            "reason server-side."
        ),
    )
    reasoning_effort: str = Field(
        default="max",
        description=(
            "Moonshot reasoning_effort (kimi-k3 only, injected via "
            "extra_body). Kimi-k3 always reasons; this tunes how hard."
        ),
    )
    max_tokens: int = Field(default=8192, ge=256, le=131072)

    @model_validator(mode="after")
    def _sync_llm_with_model(self) -> "MoonshotCodeDispatchProfile":
        """Derive ``llm`` from ``model`` unless the caller set ``llm`` explicitly."""
        if "llm" not in self.model_fields_set:
            self.llm = f"moonshot:{self.model}"
        return self
