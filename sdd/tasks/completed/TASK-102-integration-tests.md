# TASK-102: Integration Tests & Degradation Tests

**Feature**: MassiveToolkit Integration (FEAT-019)
**Spec**: `sdd/specs/massivetoolkit-integration.spec.md`
**Status**: in-progress
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-098, TASK-099, TASK-100, TASK-101
**Assigned-to**: antigravity-session

---

## Context

> Final validation task. Verifies the entire enrichment pipeline end-to-end, including
> graceful degradation under failure conditions. Implements Spec Section 4 (Integration Tests).

---

## Scope

- Implement `test_enrichment_service_e2e` — mock `MassiveToolkit`, feed real-shaped briefing structures, verify the full `enrich_briefings()` flow produces correctly enriched output.
- Implement `test_pipeline_enrichment_paths` — run `run_trading_pipeline()` with and without `massive_toolkit`, verify both paths produce valid output.
- Implement `test_pipeline_timeout_fallback` — set enrichment timeout to 1 second with a slow mock, verify pipeline proceeds with raw briefings.
- Implement `test_partial_failure` — mock 3 of 5 Massive endpoints failing, verify partial enrichment is still merged correctly.
- Implement `test_rate_budget` — monitor actual API call count with 15 candidate tickers, verify < 50 total calls.

**NOT in scope**: Live API calls to Massive.com (all tests use mocks).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/integration/test_enrichment_pipeline.py` | CREATE | End-to-end integration tests |
| `tests/conftest.py` | MODIFY | Add shared fixtures for enrichment test data |

---

## Implementation Notes

### Key Constraints
- All tests must use mocked `MassiveToolkit` — no live API calls.
- Test fixtures should mirror real `ResearchBriefing` shapes with multiple crews and tickers.
- Timeout test needs `asyncio.wait_for` with a short timeout (1s) and a slow mock that takes >1s.

### References in Codebase
- `parrot/finance/enrichment.py` — `EnrichmentService`
- `parrot/finance/execution.py` — `run_trading_pipeline()`
- `parrot/finance/fsm.py` — `PipelineStateMachine`
- `parrot/finance/models.py` — `ResearchBriefing`, `ResearchItem`

---

## Acceptance Criteria

- [ ] E2E test validates complete enrichment flow with mock Massive
- [ ] Pipeline runs correctly with and without `massive_toolkit`
- [ ] Timeout fallback test passes (pipeline continues with raw briefings)
- [ ] Partial failure test passes (3/5 endpoints fail, 2/5 merged)
- [ ] Rate budget test confirms < 50 API calls for 15 candidates
- [ ] All tests pass: `pytest tests/integration/test_enrichment_pipeline.py -v`

---

## Test Specification

```python
# tests/integration/test_enrichment_pipeline.py
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from parrot.finance.enrichment import EnrichmentService


@pytest.fixture
def full_mock_briefings():
    """Realistic briefings with 5 crews and ~20 tickers."""
    ...


@pytest.fixture
def slow_massive():
    """MassiveToolkit that takes 5s per call (for timeout testing)."""
    toolkit = AsyncMock()
    async def slow_call(*args, **kwargs):
        await asyncio.sleep(5)
        return {}
    toolkit.enrich_ticker = slow_call
    return toolkit


class TestEnrichmentPipelineE2E:
    async def test_full_enrichment_flow(self, full_mock_briefings):
        """Complete enrichment pipeline produces enriched briefings."""
        service = EnrichmentService(massive_toolkit=AsyncMock(), redis_client=MagicMock())
        result = await service.enrich_briefings(full_mock_briefings)
        # Equity briefing should have new items
        assert len(result["equity"].items) > len(full_mock_briefings["equity"].items)

    async def test_timeout_fallback(self, full_mock_briefings, slow_massive):
        """Pipeline proceeds with raw briefings on timeout."""
        service = EnrichmentService(massive_toolkit=slow_massive, redis_client=MagicMock())
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(
                service.enrich_briefings(full_mock_briefings),
                timeout=1.0,
            )

    async def test_partial_failure(self, full_mock_briefings):
        """Partial Massive failures still produce partial enrichment."""
        toolkit = AsyncMock()
        call_count = 0
        async def flaky_call(symbol, include=None):
            nonlocal call_count
            call_count += 1
            if call_count % 2 == 0:
                raise ConnectionError("API down")
            return {"short_interest": {"si_ratio": 0.03}}
        toolkit.enrich_ticker = flaky_call
        service = EnrichmentService(massive_toolkit=toolkit, redis_client=MagicMock())
        result = await service.enrich_briefings(full_mock_briefings)
        # Should still have some enrichment despite failures
        assert result is not None

    async def test_rate_budget(self, full_mock_briefings):
        """Total API calls stay under 50 for 15 candidates."""
        toolkit = AsyncMock()
        toolkit.enrich_ticker = AsyncMock(return_value={"options": {}})
        service = EnrichmentService(massive_toolkit=toolkit, redis_client=MagicMock())
        await service.enrich_briefings(full_mock_briefings)
        assert toolkit.enrich_ticker.call_count < 50
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-098, TASK-099, TASK-100, TASK-101 are in `tasks/completed/`
3. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-102-integration-tests.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: antigravity-session
**Date**: 2026-03-02
**Notes**: 
- Created `tests/integration/test_enrichment_pipeline.py` with 8 tests covering all acceptance criteria.
- E2E flow, pipeline paths (with/without massive), timeout fallback, partial failure (3/5 endpoints), and rate budget (<50 calls for 15 tickers).
- All tests pass, linting clean.

**Deviations from spec**: none
