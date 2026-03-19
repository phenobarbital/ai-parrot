# TASK-205: Add Hedging Guidance to Risk Analyst Prompt

**Feature**: Analyst Derivatives Recommendations (FEAT-027)
**Spec**: `sdd/specs/finance-analyst-derivatives-prompts.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (1h)
**Depends-on**: none
**Assigned-to**: claude-session

---

## Context

The Risk Analyst has options risk tools but no guidance on recommending derivatives-based hedges when portfolio risks are identified. This task adds a `<derivatives_guidance>` section enabling the Risk Analyst to recommend portfolio protection, sector hedges, single-stock hedges, futures hedges, and collars.

---

## Scope

- Locate `RISK_ANALYST_PROMPT` in `parrot/finance/prompts.py`
- Insert the `<derivatives_guidance>` block from spec §2.4
- Add `options_opportunity_flag` and `options_opportunity_reason` to the risk analyst output schema within the prompt

**NOT in scope**: changes to any other analyst prompt.

---

## Files to Modify

| File | Action | Description |
|------|--------|-------------|
| `parrot/finance/prompts.py` | modify | Add `<derivatives_guidance>` block to `RISK_ANALYST_PROMPT` and update its output schema |

---

## Guidance to Insert

Add the following block inside `RISK_ANALYST_PROMPT`, after the existing risk analysis section and before the output schema:

```xml
<derivatives_guidance>
DERIVATIVES FOR HEDGING

When you identify portfolio risks, you can recommend derivatives-based hedges.

HEDGING STRATEGIES:

1. PORTFOLIO PROTECTION (tail risk)
   - Asset: SPY puts or VIX calls
   - When: Portfolio drawdown risk elevated, correlation spike expected
   - How: "Recommend 5% allocation to SPY puts (3-month, 10% OTM)"

2. SECTOR HEDGE
   - Asset: Sector ETF puts (XLF, XLE, XLK)
   - When: Overexposed to a sector with elevated risk
   - How: "Recommend XLK puts to hedge tech concentration"

3. SINGLE-STOCK HEDGE
   - Asset: Individual stock puts
   - When: Large single-stock position with event risk
   - How: "Recommend protective puts on TSLA ahead of earnings"

4. FUTURES HEDGE
   - Asset: ES/NQ short
   - When: Want to reduce beta without selling positions
   - How: "Recommend short ES to neutralize 20% of equity beta"

5. COLLAR RECOMMENDATION
   - When: Protecting gains while generating some income
   - How: "Recommend collar on XYZ"

WHEN TO RECOMMEND DERIVATIVES:

| Risk Identified | Hedge Recommendation |
|-----------------|---------------------|
| Portfolio VAR > limit | SPY puts or short ES |
| Correlation spike risk | VIX calls |
| Single stock > 15% | Protective puts or collar |
| Sector > 40% | Sector ETF puts |
| Event risk (earnings, FOMC) | Reduce delta or buy puts |

OUTPUT FORMAT:
{
    "hedge_recommendation": {
        "asset": "SPY",
        "asset_class": "options",
        "strategy": "protective_put",
        "rationale": "Portfolio VAR approaching limit, 3-month puts provide tail protection",
        "sizing_pct": 3.0,
        "suggested_strike": "10% OTM",
        "suggested_dte": 90
    }
}

FLAG FOR CIO:
Set `options_opportunity_flag: true` when:
- You identify a hedging need that could be met with options
- Portfolio has positions that could generate income via covered calls
- IV is elevated on portfolio holdings (premium selling opportunity)
</derivatives_guidance>
```

Add to the risk analyst output schema:
```
"options_opportunity_flag": boolean — true if a derivatives-based hedge or opportunity is identified
"options_opportunity_reason": string — brief explanation if flag is true (e.g., 'Portfolio VAR near limit, SPY puts recommended')
```

---

## Acceptance Criteria

- [ ] `RISK_ANALYST_PROMPT` contains `<derivatives_guidance>` XML block
- [ ] Prompt includes all 5 hedging strategies (portfolio protection, sector, single-stock, futures, collar)
- [ ] Prompt includes risk-to-hedge decision table
- [ ] Prompt output schema includes `options_opportunity_flag` and `options_opportunity_reason`
- [ ] `ruff check parrot/finance/prompts.py` passes with no errors

---

## Agent Instructions

1. Read `parrot/finance/prompts.py` to locate `RISK_ANALYST_PROMPT`
2. Insert the `<derivatives_guidance>` block from spec §2.4
3. Add `options_opportunity_flag` and `options_opportunity_reason` fields to the output schema section
4. Run linter:
   ```bash
   source .venv/bin/activate
   ruff check parrot/finance/prompts.py
   ```
5. Confirm changes look correct before marking done
