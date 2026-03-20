# TASK-101: Analyst Prompts Update

**Feature**: MassiveToolkit Integration (FEAT-019)
**Spec**: `sdd/specs/massivetoolkit-integration.spec.md`
**Status**: in-progress
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: antigravity-session

---

## Context

> Analysts need to know that enriched data may be present in their briefings so they
> can prioritize it correctly. This task adds source-priority instructions to three
> analyst prompts. Implements Spec Section 3 (Module 3).

---

## Scope

- Append Massive data source instructions to `ANALYST_EQUITY` prompt in `<sources_priority>` section:
  - Options chains with exchange-computed Greeks (`source: massive:options_chain`)
  - Benzinga earnings with revenue estimates (`source: massive:benzinga_earnings`)
  - Benzinga analyst ratings (`source: massive:benzinga_analyst_ratings`)
  - Instruction to prefer Massive Greeks over YFinance estimates.
- Append Massive data source instructions to `ANALYST_SENTIMENT` prompt:
  - FINRA short interest with days-to-cover (`source: massive:short_interest`)
  - Daily short volume ratios (`source: massive:short_volume`)
  - Derived short squeeze scores (`source: massive:derived_short_analysis`)
- Append Massive data source instructions to `ANALYST_RISK` prompt:
  - Exchange-computed Greeks for portfolio exposure calculations.
- Write validation tests that prompts contain the expected source references.

**NOT in scope**: Changing analyst behavior logic, CIO prompt changes, Secretary prompt changes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/finance/prompts.py` | MODIFY | Add Massive source instructions to 3 analyst prompts |
| `tests/unit/test_analyst_prompts.py` | CREATE | Validate prompt content includes Massive references |

---

## Implementation Notes

### Prompt Additions (Exact Text)

**Equity Analyst** — append inside `<sources_priority>`:
```
- Massive.com enrichment data (when available):
  - Options chains with exchange-computed Greeks (source: massive:options_chain)
  - Benzinga earnings with revenue estimates (source: massive:benzinga_earnings)
  - Benzinga analyst ratings with individual actions (source: massive:benzinga_analyst_ratings)
  When these are present, prefer their data over YFinance options data
  as Massive Greeks are exchange-computed (more accurate than estimates).
```

**Sentiment Analyst** — append inside `<sources_priority>`:
```
- Massive.com enrichment data (when available):
  - FINRA short interest with days-to-cover (source: massive:short_interest)
  - Daily short volume ratios (source: massive:short_volume)
  - Derived short squeeze scores (source: massive:derived_short_analysis)
  When present, use these as your primary short interest data source.
  Pay special attention to the squeeze_score and conviction_signal fields.
```

**Risk Analyst** — append:
```
- When options chain data with exchange-computed Greeks is available
  (source: massive:options_chain), use these for portfolio Greeks exposure
  calculations instead of estimated values. Fields: delta, gamma, theta, vega
  per contract, implied_volatility from OPRA data.
```

### References in Codebase
- `parrot/finance/prompts.py` — `ANALYST_EQUITY`, `ANALYST_SENTIMENT`, `ANALYST_RISK`

---

## Acceptance Criteria

- [ ] `ANALYST_EQUITY` prompt references `massive:options_chain`, `massive:benzinga_earnings`, `massive:benzinga_analyst_ratings`
- [ ] `ANALYST_SENTIMENT` prompt references `massive:short_interest`, `massive:short_volume`, `massive:derived_short_analysis`
- [ ] `ANALYST_RISK` prompt references `massive:options_chain` for Greeks
- [ ] Prompts instruct analysts to prefer Massive data over estimated data
- [ ] All tests pass: `pytest tests/unit/test_analyst_prompts.py -v`
- [ ] No linting errors: `ruff check parrot/finance/prompts.py`

---

## Test Specification

```python
# tests/unit/test_analyst_prompts.py
from parrot.finance.prompts import ANALYST_EQUITY, ANALYST_SENTIMENT, ANALYST_RISK


class TestAnalystPromptsMassive:
    def test_equity_has_options_source(self):
        assert "massive:options_chain" in ANALYST_EQUITY

    def test_equity_has_earnings_source(self):
        assert "massive:benzinga_earnings" in ANALYST_EQUITY

    def test_equity_has_ratings_source(self):
        assert "massive:benzinga_analyst_ratings" in ANALYST_EQUITY

    def test_sentiment_has_short_interest(self):
        assert "massive:short_interest" in ANALYST_SENTIMENT

    def test_sentiment_has_short_volume(self):
        assert "massive:short_volume" in ANALYST_SENTIMENT

    def test_sentiment_has_squeeze_analysis(self):
        assert "massive:derived_short_analysis" in ANALYST_SENTIMENT

    def test_risk_has_greeks_source(self):
        assert "massive:options_chain" in ANALYST_RISK
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — this task has no dependencies (can run in parallel)
3. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-101-analyst-prompts-update.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: antigravity-session
**Date**: 2026-03-02
**Notes**: 
- Added Massive.com data reference instructions to the `<sources_priority>` of `ANALYST_EQUITY` and `ANALYST_SENTIMENT`.
- Appended OPRA Greeks instructions to the end of `<instructions>` in `ANALYST_RISK`.
- Added unit tests in `tests/unit/test_analyst_prompts.py` checking the presence of these instructions. All tests pass and linting is clear.

**Deviations from spec**: none
