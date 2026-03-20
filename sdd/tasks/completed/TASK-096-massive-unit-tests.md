# TASK-096: MassiveToolkit Unit Tests

**Feature**: MassiveToolkit
**Spec**: `sdd/specs/massive-toolkit.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-095
**Assigned-to**: 4e94bc29-f6c5-41d0-8fd5-63e0967fc976

---

## Context

This task implements comprehensive unit tests for all MassiveToolkit components. All external dependencies (SDK, Redis) are mocked to ensure fast, deterministic tests.

Reference: Spec Section 4 "Test Specification"

---

## Scope

- Write unit tests for all input models (validation, defaults)
- Write unit tests for client wrapper (retry logic, rate limiting)
- Write unit tests for cache layer (key generation, TTLs)
- Write unit tests for toolkit (transformation, derived metrics, degradation)
- Achieve >90% code coverage for `parrot/tools/massive/`

**NOT in scope**:
- Integration tests with real API (TASK-097)
- Performance/load testing

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/test_massive_models.py` | CREATE | Input model tests |
| `tests/test_massive_client.py` | CREATE | Client wrapper tests |
| `tests/test_massive_cache.py` | CREATE | Cache layer tests |
| `tests/test_massive_toolkit.py` | CREATE | Main toolkit tests |

---

## Implementation Notes

### Test Categories

**Model Tests (`test_massive_models.py`):**
- Validation: required fields, type constraints
- Defaults: limit, order, include_consensus
- Edge cases: empty strings, negative numbers

**Client Tests (`test_massive_client.py`):**
- Success path: each endpoint returns data
- Retry: transient errors trigger retry
- Rate limit: 429 triggers backoff
- Exhaustion: max retries raises exception

**Cache Tests (`test_massive_cache.py`):**
- Key generation: unique per endpoint/params
- TTL selection: correct per endpoint
- Cache hit: returns cached data
- Cache miss: returns None

**Toolkit Tests (`test_massive_toolkit.py`):**
- Init: requires API key
- Each tool: transforms SDK response correctly
- Greeks: present in options output
- Derived metrics: trend, change_pct calculated
- Graceful degradation: returns fallback on error
- Cache integration: checks cache, stores result
- Batch: Semaphore limits concurrency

### Pattern to Follow

```python
import pytest
from unittest.mock import MagicMock, AsyncMock, patch


@pytest.fixture
def mock_massive_sdk():
    """Mock the massive SDK at module level."""
    with patch("parrot.tools.massive.client.RESTClient") as mock:
        yield mock


class TestOptionsChainTransformation:
    @pytest.mark.asyncio
    async def test_greeks_extracted(self, mock_massive_sdk):
        """Greeks are extracted from SDK response."""
        mock_massive_sdk.return_value.list_snapshot_options_chain.return_value = [
            MagicMock(
                ticker="O:AAPL250321C00185000",
                greeks=MagicMock(delta=0.5, gamma=0.03, theta=-0.15, vega=0.3),
                implied_volatility=0.28,
            )
        ]
        # ... test transformation
```

### Key Constraints

- All tests must be async-compatible (`pytest-asyncio`)
- Mock all external dependencies (SDK, Redis)
- Use `MagicMock` with appropriate return values
- Test both success and failure paths
- Test edge cases (empty lists, None values)

### References in Codebase

- `tests/test_finnhub_toolkit.py` — Similar toolkit test pattern
- `tests/test_alpaca_toolkit.py` — Complex financial toolkit tests

---

## Acceptance Criteria

- [ ] All model tests pass: `pytest tests/test_massive_models.py -v`
- [ ] All client tests pass: `pytest tests/test_massive_client.py -v`
- [ ] All cache tests pass: `pytest tests/test_massive_cache.py -v`
- [ ] All toolkit tests pass: `pytest tests/test_massive_toolkit.py -v`
- [ ] Code coverage >90%: `pytest --cov=parrot/tools/massive tests/test_massive*.py`
- [ ] No mocking leaks (all patches properly scoped)

---

## Test Specification

### Model Tests

```python
# tests/test_massive_models.py
import pytest
from pydantic import ValidationError
from parrot.tools.massive.models import (
    OptionsChainInput, ShortInterestInput, ShortVolumeInput,
    EarningsDataInput, AnalystRatingsInput
)


class TestOptionsChainInput:
    def test_underlying_required(self):
        with pytest.raises(ValidationError):
            OptionsChainInput()

    def test_defaults_applied(self):
        inp = OptionsChainInput(underlying="AAPL")
        assert inp.limit == 250
        assert inp.contract_type is None

    def test_contract_type_values(self):
        for ct in ["call", "put", None]:
            inp = OptionsChainInput(underlying="AAPL", contract_type=ct)
            assert inp.contract_type == ct


class TestShortInterestInput:
    def test_defaults(self):
        inp = ShortInterestInput(symbol="GME")
        assert inp.limit == 10
        assert inp.order == "desc"


class TestAnalystRatingsInput:
    def test_include_consensus_default(self):
        inp = AnalystRatingsInput(symbol="AAPL")
        assert inp.include_consensus is True
```

### Client Tests

```python
# tests/test_massive_client.py
import pytest
from unittest.mock import MagicMock, patch
from parrot.tools.massive.client import MassiveClient


class TestMassiveClientRetry:
    @pytest.mark.asyncio
    async def test_retries_on_5xx(self):
        """Retries transient 5xx errors."""
        with patch("parrot.tools.massive.client.RESTClient") as mock:
            mock.return_value.list_short_interest.side_effect = [
                Exception("503"),
                [MagicMock(short_interest=1000)],
            ]
            client = MassiveClient(api_key="test")
            result = await client.list_short_interest("GME")
            assert len(result) == 1
            assert mock.return_value.list_short_interest.call_count == 2

    @pytest.mark.asyncio
    async def test_raises_after_max_retries(self):
        """Raises after exhausting retries."""
        with patch("parrot.tools.massive.client.RESTClient") as mock:
            mock.return_value.list_short_interest.side_effect = Exception("500")
            client = MassiveClient(api_key="test")
            with pytest.raises(Exception):
                await client.list_short_interest("GME")
```

### Toolkit Tests

```python
# tests/test_massive_toolkit.py
import pytest
from unittest.mock import MagicMock, AsyncMock, patch


class TestMassiveToolkitDerivedMetrics:
    @pytest.mark.asyncio
    async def test_short_interest_trend_increasing(self):
        """Trend is 'increasing' when SI grows."""
        with patch("parrot.tools.massive.toolkit.MassiveClient") as mock:
            mock.return_value.list_short_interest = AsyncMock(return_value=[
                MagicMock(settlement_date="2026-02-14", short_interest=15000000),
                MagicMock(settlement_date="2026-01-31", short_interest=14000000),
            ])
            toolkit = MassiveToolkit(api_key="test")
            result = await toolkit.get_short_interest("GME")
            assert result["derived"]["trend"] == "increasing"

    @pytest.mark.asyncio
    async def test_short_volume_ratio_calculated(self):
        """Short volume ratio is short_volume / total_volume."""
        with patch("parrot.tools.massive.toolkit.MassiveClient") as mock:
            mock.return_value.list_short_volume = AsyncMock(return_value=[
                MagicMock(date="2026-03-01", short_volume=10000, total_volume=40000),
            ])
            toolkit = MassiveToolkit(api_key="test")
            result = await toolkit.get_short_volume("TSLA")
            assert result["data"][0]["short_volume_ratio"] == 0.25


class TestMassiveToolkitGracefulDegradation:
    @pytest.mark.asyncio
    async def test_returns_fallback_on_api_error(self):
        """Returns fallback dict when API fails."""
        with patch("parrot.tools.massive.toolkit.MassiveClient") as mock:
            mock.return_value.list_snapshot_options_chain = AsyncMock(
                side_effect=Exception("Network error")
            )
            toolkit = MassiveToolkit(api_key="test")
            result = await toolkit.get_options_chain_enriched("AAPL")
            assert "error" in result
            assert result["fallback"] == "use_yfinance_options"
            assert result["source"] == "massive_error"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/massive-toolkit.spec.md` for test requirements
2. **Check dependencies** — TASK-095 must be in `tasks/completed/`
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Implement** all test files
5. **Run tests**: `pytest tests/test_massive*.py -v`
6. **Check coverage**: `pytest --cov=parrot/tools/massive tests/test_massive*.py`
7. **Verify** all acceptance criteria are met
8. **Move this file** to `sdd/tasks/completed/TASK-096-massive-unit-tests.md`
9. **Update index** → `"done"`
10. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: 4e94bc29-f6c5-41d0-8fd5-63e0967fc976
**Date**: 2026-03-02
**Notes**: All 109 unit tests across models (30), client (28), cache (24), and toolkit (27) passed successfully. The test suite thoroughly verifies input validation, default assignments, rate limit/retry backoff behaviors, TTLCache operations, and structured fallbacks for graceful degradation across all 5 endpoints. Code is fully tested without requiring real network requests via complete Mocking of the MassiveClient inside the toolkit tests.

**Deviations from spec**: none
