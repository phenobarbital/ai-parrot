# TASK-087: Piotroski F-Score

**Feature**: FEAT-017 QuantToolkit
**Spec**: `sdd/specs/quant-toolkit.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-084
**Assigned-to**: claude-opus-session

---

## Context

This task implements the Piotroski F-Score calculator — a fundamental quality scoring system. The equity analyst crew uses F-Scores to evaluate company financial health based on 9 accounting criteria.

Reference: Spec Section 3 (Module 4: Piotroski F-Score).

---

## Scope

- Implement the 9 Piotroski criteria:
  1. **Positive Net Income** → NI > 0 (1 point)
  2. **Positive ROA** → NI / Total Assets > 0 (1 point)
  3. **Positive Operating Cash Flow** → OCF > 0 (1 point)
  4. **Cash Flow > Net Income** → OCF > NI (1 point, quality of earnings)
  5. **Lower Long-Term Debt** → LT Debt decreased YoY (1 point)
  6. **Higher Current Ratio** → Current Ratio increased YoY (1 point)
  7. **No New Shares Issued** → Shares Outstanding <= prior year (1 point)
  8. **Higher Gross Margin** → Gross Margin % increased YoY (1 point)
  9. **Higher Asset Turnover** → Revenue / Total Assets increased YoY (1 point)
- Implement data completeness tracking
- Implement interpretation scale (8-9 Excellent, 6-7 Good, 4-5 Fair, 0-3 Poor)
- Implement batch scoring for multiple symbols
- Write comprehensive unit tests

**NOT in scope**:
- Fetching financials from data sources (callers provide data)
- The main QuantToolkit class (TASK-079)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/quant/piotroski.py` | CREATE | F-Score calculator |
| `tests/tools/test_quant/test_piotroski.py` | CREATE | Unit tests |

---

## Implementation Notes

### Pattern to Follow

```python
from typing import Any
from .models import PiotroskiInput


def calculate_piotroski_score(input_data: PiotroskiInput) -> dict:
    """
    Calculate Piotroski F-Score (0-9) for fundamental quality.

    The F-Score measures financial strength using 9 binary criteria
    across three categories:
    - Profitability (4 points)
    - Leverage/Liquidity/Source of Funds (3 points)
    - Operating Efficiency (2 points)

    Returns:
        {
            "total_score": int (0-9),
            "criteria": {
                "positive_net_income": {"score": 1, "value": 15000000, "threshold": "> 0"},
                ...
            },
            "data_completeness_pct": float (0-100),
            "interpretation": "Excellent" | "Good" | "Fair" | "Poor",
            "category_scores": {
                "profitability": 4,
                "leverage_liquidity": 2,
                "operating_efficiency": 1,
            }
        }
    """
    q = input_data.quarterly_financials
    p = input_data.prior_year_financials

    criteria = {}
    total_score = 0
    criteria_with_data = 0

    # ===== PROFITABILITY (4 criteria) =====

    # 1. Positive Net Income
    if "net_income" in q:
        criteria_with_data += 1
        ni = q["net_income"]
        score = 1 if ni > 0 else 0
        criteria["positive_net_income"] = {
            "score": score, "value": ni, "threshold": "> 0"
        }
        total_score += score

    # 2. Positive ROA
    if "net_income" in q and "total_assets" in q and q["total_assets"] > 0:
        criteria_with_data += 1
        roa = q["net_income"] / q["total_assets"]
        score = 1 if roa > 0 else 0
        criteria["positive_roa"] = {
            "score": score, "value": round(roa, 4), "threshold": "> 0"
        }
        total_score += score

    # 3. Positive Operating Cash Flow
    if "operating_cash_flow" in q:
        criteria_with_data += 1
        ocf = q["operating_cash_flow"]
        score = 1 if ocf > 0 else 0
        criteria["positive_ocf"] = {
            "score": score, "value": ocf, "threshold": "> 0"
        }
        total_score += score

    # 4. Cash Flow > Net Income (quality of earnings)
    if "operating_cash_flow" in q and "net_income" in q:
        criteria_with_data += 1
        score = 1 if q["operating_cash_flow"] > q["net_income"] else 0
        criteria["ocf_greater_than_ni"] = {
            "score": score,
            "value": f"OCF={q['operating_cash_flow']}, NI={q['net_income']}",
            "threshold": "OCF > NI"
        }
        total_score += score

    # ===== LEVERAGE/LIQUIDITY (3 criteria) =====

    # 5. Lower Long-Term Debt YoY
    if "long_term_debt" in q and "long_term_debt" in p:
        criteria_with_data += 1
        score = 1 if q["long_term_debt"] <= p["long_term_debt"] else 0
        criteria["lower_debt"] = {
            "score": score,
            "value": f"Current={q['long_term_debt']}, Prior={p['long_term_debt']}",
            "threshold": "current <= prior"
        }
        total_score += score

    # 6. Higher Current Ratio YoY
    current_ratio = None
    if "current_assets" in q and "current_liabilities" in q and q["current_liabilities"] > 0:
        current_ratio = q["current_assets"] / q["current_liabilities"]

    if current_ratio is not None and "current_ratio" in p:
        criteria_with_data += 1
        score = 1 if current_ratio > p["current_ratio"] else 0
        criteria["higher_current_ratio"] = {
            "score": score,
            "value": f"Current={round(current_ratio, 2)}, Prior={p['current_ratio']}",
            "threshold": "current > prior"
        }
        total_score += score

    # 7. No New Shares Issued
    if "shares_outstanding" in q and "shares_outstanding" in p:
        criteria_with_data += 1
        score = 1 if q["shares_outstanding"] <= p["shares_outstanding"] else 0
        criteria["no_dilution"] = {
            "score": score,
            "value": f"Current={q['shares_outstanding']}, Prior={p['shares_outstanding']}",
            "threshold": "current <= prior"
        }
        total_score += score

    # ===== OPERATING EFFICIENCY (2 criteria) =====

    # 8. Higher Gross Margin YoY
    gross_margin = None
    if "gross_profit" in q and "revenue" in q and q["revenue"] > 0:
        gross_margin = q["gross_profit"] / q["revenue"]

    if gross_margin is not None and "gross_margin" in p:
        criteria_with_data += 1
        score = 1 if gross_margin > p["gross_margin"] else 0
        criteria["higher_gross_margin"] = {
            "score": score,
            "value": f"Current={round(gross_margin, 4)}, Prior={p['gross_margin']}",
            "threshold": "current > prior"
        }
        total_score += score

    # 9. Higher Asset Turnover YoY
    asset_turnover = None
    if "revenue" in q and "total_assets" in q and q["total_assets"] > 0:
        asset_turnover = q["revenue"] / q["total_assets"]

    if asset_turnover is not None and "asset_turnover" in p:
        criteria_with_data += 1
        score = 1 if asset_turnover > p["asset_turnover"] else 0
        criteria["higher_asset_turnover"] = {
            "score": score,
            "value": f"Current={round(asset_turnover, 4)}, Prior={p['asset_turnover']}",
            "threshold": "current > prior"
        }
        total_score += score

    # Calculate completeness and interpretation
    data_completeness = (criteria_with_data / 9) * 100
    interpretation = _interpret_score(total_score)

    # Category breakdown
    profitability = sum(
        criteria.get(c, {}).get("score", 0)
        for c in ["positive_net_income", "positive_roa", "positive_ocf", "ocf_greater_than_ni"]
    )
    leverage = sum(
        criteria.get(c, {}).get("score", 0)
        for c in ["lower_debt", "higher_current_ratio", "no_dilution"]
    )
    efficiency = sum(
        criteria.get(c, {}).get("score", 0)
        for c in ["higher_gross_margin", "higher_asset_turnover"]
    )

    return {
        "total_score": total_score,
        "criteria": criteria,
        "data_completeness_pct": round(data_completeness, 1),
        "interpretation": interpretation,
        "category_scores": {
            "profitability": profitability,
            "leverage_liquidity": leverage,
            "operating_efficiency": efficiency,
        },
    }


def _interpret_score(score: int) -> str:
    """Interpret F-Score."""
    if score >= 8:
        return "Excellent"
    elif score >= 6:
        return "Good"
    elif score >= 4:
        return "Fair"
    else:
        return "Poor"


def batch_piotroski_scores(
    symbols_data: dict[str, PiotroskiInput]
) -> dict[str, dict]:
    """
    Calculate F-Scores for multiple symbols.

    Args:
        symbols_data: {symbol: PiotroskiInput}

    Returns:
        {symbol: {score_result}}
    """
    results = {}
    for symbol, data in symbols_data.items():
        results[symbol] = calculate_piotroski_score(data)
    return results
```

### Key Constraints
- All 9 criteria must be implemented
- Handle missing data gracefully (track completeness)
- Score must be integer 0-9
- Interpretation must match scale: 8-9 Excellent, 6-7 Good, 4-5 Fair, 0-3 Poor
- Division by zero must be handled (total_assets, revenue, current_liabilities)

### References in Codebase
- `trading_skills/src/trading_skills/piotroski.py` — reference implementation (306 lines)
- Spec Section 3 Module 4 for the 9 criteria definitions

---

## Acceptance Criteria

- [x] All 9 Piotroski criteria implemented
- [x] Data completeness tracking works correctly
- [x] Interpretation matches the defined scale
- [x] Batch scoring works for multiple symbols
- [x] All tests pass: `pytest tests/tools/test_quant/test_piotroski.py -v`
- [x] Handles missing data and division by zero

---

## Test Specification

```python
# tests/tools/test_quant/test_piotroski.py
import pytest
from parrot.tools.quant.models import PiotroskiInput
from parrot.tools.quant.piotroski import (
    calculate_piotroski_score, batch_piotroski_scores, _interpret_score
)


@pytest.fixture
def complete_financials():
    """Complete financials for all 9 criteria."""
    return PiotroskiInput(
        quarterly_financials={
            "net_income": 15_000_000,
            "total_assets": 100_000_000,
            "operating_cash_flow": 18_000_000,
            "current_assets": 40_000_000,
            "current_liabilities": 20_000_000,
            "long_term_debt": 25_000_000,
            "shares_outstanding": 10_000_000,
            "revenue": 80_000_000,
            "gross_profit": 32_000_000,
        },
        prior_year_financials={
            "total_assets": 95_000_000,
            "current_ratio": 1.8,
            "long_term_debt": 28_000_000,
            "shares_outstanding": 10_000_000,
            "asset_turnover": 0.75,
            "gross_margin": 0.38,
        },
    )


@pytest.fixture
def poor_financials():
    """Poor financials for testing low scores."""
    return PiotroskiInput(
        quarterly_financials={
            "net_income": -5_000_000,  # Negative
            "total_assets": 100_000_000,
            "operating_cash_flow": -2_000_000,  # Negative
            "current_assets": 30_000_000,
            "current_liabilities": 40_000_000,  # Low current ratio
            "long_term_debt": 50_000_000,  # Increased
            "shares_outstanding": 12_000_000,  # Diluted
            "revenue": 60_000_000,  # Lower
            "gross_profit": 18_000_000,  # Lower margin
        },
        prior_year_financials={
            "total_assets": 95_000_000,
            "current_ratio": 2.0,
            "long_term_debt": 40_000_000,
            "shares_outstanding": 10_000_000,
            "asset_turnover": 0.80,
            "gross_margin": 0.35,
        },
    )


class TestPiotroskiScore:
    def test_complete_data_all_criteria(self, complete_financials):
        """All 9 criteria are evaluated with complete data."""
        result = calculate_piotroski_score(complete_financials)
        assert result["data_completeness_pct"] == 100.0
        assert len(result["criteria"]) == 9

    def test_score_range(self, complete_financials):
        """Score is between 0 and 9."""
        result = calculate_piotroski_score(complete_financials)
        assert 0 <= result["total_score"] <= 9

    def test_good_company_scores_high(self, complete_financials):
        """Company with good financials scores 6+."""
        result = calculate_piotroski_score(complete_financials)
        # Our fixture has: positive NI, ROA, OCF, OCF>NI, lower debt,
        # shares not diluted = at least 6 points
        assert result["total_score"] >= 6
        assert result["interpretation"] in ["Excellent", "Good"]

    def test_poor_company_scores_low(self, poor_financials):
        """Company with poor financials scores low."""
        result = calculate_piotroski_score(poor_financials)
        assert result["total_score"] <= 4
        assert result["interpretation"] in ["Fair", "Poor"]

    def test_category_breakdown(self, complete_financials):
        """Category scores add up to total."""
        result = calculate_piotroski_score(complete_financials)
        cat = result["category_scores"]
        assert cat["profitability"] + cat["leverage_liquidity"] + cat["operating_efficiency"] <= 9


class TestInterpretation:
    def test_excellent(self):
        assert _interpret_score(9) == "Excellent"
        assert _interpret_score(8) == "Excellent"

    def test_good(self):
        assert _interpret_score(7) == "Good"
        assert _interpret_score(6) == "Good"

    def test_fair(self):
        assert _interpret_score(5) == "Fair"
        assert _interpret_score(4) == "Fair"

    def test_poor(self):
        assert _interpret_score(3) == "Poor"
        assert _interpret_score(0) == "Poor"


class TestPartialData:
    def test_partial_data_still_scores(self):
        """Can score with incomplete data."""
        partial = PiotroskiInput(
            quarterly_financials={
                "net_income": 10_000_000,
                "total_assets": 50_000_000,
                "operating_cash_flow": 12_000_000,
            },
            prior_year_financials={},
        )
        result = calculate_piotroski_score(partial)
        # Should get scores for NI, ROA, OCF, OCF>NI = 4 criteria
        assert result["data_completeness_pct"] < 100
        assert result["total_score"] >= 0


class TestBatchScoring:
    def test_batch_multiple_symbols(self, complete_financials, poor_financials):
        """Batch scoring works for multiple symbols."""
        results = batch_piotroski_scores({
            "AAPL": complete_financials,
            "BADCO": poor_financials,
        })
        assert "AAPL" in results
        assert "BADCO" in results
        assert results["AAPL"]["total_score"] > results["BADCO"]["total_score"]
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/quant-toolkit.spec.md` for full context
2. **Check dependencies** — verify TASK-084 is in `tasks/completed/`
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-080-piotroski-fscore.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-opus-session
**Date**: 2026-03-02
**Notes**:
- Created `parrot/tools/quant/piotroski.py` with full F-Score calculator
- Implemented all 9 Piotroski criteria:
  - Profitability (4): positive NI, positive ROA, positive OCF, OCF > NI
  - Leverage/Liquidity (3): lower debt, higher current ratio, no dilution
  - Operating Efficiency (2): higher gross margin, higher asset turnover
- Data completeness tracking (0-100%)
- Interpretation scale: 8-9 Excellent, 6-7 Good, 4-5 Fair, 0-3 Poor
- Category breakdown scores
- Utility functions: `batch_piotroski_scores`, `get_fscore_summary`, `rank_by_fscore`
- Edge cases handled: division by zero, missing data, empty inputs
- All 39 Piotroski tests pass
- Updated `__init__.py` to export all Piotroski functions

**Deviations from spec**: None. Implementation follows spec exactly.
