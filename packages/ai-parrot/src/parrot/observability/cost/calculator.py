"""CostCalculator — stateless USD cost estimation for LLM API calls.

FEAT-177 TASK-1232.

Pricing tables are loaded from bundled JSON files once at first
``CostCalculator()`` construction and cached at module level. No filesystem
I/O occurs in the hot path (``cost_usd``).

Override path: ``ObservabilityConfig.pricing_override_path`` or
``PARROT_PRICING_PATH`` env var (resolved by ``setup_telemetry``).

Spec §3 Module 5, §8 D5 (bundled JSON, 90-day stale warning).
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel

logger = logging.getLogger("parrot.observability.cost")

# ---------------------------------------------------------------------------
# Module-level pricing cache
# ---------------------------------------------------------------------------

# Loaded on first CostCalculator construction: dict[provider, dict[model, entry]]
_LOADED: Optional[dict[str, dict[str, dict]]] = None
# Metadata per provider: {provider: {"last_updated": date, "source": str}}
_META: dict[str, dict] = {}
_BUNDLED_DIR = Path(__file__).parent / "pricing"

# Guards _LOADED mutations: both the initial load and any _apply_override calls.
# Prevents a race when multiple threads construct CostCalculator concurrently
# with different override_path values.
_PRICING_LOCK = threading.Lock()


class PricedCost(BaseModel):
    """One computed cost plus the price revision that produced it (FEAT-783 S9)."""

    usd: Optional[float] = None
    price_revision: Optional[str] = None
    valid_from: Optional[str] = None
    priced: bool = False


def _select_entry(value: "dict | list[dict]", at: Optional[date]) -> Optional[dict]:
    """Return the price entry in force at *at* (None = latest).

    A bare dict is valid forever. Missing ``valid_from`` values on dated lists
    represent the earliest possible entry.
    """
    if isinstance(value, dict):
        return value

    selected: Optional[dict] = None
    selected_from = date.min
    for entry in value:
        valid_from_value = entry.get("valid_from")
        entry_from = date.fromisoformat(valid_from_value) if valid_from_value else date.min
        if at is not None and entry_from > at:
            continue
        if selected is None or entry_from > selected_from:
            selected = entry
            selected_from = entry_from
    return selected


def _reset_pricing_cache_for_tests() -> None:
    """Test-only: reset the module-level cache so a fresh load can be attempted."""
    global _LOADED, _META
    _LOADED = None
    _META = {}


def _load_bundled_pricing() -> dict[str, dict[str, dict]]:
    """Load all bundled JSON files from the ``pricing/`` directory.

    Returns:
        Dict[provider_key, Dict[model_id, pricing_entry]] where provider_key
        is the filename stem (e.g. ``"openai"`` for ``openai.json``).
    """
    result: dict[str, dict[str, dict]] = {}
    for p in _BUNDLED_DIR.glob("*.json"):
        try:
            raw_text = p.read_text(encoding="utf-8")
            raw = json.loads(raw_text)
            provider = p.stem
            result[provider] = raw.get("models", {})
            meta = raw.get("pricing", {})
            _META[provider] = {
                **meta,
                "revision": f"{provider}@{hashlib.sha256(raw_text.encode('utf-8')).hexdigest()[:12]}",
            }
        except Exception:
            logger.exception("Failed to load bundled pricing file %s", p)
    return result


def _apply_override(
    base: dict[str, dict[str, dict]],
    override_path: str,
) -> dict[str, dict[str, dict]]:
    """Deep-merge override pricing files over bundled pricing.

    For each ``<provider>.json`` found in *override_path*, the ``models``
    dict is merged per-model: override wins for models present in the
    override file; bundled values remain for models absent from the override.

    Args:
        base: The bundled pricing dict (mutated in-place and returned).
        override_path: Directory path containing override JSON files.

    Returns:
        The mutated *base* dict.
    """
    override_dir = Path(override_path)
    if not override_dir.is_dir():
        logger.warning(
            "CostCalculator: override_path=%r is not a directory; ignoring.", override_path
        )
        return base
    for p in override_dir.glob("*.json"):
        try:
            raw_text = p.read_text(encoding="utf-8")
            raw = json.loads(raw_text)
            provider = p.stem
            models = raw.get("models", {})
            if provider not in base:
                base[provider] = {}
            base[provider].update(models)  # model-level override wins
            metadata = raw.get("pricing", _META.get(provider, {}))
            _META[provider] = {
                **metadata,
                "revision": f"{provider}@{hashlib.sha256(raw_text.encode('utf-8')).hexdigest()[:12]}",
            }
        except Exception:
            logger.exception("Failed to load override pricing file %s", p)
    return base


def _check_staleness(today: date, stale_warn_days: int) -> None:
    """Emit a WARN for each provider whose pricing is older than *stale_warn_days*.

    Args:
        today: Reference date (injectable for tests).
        stale_warn_days: Number of days before a WARN is emitted.
    """
    threshold = today - timedelta(days=stale_warn_days)
    for provider, meta in _META.items():
        last_updated_str = meta.get("last_updated", "")
        if not last_updated_str:
            continue
        try:
            last_updated = date.fromisoformat(last_updated_str)
        except ValueError:
            continue
        if last_updated < threshold:
            logger.warning(
                "CostCalculator: pricing for provider=%r is stale "
                "(last_updated=%s, older than %d days). "
                "Update the bundled JSON or set PARROT_PRICING_PATH.",
                provider,
                last_updated_str,
                stale_warn_days,
            )


class CostCalculator:
    """Stateless USD cost calculator using bundled or overridden pricing tables.

    Pricing tables are loaded once at module level on first construction.
    All subsequent constructions reuse the cached data — no filesystem I/O.

    Args:
        override_path: Optional directory containing ``<provider>.json`` files
            that override bundled pricing via deep-merge (per-model granularity).
        stale_warn_days: Emit a WARN at boot for any provider file older than
            this many days. Default: 90.
        today: Reference date for staleness check. Defaults to ``date.today()``.
            Pass explicitly in tests to avoid time-dependent failures.
    """

    def __init__(
        self,
        *,
        override_path: Optional[str] = None,
        stale_warn_days: int = 90,
        today: Optional[date] = None,
    ) -> None:
        """Initialize a CostCalculator, loading pricing tables on first call.

        Pricing tables are loaded once at module level and cached. Subsequent
        constructions reuse the cached data.

        Note:
            Concurrent construction with different ``override_path`` values will
            serialize on ``_PRICING_LOCK``. The last override applied wins for
            any model keys present in multiple override files.

        Args:
            override_path: Optional directory containing ``<provider>.json`` files
                that override bundled pricing via deep-merge (per-model granularity).
            stale_warn_days: Emit a WARN at boot for any provider file older than
                this many days. Default: 90.
            today: Reference date for staleness check. Defaults to ``date.today()``.
                Pass explicitly in tests to avoid time-dependent failures.
        """
        global _LOADED
        with _PRICING_LOCK:
            if _LOADED is None:
                _LOADED = _load_bundled_pricing()
                if override_path:
                    _apply_override(_LOADED, override_path)
                _check_staleness(today or date.today(), stale_warn_days)
            elif override_path:
                # Cache was already populated; apply override on top of cached state.
                _apply_override(_LOADED, override_path)
                _check_staleness(today or date.today(), stale_warn_days)

        self._pricing = _LOADED
        self._warned_unknown: set[tuple[str, str]] = set()

    def cost_usd(
        self,
        *,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cached_input_tokens: int = 0,
        cache_creation_tokens: int = 0,
        at: Optional[date] = None,
    ) -> Optional[float]:
        """Compute USD cost for a single LLM API call.

        Args:
            provider: ``gen_ai.system`` value (e.g. ``"openai"``, ``"anthropic"``).
                For Google models use ``"gemini"`` (``google.json`` filename stem).
            model: Model identifier matching a key in the pricing JSON.
            input_tokens: Number of input tokens billed.
            output_tokens: Number of output tokens billed.
            cached_input_tokens: Number of cached input tokens (discount tier).
                Default ``0``.
            cache_creation_tokens: Number of cache-creation tokens, billed as
                an additive tier. They are never subtracted from input tokens.
            at: Date for selecting a dated price entry. Defaults to the latest.

        Returns:
            USD cost as a float rounded to 6 decimal places, or ``None`` if
            the ``(provider, model)`` pair is not found in any pricing table.
        """
        return self.price_call(
            provider=provider,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_input_tokens=cached_input_tokens,
            cache_creation_tokens=cache_creation_tokens,
            at=at,
        ).usd

    def price_call(self, **kwargs: Any) -> PricedCost:
        """Compute a cost together with its pricing revision and effective date."""
        provider = kwargs["provider"]
        model = kwargs["model"]
        file_key = "google" if provider == "gemini" else provider
        provider_pricing = self._pricing.get(file_key)
        price_value = provider_pricing.get(model) if provider_pricing is not None else None
        price = _select_entry(price_value, kwargs.get("at")) if price_value is not None else None
        if price is None:
            self._warn_unknown(provider, model)
            return PricedCost()

        input_per_1m: float = price["input_per_1m"]
        output_per_1m: float = price["output_per_1m"]
        cached_per_1m: float = price.get("cached_input_per_1m", input_per_1m)
        cache_creation_per_1m: float = price.get("cache_creation_per_1m", input_per_1m)
        input_tokens = kwargs["input_tokens"]
        output_tokens = kwargs["output_tokens"]
        cached_input_tokens = kwargs.get("cached_input_tokens", 0)
        cache_creation_tokens = kwargs.get("cache_creation_tokens", 0)

        # Standard input cost (non-cached portion)
        non_cached = max(0, input_tokens - cached_input_tokens)
        input_cost = non_cached * input_per_1m / 1_000_000
        output_cost = output_tokens * output_per_1m / 1_000_000
        cached_cost = cached_input_tokens * cached_per_1m / 1_000_000

        cache_creation_cost = cache_creation_tokens * cache_creation_per_1m / 1_000_000
        total = input_cost + output_cost + cached_cost + cache_creation_cost
        revision, valid_from = self.revision_for(provider, model, kwargs.get("at"))
        return PricedCost(usd=round(total, 6), price_revision=revision, valid_from=valid_from, priced=True)

    def revision_for(
        self, provider: str, model: str, at: Optional[date] = None
    ) -> tuple[Optional[str], Optional[str]]:
        """Return the revision and date for a price entry without computing cost."""
        file_key = "google" if provider == "gemini" else provider
        provider_pricing = self._pricing.get(file_key)
        price_value = provider_pricing.get(model) if provider_pricing is not None else None
        price = _select_entry(price_value, at) if price_value is not None else None
        if price is None:
            return None, None
        return _META.get(file_key, {}).get("revision"), price.get("valid_from")

    def _warn_unknown(self, provider: str, model: str) -> None:
        """Log a one-time WARN for an unknown (provider, model) pair.

        Args:
            provider: Provider key.
            model: Model identifier.
        """
        key = (provider, model)
        if key not in self._warned_unknown:
            self._warned_unknown.add(key)
            logger.warning(
                "CostCalculator: no pricing for provider=%r model=%r — returning None. "
                "Add a bundled JSON entry or set PARROT_PRICING_PATH.",
                provider,
                model,
            )
