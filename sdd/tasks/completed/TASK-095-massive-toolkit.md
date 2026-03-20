# TASK-095: MassiveToolkit Main Implementation

**Feature**: MassiveToolkit
**Spec**: `sdd/specs/massive-toolkit.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-092, TASK-093, TASK-094
**Assigned-to**: 4e94bc29-f6c5-41d0-8fd5-63e0967fc976

---

## Context

This task implements the main `MassiveToolkit` class with all 5 tool methods. It integrates the client wrapper and cache layer to provide a complete toolkit that agents can use for enrichment.

Reference: Spec Section 2 "New Public Interfaces" and Section 3 "Module 4"

---

## Scope

- Implement `MassiveToolkit` class extending `AbstractToolkit`
- Implement 5 tool methods:
  - `get_options_chain_enriched()` — Options with Greeks and IV
  - `get_short_interest()` — FINRA bi-monthly data with derived metrics
  - `get_short_volume()` — Daily short volume with ratios
  - `get_earnings_data()` — Benzinga earnings with revenue surprise
  - `get_analyst_ratings()` — Individual analyst actions + consensus
- Transform SDK responses to spec-defined output structures
- Implement graceful degradation (return fallback dict on error)
- Implement `enrich_ticker()` convenience method
- Implement `enrich_candidates()` with rate-limit-aware concurrency (Semaphore)
- Detect Benzinga availability and disable those tools if not in plan
- Update package `__init__.py` to export the toolkit

**NOT in scope**:
- WebSocket streaming (Phase 2)
- Economy endpoints

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/massive/toolkit.py` | CREATE | Main MassiveToolkit class |
| `parrot/tools/massive/__init__.py` | MODIFY | Export MassiveToolkit and models |

---

## Implementation Notes

### Pattern to Follow

```python
# Reference: parrot/tools/finnhub.py
from parrot.tools.toolkit import AbstractToolkit
from .client import MassiveClient
from .cache import MassiveCache
from .models import OptionsChainInput, ShortInterestInput, ...

class MassiveToolkit(AbstractToolkit):
    """Premium market data enrichment from Massive.com."""

    name = "massive_toolkit"

    def __init__(self, api_key: str | None = None, **kwargs):
        super().__init__(**kwargs)
        self.api_key = api_key or os.environ.get("MASSIVE_API_KEY")
        if not self.api_key:
            raise ValueError("MASSIVE_API_KEY required")
        self._client = MassiveClient(api_key=self.api_key)
        self._cache = MassiveCache()
        self._benzinga_available = None  # Lazy check

    async def get_options_chain_enriched(
        self,
        underlying: str,
        expiration_date_gte: str | None = None,
        expiration_date_lte: str | None = None,
        strike_price_gte: float | None = None,
        strike_price_lte: float | None = None,
        contract_type: str | None = None,
        limit: int = 250,
    ) -> dict:
        """
        Fetch options chain with pre-computed Greeks and IV.

        Returns market-calibrated Greeks (delta, gamma, theta, vega) from
        OPRA data. Use for portfolio exposure calculations and spread analysis.
        """
        try:
            # Check cache
            cached = await self._cache.get(
                "options_chain", underlying=underlying, ...
            )
            if cached:
                return {**cached, "cached": True}

            # Fetch from API
            chain = await self._client.list_snapshot_options_chain(
                underlying, params={...}
            )

            # Transform to output structure
            result = self._transform_options_chain(chain, underlying)

            # Cache and return
            await self._cache.set("options_chain", result, underlying=underlying, ...)
            return {**result, "cached": False}

        except Exception as e:
            self.logger.warning(f"Massive options chain failed: {e}")
            return {
                "underlying": underlying,
                "error": str(e),
                "fallback": "use_yfinance_options",
                "source": "massive_error",
            }
```

### Key Constraints

- **Graceful degradation**: Every tool method must catch exceptions and return `{"error": ..., "fallback": ...}`
- **Cache integration**: Check cache before API call, cache successful results
- **Derived metrics**: Calculate trend, change_pct, etc. from raw data
- **Rate-limit-aware batch**: `enrich_candidates()` must use `asyncio.Semaphore(max_concurrent=3)`
- **Benzinga detection**: First call to Benzinga endpoint should detect if available; if 403/plan error, set flag and skip future calls

### Output Structures (from spec)

**Options Chain:**
```python
{
    "underlying": "AAPL",
    "underlying_price": 185.42,
    "timestamp": "2026-03-02T15:30:00Z",
    "contracts_count": 147,
    "contracts": [
        {
            "ticker": "O:AAPL250321C00185000",
            "strike": 185.0,
            "expiration": "2025-03-21",
            "contract_type": "call",
            "greeks": {"delta": 0.512, "gamma": 0.031, "theta": -0.145, "vega": 0.287},
            "implied_volatility": 0.285,
            "open_interest": 12450,
            "volume": 3200,
            "bid": 4.85,
            "ask": 5.10,
            "midpoint": 4.975,
            "break_even_price": 189.95,
        }
    ],
    "source": "massive",
}
```

**Short Interest:**
```python
{
    "symbol": "GME",
    "latest": {"settlement_date": "...", "short_interest": 15234567, "days_to_cover": 3.34},
    "history": [...],
    "derived": {
        "short_interest_change_pct": 2.31,
        "trend": "increasing",  # increasing/decreasing/stable
        "days_to_cover_zscore": 1.85,
    },
    "source": "massive",
}
```

### References in Codebase

- `parrot/tools/finnhub.py` — Similar financial toolkit pattern
- `parrot/tools/toolkit.py` — `AbstractToolkit` base class
- `parrot/tools/alpaca/` — Another complex financial toolkit

---

## Acceptance Criteria

- [ ] `MassiveToolkit` class extends `AbstractToolkit`
- [ ] All 5 tool methods implemented with correct output structures
- [ ] Greeks included in options chain output (delta, gamma, theta, vega)
- [ ] Derived metrics calculated (trend, change_pct, zscore)
- [ ] Cache integration working (check, set with endpoint-specific TTL)
- [ ] Graceful degradation returns fallback dict on any error
- [ ] `enrich_ticker()` fetches all endpoints in parallel
- [ ] `enrich_candidates()` respects rate limit via Semaphore
- [ ] Benzinga endpoints disabled gracefully if not in plan
- [ ] No linting errors: `ruff check parrot/tools/massive/`
- [ ] Importable: `from parrot.tools.massive import MassiveToolkit`

---

## Test Specification

```python
# tests/test_massive_toolkit.py
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from parrot.tools.massive import MassiveToolkit


@pytest.fixture
def mock_client():
    """Mock MassiveClient."""
    with patch("parrot.tools.massive.toolkit.MassiveClient") as mock:
        client = MagicMock()
        client.list_snapshot_options_chain = AsyncMock(return_value=[
            MagicMock(
                ticker="O:AAPL250321C00185000",
                strike_price=185.0,
                greeks=MagicMock(delta=0.512, gamma=0.031, theta=-0.145, vega=0.287),
                implied_volatility=0.285,
            )
        ])
        mock.return_value = client
        yield client


class TestMassiveToolkit:
    def test_init_requires_api_key(self):
        """Raises without API key."""
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(ValueError, match="MASSIVE_API_KEY"):
                MassiveToolkit()

    @pytest.mark.asyncio
    async def test_options_chain_returns_greeks(self, mock_client):
        """Options chain includes Greeks."""
        toolkit = MassiveToolkit(api_key="test")
        result = await toolkit.get_options_chain_enriched("AAPL")

        assert result["source"] == "massive"
        assert len(result["contracts"]) > 0
        assert "greeks" in result["contracts"][0]
        assert result["contracts"][0]["greeks"]["delta"] == 0.512

    @pytest.mark.asyncio
    async def test_graceful_degradation(self, mock_client):
        """Returns fallback on error."""
        mock_client.list_snapshot_options_chain.side_effect = Exception("API Error")
        toolkit = MassiveToolkit(api_key="test")
        result = await toolkit.get_options_chain_enriched("AAPL")

        assert "error" in result
        assert result["fallback"] == "use_yfinance_options"

    @pytest.mark.asyncio
    async def test_short_interest_derived_metrics(self, mock_client):
        """Short interest includes derived trend."""
        mock_client.list_short_interest = AsyncMock(return_value=[
            MagicMock(settlement_date="2026-02-14", short_interest=15000000, days_to_cover=3.34),
            MagicMock(settlement_date="2026-01-31", short_interest=14000000, days_to_cover=3.1),
        ])
        toolkit = MassiveToolkit(api_key="test")
        result = await toolkit.get_short_interest("GME")

        assert result["derived"]["trend"] == "increasing"
        assert result["derived"]["short_interest_change_pct"] > 0
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/massive-toolkit.spec.md` for full output structures
2. **Check dependencies** — TASK-092, TASK-093, TASK-094 must be in `tasks/completed/`
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Implement** the toolkit in `parrot/tools/massive/toolkit.py`
5. **Update** `parrot/tools/massive/__init__.py` with exports
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-095-massive-toolkit.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: 4e94bc29-f6c5-41d0-8fd5-63e0967fc976
**Date**: 2026-03-02
**Notes**: All 27 unit tests pass. Ruff clean. Import verified. Implemented all 5 tool methods with full output model transforms, derived metrics (trend, beat rate, z-scores, averages), cache integration via MassiveCache, graceful degradation with structured fallback dicts, `enrich_ticker()` parallel fetch, `enrich_candidates()` with asyncio.Semaphore, and lazy Benzinga detection.

**Deviations from spec**: Added `_enrich_ticker_selective()` for endpoint-specific batch enrichment beyond original scope.
