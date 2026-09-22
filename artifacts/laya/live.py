"""Live-mode guards for the Laya evaluation: preflight, logical-call cap, model evidence (spec §2)."""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict

from parrot.models.responses import AIMessage  # verified: packages/ai-parrot/src/parrot/models/responses.py:75

from artifacts.laya.models import EvaluationConfig

API_KEY_ENV = "ANTHROPIC_API_KEY"  # verified: client.py:173 — the client itself reads this name


class LivePreflightError(ValueError):
    """Live configuration incomplete; ``error_code`` is always ``live_config_missing``."""

    error_code = "live_config_missing"


def preflight_live(config: EvaluationConfig, env: Mapping[str, str] | None = None) -> None:
    """Reject a live run before any request when model IDs, cap or API key are missing (spec §2).

    Raises:
        LivePreflightError: listing every missing input at once.
    """
    if not config.live:
        return
    env = os.environ if env is None else env
    missing: list[str] = []
    if not config.primary_api_model:
        missing.append("--primary-api-model")
    if not config.cheap_api_model:
        missing.append("--cheap-api-model")
    if config.max_live_calls <= 0:
        missing.append("--max-live-calls (> 0)")
    if not env.get(API_KEY_ENV):
        missing.append(f"{API_KEY_ENV} (environment)")
    if missing:
        raise LivePreflightError(f"live mode requires: {', '.join(missing)}")


class LiveCallBudget:
    """Cap on logical ``Agent.ask`` calls across both arms, failed calls included (spec §2)."""

    NOT_A_MONEY_CAP = "logical-call cap: not an HTTP-attempt or money cap (client retries/fallback may add requests)"

    def __init__(self, max_calls: int) -> None:
        self.max_calls = max_calls
        self.used = 0

    @property
    def remaining(self) -> int:
        return self.max_calls - self.used

    def reserve(self) -> bool:
        """Reserve one slot BEFORE dispatch; False when exhausted (-> ``call_cap_reached``)."""
        if self.remaining <= 0:
            return False
        self.used += 1
        return True

    def reserve_pair(self) -> bool:
        """Reserve two slots atomically; a pair never starts with one slot left (spec §2)."""
        if self.remaining < 2:
            return False
        self.used += 2
        return True


class ModelEvidence(BaseModel):
    """What we can prove about which model answered (spec §2 'Record requested, selected, reported and provider-returned')."""

    model_config = ConfigDict(extra="forbid")
    requested_model: str | None
    reported_model: str | None  # AIMessage.model — NOT proof (factory echoes the request)
    actual_model: str | None  # raw_response["model"] when available
    verified: bool
    mismatch: bool
    fallback_metadata: dict[str, Any] | None
    usage: dict[str, Any] | None
    error_code: str | None  # "model_unverified" when actual_model is None


def extract_model_evidence(message: AIMessage, requested_model: str | None) -> ModelEvidence:
    """Prefer the raw provider model; keep fallback metadata separate; never substitute or 'correct' anything."""
    raw = message.raw_response if isinstance(message.raw_response, dict) else None
    actual = raw.get("model") if raw and isinstance(raw.get("model"), str) else None
    meta = message.metadata or {}
    fallback = {k: meta[k] for k in ("used_fallback_model", "original_model", "fallback_model") if k in meta} or None
    usage = message.usage.model_dump() if message.usage else None
    return ModelEvidence(
        requested_model=requested_model,
        reported_model=message.model,
        actual_model=actual,
        verified=actual is not None,
        mismatch=bool(actual and requested_model and actual != requested_model),
        fallback_metadata=fallback,
        usage=usage,
        error_code=None if actual else "model_unverified",
    )
