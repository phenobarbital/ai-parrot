"""Opt-in LLM option refiner (FEAT-649, Module 4) — results always go through confirm_request."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any, Protocol

from pydantic import BaseModel, Field

from .models import OptionMatch

if TYPE_CHECKING:
    from parrot.clients.base import AbstractClient


class RefinedOption(BaseModel):
    """Structured-output schema the LLM must return."""

    value: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class OptionRefiner(Protocol):
    """Refine an unmatched transcript to one option (never auto-accepted)."""

    async def refine(self, transcript: str, options: list[dict], *, locale: str) -> OptionMatch | None:
        """Return a suggested match or ``None``."""
        ...


class LLMOptionRefiner:
    """`OptionRefiner` backed by ``AbstractClient.ask(structured_output=...)``."""

    def __init__(self, client: "AbstractClient", *, timeout_s: float = 5.0) -> None:
        self.client = client
        self.timeout_s = timeout_s
        self.logger = logging.getLogger(__name__)

    async def refine(self, transcript: str, options: list[dict], *, locale: str) -> OptionMatch | None:
        """Structured output {value, confidence}; result ALWAYS surfaces as confirm_request (method="llm")."""
        enabled = [o for o in options if not o.get("disabled", False)]
        listing = json.dumps([{"value": o["value"], "label": o.get("label")} for o in enabled], ensure_ascii=False)
        prompt = (
            f"Locale: {locale}. A user answered a multiple-choice question by voice.\n"
            f"Options (JSON): {listing}\nTranscript: {transcript!r}\n"
            "Return the option value the user most likely meant, or null if none fits, with a confidence in [0, 1]."
        )
        try:
            response: Any = await asyncio.wait_for(
                self.client.ask(prompt, structured_output=RefinedOption), timeout=self.timeout_s
            )
        except Exception as exc:  # noqa: BLE001 — refiner is best-effort; any failure -> no suggestion
            self.logger.warning("LLMOptionRefiner failed: %s", type(exc).__name__)
            return None
        try:
            result = getattr(response, "structured_output", None)
            if isinstance(result, dict):
                result = RefinedOption(**result)
            if not isinstance(result, RefinedOption) or result.value is None:
                return None
            for opt in enabled:
                if str(opt["value"]) == result.value:
                    return OptionMatch(
                        value=opt["value"],
                        label=str(opt.get("label", opt["value"])),
                        method="llm",
                        score=max(0.0, min(1.0, float(result.confidence))),
                    )
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("LLMOptionRefiner bad output: %s", type(exc).__name__)
        return None
