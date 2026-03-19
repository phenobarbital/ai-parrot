# TASK-206: Add Futures Awareness Note to Crypto Analyst Prompt

**Feature**: Analyst Derivatives Recommendations (FEAT-027)
**Spec**: `sdd/specs/finance-analyst-derivatives-prompts.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: S (30min)
**Depends-on**: none
**Assigned-to**: claude-session

---

## Context

The spec (§2 Integration Points) calls for a note about futures awareness in the Crypto Analyst prompt. Crypto derivatives (Binance perps, etc.) are explicitly out of scope per the spec, but the analyst should be aware of the concept and set the `options_opportunity_flag` when relevant. This is the lightest-touch change across all analysts.

---

## Scope

- Locate `CRYPTO_ANALYST_PROMPT` in `parrot/finance/prompts.py`
- Add a brief `<derivatives_guidance>` note (limited scope — no crypto perps per spec decision)
- Add `options_opportunity_flag` and `options_opportunity_reason` to the crypto analyst output schema within the prompt

**NOT in scope**: crypto perpetual futures or options recommendations (deferred per spec §7).

---

## Files to Modify

| File | Action | Description |
|------|--------|-------------|
| `parrot/finance/prompts.py` | modify | Add limited `<derivatives_guidance>` note to `CRYPTO_ANALYST_PROMPT` and update its output schema |

---

## Guidance to Insert

Add the following block inside `CRYPTO_ANALYST_PROMPT`, before the output schema:

```xml
<derivatives_guidance>
DERIVATIVES AWARENESS (LIMITED SCOPE)

Crypto derivatives (perpetual futures, options on Binance/Deribit) are NOT in scope
for your recommendations due to regulatory complexity.

However, set `options_opportunity_flag: true` when:
- You observe extreme spot market volatility that would benefit from hedging
- Correlation between crypto and traditional assets creates cross-asset opportunities

When flagging, use `options_opportunity_reason` to describe the condition briefly.
The CIO will determine whether traditional derivatives (ES futures, SPY puts) apply
as a cross-asset hedge.
</derivatives_guidance>
```

Add to the crypto analyst output schema:
```
"options_opportunity_flag": boolean — true if cross-asset derivatives opportunity is identified
"options_opportunity_reason": string — brief explanation if flag is true
```

---

## Acceptance Criteria

- [ ] `CRYPTO_ANALYST_PROMPT` contains `<derivatives_guidance>` XML block
- [ ] Note explicitly states crypto perps are out of scope
- [ ] Prompt output schema includes `options_opportunity_flag` and `options_opportunity_reason`
- [ ] `ruff check parrot/finance/prompts.py` passes with no errors

---

## Agent Instructions

1. Read `parrot/finance/prompts.py` to locate `CRYPTO_ANALYST_PROMPT`
2. Insert the limited `<derivatives_guidance>` note above
3. Add `options_opportunity_flag` and `options_opportunity_reason` fields to the output schema section
4. Run linter:
   ```bash
   source .venv/bin/activate
   ruff check parrot/finance/prompts.py
   ```
5. Confirm changes look correct before marking done
