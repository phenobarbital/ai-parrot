# TASK-207: Integration Tests for Analyst Derivatives Prompts

**Feature**: Analyst Derivatives Recommendations (FEAT-027)
**Spec**: `sdd/specs/finance-analyst-derivatives-prompts.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2h)
**Depends-on**: TASK-202, TASK-203, TASK-204, TASK-205, TASK-206
**Assigned-to**: claude-session

---

## Context

After all analyst prompts have been updated (TASK-202 through TASK-206), this task writes the integration tests from spec §4 to verify all prompts contain the required derivatives guidance and output schema fields.

---

## Scope

- Create `tests/test_analyst_derivatives_prompts.py` with all tests from spec §4
- Tests are import-only (no LLM calls) — verify prompt string contents

**NOT in scope**: live LLM calls or end-to-end deliberation cycle testing.

---

## Files to Create

| File | Action | Description |
|------|--------|-------------|
| `tests/test_analyst_derivatives_prompts.py` | CREATE | Integration tests for all analyst prompt derivatives guidance |

---

## Test Cases

### Macro Analyst (futures)

```python
def test_macro_analyst_has_futures_guidance():
    from parrot.finance.prompts import MACRO_ANALYST_PROMPT
    assert "<derivatives_guidance>" in MACRO_ANALYST_PROMPT
    assert "ES" in MACRO_ANALYST_PROMPT
    assert "futures" in MACRO_ANALYST_PROMPT.lower()

def test_macro_analyst_has_margin_note():
    from parrot.finance.prompts import MACRO_ANALYST_PROMPT
    assert "margin" in MACRO_ANALYST_PROMPT.lower()

def test_macro_analyst_has_options_flag():
    from parrot.finance.prompts import MACRO_ANALYST_PROMPT
    assert "options_opportunity_flag" in MACRO_ANALYST_PROMPT
    assert "options_opportunity_reason" in MACRO_ANALYST_PROMPT
```

### Equity Analyst (options)

```python
def test_equity_analyst_has_options_guidance():
    from parrot.finance.prompts import EQUITY_ANALYST_PROMPT
    assert "<derivatives_guidance>" in EQUITY_ANALYST_PROMPT
    assert "covered" in EQUITY_ANALYST_PROMPT.lower()
    assert "protective" in EQUITY_ANALYST_PROMPT.lower()

def test_equity_analyst_has_options_flag():
    from parrot.finance.prompts import EQUITY_ANALYST_PROMPT
    assert "options_opportunity_flag" in EQUITY_ANALYST_PROMPT
    assert "options_opportunity_reason" in EQUITY_ANALYST_PROMPT
```

### Sentiment Analyst (flow translation)

```python
def test_sentiment_analyst_has_flow_guidance():
    from parrot.finance.prompts import SENTIMENT_ANALYST_PROMPT
    assert "<derivatives_guidance>" in SENTIMENT_ANALYST_PROMPT
    assert "flow" in SENTIMENT_ANALYST_PROMPT.lower()
    assert "unusual" in SENTIMENT_ANALYST_PROMPT.lower()

def test_sentiment_analyst_has_options_flag():
    from parrot.finance.prompts import SENTIMENT_ANALYST_PROMPT
    assert "options_opportunity_flag" in SENTIMENT_ANALYST_PROMPT
    assert "options_opportunity_reason" in SENTIMENT_ANALYST_PROMPT
```

### Risk Analyst (hedging)

```python
def test_risk_analyst_has_hedge_guidance():
    from parrot.finance.prompts import RISK_ANALYST_PROMPT
    assert "<derivatives_guidance>" in RISK_ANALYST_PROMPT
    assert "hedge" in RISK_ANALYST_PROMPT.lower()
    assert "protective" in RISK_ANALYST_PROMPT.lower()

def test_risk_analyst_has_options_flag():
    from parrot.finance.prompts import RISK_ANALYST_PROMPT
    assert "options_opportunity_flag" in RISK_ANALYST_PROMPT
    assert "options_opportunity_reason" in RISK_ANALYST_PROMPT
```

### Crypto Analyst (awareness note)

```python
def test_crypto_analyst_has_derivatives_note():
    from parrot.finance.prompts import CRYPTO_ANALYST_PROMPT
    assert "<derivatives_guidance>" in CRYPTO_ANALYST_PROMPT

def test_crypto_analyst_has_options_flag():
    from parrot.finance.prompts import CRYPTO_ANALYST_PROMPT
    assert "options_opportunity_flag" in CRYPTO_ANALYST_PROMPT
    assert "options_opportunity_reason" in CRYPTO_ANALYST_PROMPT
```

### All analysts have the flag (parametrized)

```python
import pytest

@pytest.mark.parametrize("prompt_name", [
    "MACRO_ANALYST_PROMPT",
    "EQUITY_ANALYST_PROMPT",
    "SENTIMENT_ANALYST_PROMPT",
    "RISK_ANALYST_PROMPT",
    "CRYPTO_ANALYST_PROMPT",
])
def test_all_analysts_have_options_opportunity_flag(prompt_name):
    import parrot.finance.prompts as prompts_module
    prompt = getattr(prompts_module, prompt_name)
    assert "options_opportunity_flag" in prompt, (
        f"{prompt_name} is missing 'options_opportunity_flag'"
    )
    assert "options_opportunity_reason" in prompt, (
        f"{prompt_name} is missing 'options_opportunity_reason'"
    )
```

---

## File Structure

```python
# tests/test_analyst_derivatives_prompts.py
"""
Integration tests verifying that all analyst prompts include
derivatives guidance (FEAT-027).
"""
import pytest


# --- Macro Analyst ---

def test_macro_analyst_has_futures_guidance():
    ...

# (etc.)
```

---

## Acceptance Criteria

- [ ] `tests/test_analyst_derivatives_prompts.py` created with all test cases above
- [ ] All tests pass:
  ```bash
  source .venv/bin/activate
  pytest tests/test_analyst_derivatives_prompts.py -v --no-header
  ```
- [ ] No existing tests broken:
  ```bash
  pytest --tb=short -q
  ```

---

## Agent Instructions

1. Ensure TASK-202 through TASK-206 are done before starting
2. Create `tests/test_analyst_derivatives_prompts.py` with all tests above
3. Run:
   ```bash
   source .venv/bin/activate
   pytest tests/test_analyst_derivatives_prompts.py -v --no-header 2>&1 | tail -30
   ```
4. Fix any import or content mismatches (check actual prompt variable names in `parrot/finance/prompts.py`)
5. Run full suite to confirm no regressions:
   ```bash
   pytest --tb=short -q 2>&1 | tail -20
   ```
