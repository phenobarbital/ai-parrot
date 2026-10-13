"""Opt-in LLM post-processor for spoken typed answers (FEAT-653). Output is always re-normalized by the engine."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any, Protocol

from pydantic import BaseModel, Field

from ..core.types import FieldType

if TYPE_CHECKING:
    from parrot.clients.base import AbstractClient

_FORMATS: dict[FieldType, str] = {
    FieldType.EMAIL: "lowercase email address",
    FieldType.PHONE: "optional leading +, then digits only",
    FieldType.INTEGER: "integer",
    FieldType.NUMBER: "number with '.' as decimal separator",
    FieldType.DATE: "YYYY-MM-DD",
    FieldType.TIME: "HH:MM (24 hour)",
    FieldType.DATETIME: "YYYY-MM-DDTHH:MM (local time, no offset)",
}

_SYSTEM_PROMPT = (
    "A user answered one form field by voice. The input is a JSON object with the field type, its label, the "
    "locale, the user's timezone, today's date, the speech-recognition transcript, the candidate value produced by "
    "deterministic rules, and the required output format. The transcript may contain speech-recognition errors. "
    "Return the value the user most likely meant, written exactly in the required format, together with a "
    "confidence between 0 and 1. Resolve relative dates against today's date and the timezone. Never invent "
    "information that is not present in the transcript: when you cannot tell what the user meant, return a null "
    'value with a low confidence. Respond only with {"value": <string or null>, "confidence": <number>}.'
)


class RefinedValue(BaseModel):
    """Structured output the LLM must return."""

    value: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class ValueRefiner(Protocol):
    """Correct one spoken value; None when no suggestion."""

    async def refine(
        self,
        *,
        transcript: str,
        candidate: Any,
        field_type: FieldType,
        label: str,
        locale: str,
        today: str,
        timezone: str | None,
    ) -> RefinedValue | None:
        """Return a suggestion or ``None``."""
        ...


class LLMValueRefiner:
    """`ValueRefiner` over ``AbstractClient.ask(structured_output=RefinedValue)``; never raises, None on any failure."""

    def __init__(self, client: "AbstractClient") -> None:
        self.client = client
        self.logger = logging.getLogger(__name__)

    async def refine(
        self,
        *,
        transcript: str,
        candidate: Any,
        field_type: FieldType,
        label: str,
        locale: str,
        today: str,
        timezone: str | None,
    ) -> RefinedValue | None:
        """Ask the LLM; parse structured output; clamp confidence; None on failure or unparsable output."""
        payload = {
            "field_type": field_type.value,
            "label": label,
            "locale": locale,
            "timezone": timezone or "unknown",
            "today": today,
            "transcript": transcript,
            "rules_candidate": candidate if candidate is not None else "none",
            "required_format": _FORMATS.get(field_type, "text"),
        }
        try:
            response: Any = await self.client.ask(
                json.dumps(payload, ensure_ascii=False, default=str),
                system_prompt=_SYSTEM_PROMPT,
                structured_output=RefinedValue,
            )
        except Exception as exc:  # noqa: BLE001 — best effort; the adapter maps None to status "failed"
            self.logger.warning("LLMValueRefiner failed: %s", type(exc).__name__)
            return None
        return self._parse(response)

    def _parse(self, response: Any) -> RefinedValue | None:
        """Accept .structured_output / .output as RefinedValue, dict, JSON str/bytes or BaseModel."""
        for attr in ("structured_output", "output"):
            candidate = getattr(response, attr, None)
            if candidate is None:
                continue
            try:
                if isinstance(candidate, (str, bytes)):
                    candidate = json.loads(candidate)
                elif isinstance(candidate, BaseModel):
                    candidate = candidate.model_dump()
                if not isinstance(candidate, dict):
                    continue
                value = candidate.get("value")
                confidence = max(0.0, min(1.0, float(candidate.get("confidence") or 0.0)))
                if value is not None and not isinstance(value, str):
                    value = str(value)
                return RefinedValue(value=value, confidence=confidence)
            except (ValueError, TypeError) as exc:
                self.logger.warning("LLMValueRefiner bad output: %s", type(exc).__name__)
                continue
        return None
