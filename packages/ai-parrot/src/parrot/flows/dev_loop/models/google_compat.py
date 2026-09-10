"""Dispatch profile for the `google-compat` seat (FEAT-549, spec §3 M3). Template: models/nova.py:93."""
from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from parrot.flows.dev_loop.models.llm import LLMCodeDispatchProfile  # verified: models/llm.py:10


class GoogleCompatCodeDispatchProfile(LLMCodeDispatchProfile):
    """Gemini via Google's OpenAI-compatible endpoint.

    ``enable_thinking`` MUST stay False: ``extra_body.chat_template_kwargs``
    is silently ignored by Google's layer — use ``reasoning_effort`` instead.
    """

    model: str = Field(default="gemini-3.5-flash", description="Gemini model id served by the compat endpoint.")
    llm: str = "google-compat:gemini-3.5-flash"
    reasoning_effort: Literal["none", "low", "medium", "high"] = Field(
        default="none",
        description="Forwarded as the OpenAI `reasoning_effort` kwarg; 'none' disables thinking.",
    )

    @model_validator(mode="after")
    def _sync_llm_with_model(self) -> "GoogleCompatCodeDispatchProfile":
        """Derive ``llm`` from ``model`` unless the caller set ``llm`` explicitly (nova.py precedent)."""
        if "llm" not in self.model_fields_set:
            self.llm = f"google-compat:{self.model}"
        return self
