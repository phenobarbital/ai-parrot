"""Z.ai (GLM) dispatch profile for the dev-loop flow."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from parrot.flows.dev_loop.models.llm import LLMCodeDispatchProfile


class ZaiCodeDispatchProfile(LLMCodeDispatchProfile):
    """Declarative profile consumed by ``ZaiCodeDispatcher.dispatch()``.

    Subclasses ``LLMCodeDispatchProfile`` so it flows through the inherited
    dispatch loop unchanged; Z.ai-native fields (``enable_thinking``,
    ``reasoning_effort``) are consumed by
    ``ZaiCodeDispatcher._completion_args`` instead of the Nvidia-style
    ``extra_body.chat_template_kwargs`` block used by the base class.
    """

    model: str = Field(
        default="glm-5.2",
        description="Convenience field; kept in sync with ``llm`` (zai:<model>).",
    )
    llm: str = "zai:glm-5.2"
    enable_thinking: bool = Field(
        default=True,
        description="Z.ai native thinking mode (thinking={'type': 'enabled'|'disabled'}).",
    )
    reasoning_effort: Literal[
        "max", "xhigh", "high", "medium", "low", "minimal", "none"
    ] = Field(
        default="max",
        description=(
            "Z.ai reasoning_effort. GLM-5.2-only, effective only when "
            "thinking is enabled."
        ),
    )
    max_tokens: int = Field(default=8192, ge=256, le=131072)

    @model_validator(mode="after")
    def _sync_llm_with_model(self) -> "ZaiCodeDispatchProfile":
        """Derive ``llm`` from ``model`` unless the caller set ``llm`` explicitly."""
        if "llm" not in self.model_fields_set:
            self.llm = f"zai:{self.model}"
        return self

