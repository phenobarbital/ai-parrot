# TASK-098: CandidateTicker Model & Data Needs Classifier

**Feature**: MassiveToolkit Integration (FEAT-019)
**Spec**: `sdd/specs/massivetoolkit-integration.spec.md`
**Status**: in-progress
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: antigravity-session

---

## Context

> Foundation data model for the enrichment pipeline. The `CandidateTicker` dataclass and
> data-needs classification logic are required by the `EnrichmentService` (TASK-099).
> Implements Spec Section 2 (Data Models) and the extraction/classification helpers
> described in the deliberation proposal.

---

## Scope

- Implement `CandidateTicker` dataclass with fields: `symbol`, `asset_class`, `mention_count`, `max_relevance`, `mentioned_by`, `data_needs`.
- Implement `_infer_asset_class(symbol: str) -> str` — classify symbol as `equity`, `crypto`, `etf`, or `index`.
- Implement `_infer_data_needs(crew_id: str, item: ResearchItem) -> set[str]` — map crew context to required Massive endpoints (`options`, `earnings`, `analyst_ratings`, `short_interest`, `short_volume`).
- Implement `_extract_candidates(briefings: dict[str, ResearchBriefing]) -> list[CandidateTicker]` — scan all briefings, build priority-ranked list capped at `max_candidates` (default 15).
- Write unit tests for all three functions.

**NOT in scope**: fetching data from Massive, merging into briefings, FSM changes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/finance/enrichment.py` | CREATE | `CandidateTicker` dataclass + extraction/classification helpers |
| `tests/unit/test_candidate_ticker.py` | CREATE | Unit tests for model and classifiers |

---

## Implementation Notes

### Pattern to Follow
```python
from dataclasses import dataclass, field

@dataclass
class CandidateTicker:
    symbol: str
    asset_class: str
    mention_count: int = 0
    max_relevance: float = 0.0
    mentioned_by: list[str] = field(default_factory=list)
    data_needs: set[str] = field(default_factory=set)
```

### Key Constraints
- Crypto tickers must be excluded from Massive enrichment (no coverage).
- ETFs get `options` only (no `earnings`/`analyst_ratings`).
- Cap candidate list at configurable `max_candidates` (env: `MASSIVE_MAX_CANDIDATES`, default 15).
- Sort by `mention_count` desc, then `max_relevance` desc.

### References in Codebase
- `parrot/finance/models.py` — `ResearchBriefing`, `ResearchItem` definitions
- `parrot/finance/enrichment.py` — will become the home for the full `EnrichmentService`

---

## Acceptance Criteria

- [ ] `CandidateTicker` dataclass created with all fields
- [ ] `_infer_asset_class` correctly classifies equity, crypto, ETF symbols
- [ ] `_infer_data_needs` maps equity mentions to `{options, earnings, analyst_ratings}` and sentiment to `{short_interest, short_volume}`
- [ ] `_extract_candidates` deduplicates across crews, ranks correctly, caps at 15
- [ ] All tests pass: `pytest tests/unit/test_candidate_ticker.py -v`
- [ ] No linting errors: `ruff check parrot/finance/enrichment.py`

---

## Test Specification

```python
# tests/unit/test_candidate_ticker.py
import pytest
from parrot.finance.enrichment import CandidateTicker, _extract_candidates, _infer_asset_class, _infer_data_needs


class TestCandidateTicker:
    def test_infer_asset_class_equity(self):
        """US equity symbols classified correctly."""
        assert _infer_asset_class("AAPL") == "equity"

    def test_infer_asset_class_crypto(self):
        """Crypto symbols classified correctly."""
        assert _infer_asset_class("BTC") == "crypto"

    def test_infer_asset_class_etf(self):
        """ETF symbols classified correctly."""
        assert _infer_asset_class("SPY") == "etf"

    def test_extract_candidates_ranking(self, mock_briefings):
        """Tickers mentioned by multiple crews rank higher."""
        candidates = _extract_candidates(mock_briefings)
        assert candidates[0].mention_count >= candidates[-1].mention_count

    def test_extract_candidates_cap(self, mock_briefings_large):
        """Candidate list capped at max_candidates."""
        candidates = _extract_candidates(mock_briefings_large, max_candidates=15)
        assert len(candidates) <= 15

    def test_infer_data_needs_equity(self):
        """Equity research items get options + earnings + analyst_ratings."""
        needs = _infer_data_needs("equity", mock_equity_item)
        assert {"options", "earnings", "analyst_ratings"}.issubset(needs)

    def test_infer_data_needs_sentiment(self):
        """Sentiment items get short_interest + short_volume."""
        needs = _infer_data_needs("sentiment", mock_sentiment_item)
        assert {"short_interest", "short_volume"}.issubset(needs)

    def test_crypto_excluded_from_enrichment(self, mock_briefings):
        """Crypto tickers have empty data_needs set."""
        candidates = _extract_candidates(mock_briefings)
        crypto = [c for c in candidates if c.asset_class == "crypto"]
        for c in crypto:
            assert len(c.data_needs) == 0
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — this task has no dependencies
3. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-098-candidate-ticker-model.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: Antigravity
**Date**: 2026-03-02
**Notes**: Implemented CandidateTicker and data_needs inference logic to prepare for MassiveToolkit enrichment. All unit tests successfully passed.

**Deviations from spec**: none
