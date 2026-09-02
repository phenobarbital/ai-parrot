"""Gemini dispatch profile for the dev-loop flow (FEAT-129).

Development seat only. The review profile that used to live here was
removed with ``GeminiCodeReviewDispatcher`` — Gemini is banned from every
reviewer role (see ``models/base.py``'s ``JudgeBackend``).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class GeminiCodeDispatchProfile(BaseModel):
    """Declarative profile consumed by ``GeminiCodeDispatcher.dispatch()``.

    The Gemini integration is designed to run the Google Gemini Agent
    supporting tool calling and structured output extraction.
    """

    subagent: Literal["sdd-worker"] = "sdd-worker"
    model: str = "auto"
    sandbox: bool = Field(
        default=True,
        description="Whether to run the gemini session in a sandbox.",
    )
    approval_mode: Literal["default", "auto_edit", "yolo", "plan"] = "auto_edit"
    timeout_seconds: int = Field(default=1800, ge=60, le=7200)
