# TASK-202: Add Futures Guidance to Macro Analyst Prompt

**Feature**: Analyst Derivatives Recommendations (FEAT-027)
**Spec**: `sdd/specs/finance-analyst-derivatives-prompts.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (1h)
**Depends-on**: none
**Assigned-to**: claude-session

---

## Context

The Macro Analyst prompt currently references "index futures" only as a data source. It has no guidance for recommending futures positions as an asset class. This task adds a `<derivatives_guidance>` section so the analyst can recommend ES, NQ, ZB, ZN, and related contracts.

---

## Scope

- Locate `MACRO_ANALYST_PROMPT` in `parrot/finance/prompts.py`
- Insert the `<derivatives_guidance>` block from spec §2.1 inside the prompt
- Add `options_opportunity_flag` and `options_opportunity_reason` to the macro analyst output schema within the prompt

**NOT in scope**: changes to any other analyst prompt.

---

## Files to Modify

| File | Action | Description |
|------|--------|-------------|
| `parrot/finance/prompts.py` | modify | Add `<derivatives_guidance>` block to `MACRO_ANALYST_PROMPT` and update its output schema |

---

## Guidance to Insert

Add the following block inside `MACRO_ANALYST_PROMPT`, after the existing data/tools section and before the output schema:

```xml
<derivatives_guidance>
FUTURES RECOMMENDATIONS

You can recommend index futures and bond futures when macro conditions favor them.

AVAILABLE FUTURES (via IBKR):
- ES (E-mini S&P 500) / MES (Micro E-mini S&P 500)
- NQ (E-mini Nasdaq-100) / MNQ (Micro E-mini Nasdaq-100)
- YM (E-mini Dow) / MYM (Micro E-mini Dow)
- ZB (30-Year Treasury Bond) / ZN (10-Year Treasury Note)
- ZF (5-Year Treasury Note) / ZT (2-Year Treasury Note)

WHEN TO RECOMMEND FUTURES OVER ETFs:
1. Leverage efficiency needed (futures = 5-10% margin vs 100% for ETF)
2. Tax efficiency (60/40 treatment for Section 1256 contracts)
3. 24-hour trading needed (macro event overnight)
4. Hedging existing equity exposure (short futures vs liquidating)
5. Duration plays on rates (ZN/ZB more precise than TLT)
6. Consider margin requirements when sizing futures recommendations.

OUTPUT FORMAT:
When recommending a futures position, use:
{
    "asset": "ES",
    "asset_class": "futures",
    "signal": "buy",
    "rationale": "Fed pivot + positive macro momentum favors S&P continuation",
    "contract_month": "nearest_quarterly",
    "micro_alternative": "MES"
}

FLAG FOR CIO:
Set `options_opportunity_flag: true` when:
- VIX > 25 and you see range-bound consolidation ahead (CIO may prefer options income)
- Your macro view is high-conviction but timing uncertain (options limit loss)
</derivatives_guidance>
```

Add to the macro analyst output schema:
```
"options_opportunity_flag": boolean — true if conditions favor options strategy (high IV, range-bound, hedge needed)
"options_opportunity_reason": string — brief explanation if flag is true (e.g., 'VIX > 25, range-bound consolidation expected')
```

---

## Acceptance Criteria

- [ ] `MACRO_ANALYST_PROMPT` contains `<derivatives_guidance>` XML block
- [ ] Prompt mentions ES, NQ, ZB, ZN futures by ticker
- [ ] Prompt mentions margin requirements consideration
- [ ] Prompt output schema includes `options_opportunity_flag` and `options_opportunity_reason`
- [ ] `ruff check parrot/finance/prompts.py` passes with no errors

---

## Agent Instructions

1. Read `parrot/finance/prompts.py` to locate `MACRO_ANALYST_PROMPT`
2. Insert the `<derivatives_guidance>` block from spec §2.1 (with margin note from open question resolution)
3. Add `options_opportunity_flag` and `options_opportunity_reason` fields to the output schema section
4. Run linter:
   ```bash
   source .venv/bin/activate
   ruff check parrot/finance/prompts.py
   ```
5. Confirm changes look correct before marking done
