"""Per-form public response controls (FEAT-730).

Typed ``FormSchema.public_access`` block: open/closed, close date, response cap,
one-response-per-key-question and the completion action. ``None`` on the form
means no policy (today's behaviour).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator, model_validator

from .types import LocalizedString

RejectionReason = Literal["form_closed", "response_limit_reached", "duplicate_response"]


class CompletionAction(BaseModel):
    """What the respondent sees after a successful submit."""

    mode: Literal["message", "redirect"] = "message"
    message: LocalizedString | None = None
    redirect_url: str | None = None

    @model_validator(mode="after")
    def _validate_redirect(self) -> CompletionAction:
        """mode == "redirect" requires an absolute https:// redirect_url with a host."""
        if self.redirect_url is not None:
            parsed = urlparse(self.redirect_url)
            if parsed.scheme != "https" or not parsed.netloc:
                raise ValueError(
                    f"redirect_url must be an absolute https:// URL with a host, got {self.redirect_url!r}"
                )
        elif self.mode == "redirect":
            raise ValueError("completion mode 'redirect' requires redirect_url")
        return self


class PublicAccessConfig(BaseModel):
    """Per-form response policy (``FormSchema.public_access``)."""

    accepting_responses: bool = True
    closes_at: datetime | None = None
    max_responses: int | None = Field(default=None, ge=1)
    unique_key_field: str | None = None
    completion: CompletionAction | None = None

    @field_validator("closes_at")
    @classmethod
    def _require_tz(cls, v: datetime | None) -> datetime | None:
        """Reject naive datetimes; normalize aware ones to UTC."""
        if v is None:
            return None
        if v.tzinfo is None or v.utcoffset() is None:
            raise ValueError("closes_at must be timezone-aware")
        return v.astimezone(timezone.utc)


class AvailabilityState(BaseModel):
    """Body of ``GET …/forms/{form_uid}/availability``."""

    accepting: bool
    reason: Literal["form_closed", "response_limit_reached"] | None = None
    completion: CompletionAction | None = None


def evaluate_open(config: PublicAccessConfig | None, *, now: datetime) -> Literal["form_closed"] | None:
    """Return ``"form_closed"`` when the form is closed at ``now``, else ``None``."""
    if config is None:
        return None
    if not config.accepting_responses:
        return "form_closed"
    if config.closes_at is not None and now >= config.closes_at:
        return "form_closed"
    return None


def normalize_key_value(value: Any) -> Any | None:
    """``None`` for blank/missing (None, "", whitespace, [], {}); strings returned stripped."""
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    if isinstance(value, (list, tuple, dict, set)) and not value:
        return None
    return value
