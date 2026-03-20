# TASK-189: Derivatives Prompts Integration Tests

**Feature**: FEAT-027 (Analyst Derivatives Recommendations)
**Spec**: `sdd/specs/finance-analyst-derivatives-prompts.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: S (1-2h)
**Depends-on**: TASK-184, TASK-185, TASK-186, TASK-187, TASK-188
**Assigned-to**: claude-session
**Completed**: 2026-03-05

---

## Context

> Create integration tests to verify all analyst prompts contain derivatives
> guidance and the options_opportunity_flag output field.

---

## Scope

- Create test file `tests/test_analyst_derivatives_prompts.py`
- Test that each analyst prompt contains `<derivatives_guidance>`
- Test that each analyst prompt contains `options_opportunity_flag` in output schema
- Test specific content presence (futures for macro, covered call for equity, etc.)

**NOT in scope**: E2E tests with actual LLM calls, deliberation tests.

---

## Files to Create / Modify

| File | Action | Description |
|------|--------|-------------|
| `tests/test_analyst_derivatives_prompts.py` | CREATE | Integration tests for prompt content |

---

## Implementation Notes

Tests should import prompts and check for string presence:

```python
from parrot.finance.prompts import (
    MACRO_ANALYST_PROMPT,  # or however the prompt is named
    EQUITY_ANALYST_PROMPT,
    # etc.
)
```

Note: Need to verify actual prompt variable names in `prompts.py`.

---

## Test Cases

```python
def test_macro_analyst_has_futures_guidance():
    assert "<derivatives_guidance>" in MACRO_ANALYST
    assert "ES" in MACRO_ANALYST
    assert "futures" in MACRO_ANALYST.lower()

def test_equity_analyst_has_options_guidance():
    assert "<derivatives_guidance>" in EQUITY_ANALYST
    assert "covered" in EQUITY_ANALYST.lower()

def test_sentiment_analyst_has_flow_guidance():
    assert "<derivatives_guidance>" in SENTIMENT_ANALYST
    assert "flow" in SENTIMENT_ANALYST.lower()

def test_risk_analyst_has_hedge_guidance():
    assert "<derivatives_guidance>" in RISK_ANALYST
    assert "hedge" in RISK_ANALYST.lower()

def test_all_analysts_have_options_flag():
    for prompt in [MACRO, EQUITY, CRYPTO, SENTIMENT, RISK]:
        assert "options_opportunity_flag" in prompt
```

---

## Acceptance Criteria

- [x] Test file created at `tests/test_analyst_derivatives_prompts.py`
- [x] Tests verify `<derivatives_guidance>` presence in each analyst
- [x] Tests verify `options_opportunity_flag` in each analyst output schema
- [x] Tests verify key content (futures for macro, covered call for equity, etc.)
- [x] All tests pass: `pytest tests/test_analyst_derivatives_prompts.py -v`
- [x] `ruff check tests/test_analyst_derivatives_prompts.py` passes

---

## Agent Instructions

1. Read `prompts.py` to identify exact prompt variable names for each analyst
2. Create `tests/test_analyst_derivatives_prompts.py`
3. Implement tests from spec Section 4
4. Run `pytest tests/test_analyst_derivatives_prompts.py -v`
5. Run `ruff check tests/test_analyst_derivatives_prompts.py`

---

## Completion Note

**Completed**: 2026-03-05
**Implemented by**: claude-session

### Summary

Created comprehensive integration tests for FEAT-027 analyst derivatives prompts.

### Test File Created

`tests/test_analyst_derivatives_prompts.py` — 49 tests organized by analyst:

| Test Class | Tests | Coverage |
|------------|-------|----------|
| TestMacroAnalystDerivatives | 8 | Futures (ES, NQ, ZB), micros, margin, flags |
| TestEquityAnalystDerivatives | 8 | Covered call, protective put, collar, flags |
| TestCryptoAnalystDerivatives | 3 | Options flag, perpetual futures |
| TestSentimentAnalystDerivatives | 8 | Flow signals, IV spike, flow fields, flags |
| TestRiskAnalystDerivatives | 8 | Hedge strategies, VAR, hedge_recommendation |
| TestAllAnalystsDerivatives | 14 | Parametrized cross-analyst verification |

### Verification

```bash
ruff check tests/test_analyst_derivatives_prompts.py  # All checks passed
pytest tests/test_analyst_derivatives_prompts.py --tb=short  # 49 passed in 3.22s
```

### Prompt Variables Used

```python
from parrot.finance.prompts import (
    ANALYST_MACRO,      # Macro Analyst
    ANALYST_EQUITY,     # Equity Analyst
    ANALYST_CRYPTO,     # Crypto Analyst
    ANALYST_SENTIMENT,  # Sentiment Analyst
    ANALYST_RISK,       # Risk Analyst
)
```
