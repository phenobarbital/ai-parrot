# TASK-204: Add Flow-to-Recommendation Guidance to Sentiment Analyst Prompt

**Feature**: Analyst Derivatives Recommendations (FEAT-027)
**Spec**: `sdd/specs/finance-analyst-derivatives-prompts.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (1h)
**Depends-on**: none
**Assigned-to**: claude-session

---

## Context

The Sentiment Analyst currently analyzes options flow as an input signal but has no guidance on translating detected flow into actionable options recommendations. This task adds a `<derivatives_guidance>` section enabling the analyst to convert flow signals into recommendations.

---

## Scope

- Locate `SENTIMENT_ANALYST_PROMPT` in `parrot/finance/prompts.py`
- Insert the `<derivatives_guidance>` block from spec §2.3
- Add `options_opportunity_flag` and `options_opportunity_reason` to the sentiment analyst output schema within the prompt

**NOT in scope**: changes to any other analyst prompt.

---

## Files to Modify

| File | Action | Description |
|------|--------|-------------|
| `parrot/finance/prompts.py` | modify | Add `<derivatives_guidance>` block to `SENTIMENT_ANALYST_PROMPT` and update its output schema |

---

## Guidance to Insert

Add the following block inside `SENTIMENT_ANALYST_PROMPT`, after the existing flow analysis section and before the output schema:

```xml
<derivatives_guidance>
OPTIONS FLOW TRANSLATION

You analyze options flow data. When you detect significant flow signals, you can
translate them into actionable recommendations.

FLOW SIGNALS TO RECOMMENDATIONS:

| Flow Signal | Interpretation | Recommendation |
|-------------|----------------|----------------|
| Unusual call buying (large premium, OTM) | Smart money bullish | Flag bullish, consider long calls |
| Unusual put buying (large premium, OTM) | Smart money bearish/hedging | Flag bearish or hedge |
| IV spike without news | Anticipated event | Flag options_opportunity (premium selling after event) |
| Put/call ratio extreme (> 1.5) | Fear elevated | Contrarian bullish signal |
| Call/put ratio extreme (< 0.5) | Complacency | Contrarian bearish signal |
| Gamma exposure flip | Dealer hedging shifts | Volatility regime change |

OUTPUT FORMAT:
When flow suggests options positioning:
{
    "asset": "NVDA",
    "asset_class": "options",
    "signal": "buy",
    "flow_signal": "unusual_call_sweep",
    "flow_premium": 2500000,
    "flow_interpretation": "Large institutional call buying ahead of earnings",
    "rationale": "Follow smart money flow"
}

FLAG FOR CIO:
Set `options_opportunity_flag: true` when:
- You detect elevated IV that may contract (post-catalyst setup)
- Flow suggests institutional hedging activity (CIO may want to sell premium)
- Gamma exposure indicates upcoming volatility (CIO may avoid premium selling)
</derivatives_guidance>
```

Add to the sentiment analyst output schema:
```
"options_opportunity_flag": boolean — true if flow conditions favor options strategy
"options_opportunity_reason": string — brief explanation if flag is true (e.g., 'IV spike detected, post-catalyst premium selling opportunity')
```

---

## Acceptance Criteria

- [ ] `SENTIMENT_ANALYST_PROMPT` contains `<derivatives_guidance>` XML block
- [ ] Prompt includes flow signal table (unusual call/put buying, IV spike, P/C ratio, gamma flip)
- [ ] Prompt output schema includes `options_opportunity_flag` and `options_opportunity_reason`
- [ ] `ruff check parrot/finance/prompts.py` passes with no errors

---

## Agent Instructions

1. Read `parrot/finance/prompts.py` to locate `SENTIMENT_ANALYST_PROMPT`
2. Insert the `<derivatives_guidance>` block from spec §2.3
3. Add `options_opportunity_flag` and `options_opportunity_reason` fields to the output schema section
4. Run linter:
   ```bash
   source .venv/bin/activate
   ruff check parrot/finance/prompts.py
   ```
5. Confirm changes look correct before marking done
