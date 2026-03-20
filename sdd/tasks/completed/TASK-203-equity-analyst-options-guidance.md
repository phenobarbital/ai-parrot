# TASK-203: Add Options Guidance to Equity Analyst Prompt

**Feature**: Analyst Derivatives Recommendations (FEAT-027)
**Spec**: `sdd/specs/finance-analyst-derivatives-prompts.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (1h)
**Depends-on**: none
**Assigned-to**: claude-session

---

## Context

The Equity Analyst prompt recommends stocks and ETFs only. It has no guidance for recommending options strategies (covered calls, protective puts, long calls/puts, collars). This task adds a `<derivatives_guidance>` section enabling options recommendations.

---

## Scope

- Locate `EQUITY_ANALYST_PROMPT` in `parrot/finance/prompts.py`
- Insert the `<derivatives_guidance>` block from spec §2.2
- Add `options_opportunity_flag` and `options_opportunity_reason` to the equity analyst output schema within the prompt

**NOT in scope**: changes to any other analyst prompt.

---

## Files to Modify

| File | Action | Description |
|------|--------|-------------|
| `parrot/finance/prompts.py` | modify | Add `<derivatives_guidance>` block to `EQUITY_ANALYST_PROMPT` and update its output schema |

---

## Guidance to Insert

Add the following block inside `EQUITY_ANALYST_PROMPT`, after the existing tools/data section and before the output schema:

```xml
<derivatives_guidance>
OPTIONS RECOMMENDATIONS

You can recommend options strategies when they offer better risk/reward than direct positions.

STRATEGIES YOU CAN RECOMMEND:

1. COVERED CALL (income on existing positions)
   - Asset class: options
   - When: You're bullish but expect limited upside / range-bound
   - How: "Recommend selling 30-delta calls on existing XYZ position"

2. PROTECTIVE PUT (hedge existing positions)
   - Asset class: options
   - When: Bullish long-term but near-term risk elevated
   - How: "Recommend buying puts on XYZ to limit downside"

3. LONG CALL/PUT (directional with defined risk)
   - Asset class: options
   - When: High conviction + want limited capital at risk
   - How: "Recommend long calls on XYZ instead of shares"

4. COLLAR (protection + income)
   - Asset class: options
   - When: Protecting gains, willing to cap upside
   - How: "Recommend collar on XYZ: sell 25-delta call, buy 25-delta put"

WHEN TO RECOMMEND OPTIONS OVER STOCK:

| Condition | Recommendation |
|-----------|----------------|
| High conviction + limited capital | Long calls/puts |
| Own stock + range-bound view | Covered call |
| Own stock + binary event ahead | Protective put or collar |
| IV percentile > 60 + range view | Flag for CIO (iron condor/butterfly) |

OUTPUT FORMAT:
{
    "asset": "AAPL",
    "asset_class": "options",
    "signal": "buy",
    "strategy": "long_call",
    "rationale": "Earnings catalyst + limited risk profile preferred",
    "suggested_delta": 0.40,
    "suggested_dte": 45
}

FLAG FOR CIO:
Set `options_opportunity_flag: true` when:
- IV percentile > 50 on a stock you're neutral/range-bound on
- You recommend a stock but acknowledge binary event risk
- Existing portfolio position could benefit from income overlay
</derivatives_guidance>
```

Add to the equity analyst output schema:
```
"options_opportunity_flag": boolean — true if conditions favor options strategy
"options_opportunity_reason": string — brief explanation if flag is true (e.g., 'IV percentile 75 on SPY, range-bound view')
```

---

## Acceptance Criteria

- [ ] `EQUITY_ANALYST_PROMPT` contains `<derivatives_guidance>` XML block
- [ ] Prompt includes covered call, protective put, long call/put, and collar strategies
- [ ] Prompt output schema includes `options_opportunity_flag` and `options_opportunity_reason`
- [ ] `ruff check parrot/finance/prompts.py` passes with no errors

---

## Agent Instructions

1. Read `parrot/finance/prompts.py` to locate `EQUITY_ANALYST_PROMPT`
2. Insert the `<derivatives_guidance>` block from spec §2.2
3. Add `options_opportunity_flag` and `options_opportunity_reason` fields to the output schema section
4. Run linter:
   ```bash
   source .venv/bin/activate
   ruff check parrot/finance/prompts.py
   ```
5. Confirm changes look correct before marking done
