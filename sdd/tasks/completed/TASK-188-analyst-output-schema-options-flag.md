# TASK-188: Analyst Output Schema Options Flag

**Feature**: FEAT-027 (Analyst Derivatives Recommendations)
**Spec**: `sdd/specs/finance-analyst-derivatives-prompts.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (1-2h)
**Depends-on**: TASK-184, TASK-185, TASK-186, TASK-187
**Assigned-to**: claude-session
**Completed**: 2026-03-05

---

## Context

> Update all analyst output schemas in their prompts to include
> `options_opportunity_flag` and `options_opportunity_reason` fields.

---

## Scope

- Locate the `<output_format>` section of each analyst prompt
- Add two new fields to each analyst's JSON schema:
  - `options_opportunity_flag`: boolean
  - `options_opportunity_reason`: string (explanation when flag is true)
- Analysts affected: Macro, Equity, Crypto, Sentiment, Risk

**NOT in scope**: Changes to dataclass schemas (prompt-only), CIO changes.

---

## Files to Create / Modify

| File | Action | Description |
|------|--------|-------------|
| `parrot/finance/prompts.py` | MODIFY | Add options flag fields to all 5 analyst output schemas |

---

## Implementation Notes

Each analyst prompt has an `<output_format>` section with a JSON schema.
Add these fields to each:

```json
{
    "...existing fields...",
    "options_opportunity_flag": "boolean — true if conditions favor options strategy",
    "options_opportunity_reason": "string — brief explanation if flag is true"
}
```

Place these fields near the end of the schema, before the closing brace.

---

## Acceptance Criteria

- [x] Macro Analyst output schema has `options_opportunity_flag` and `options_opportunity_reason`
- [x] Equity Analyst output schema has `options_opportunity_flag` and `options_opportunity_reason`
- [x] Crypto Analyst output schema has `options_opportunity_flag` and `options_opportunity_reason`
- [x] Sentiment Analyst output schema has `options_opportunity_flag` and `options_opportunity_reason`
- [x] Risk Analyst output schema has `options_opportunity_flag` and `options_opportunity_reason`
- [x] `ruff check parrot/finance/prompts.py` passes

---

## Agent Instructions

1. Read each analyst's `<output_format>` section in `prompts.py`
2. For each analyst (macro, equity, crypto, sentiment, risk):
   - Find the JSON schema in `<output_format>`
   - Add the two new fields before the closing `}`
3. Run `ruff check parrot/finance/prompts.py`
4. Verify: `grep -c "options_opportunity_flag" parrot/finance/prompts.py` should return 5+

---

## Completion Note

**Completed**: 2026-03-05
**Implemented by**: claude-session

### Summary

Verified and ensured all 5 analyst output schemas have `options_opportunity_flag` and
`options_opportunity_reason` fields.

### Changes

Previous tasks (TASK-184, 185, 186, 187) already added the fields to 4 analysts.
This task added the missing fields to the **Crypto Analyst**:

```json
"options_opportunity_flag": "boolean — true if crypto derivatives opportunity exists (perpetual futures, high funding rates)",
"options_opportunity_reason": "string — brief explanation if flag is true (e.g., 'BTC funding rate extreme, mean reversion trade via perps')"
```

### Verification

```bash
ruff check parrot/finance/prompts.py  # All checks passed
grep -c "options_opportunity_flag" parrot/finance/prompts.py  # 9 (5 in output schemas, 4 in guidance)
grep -c "options_opportunity_reason" parrot/finance/prompts.py  # 5 (1 per analyst)
```

### All 5 Analysts Confirmed

| Analyst | options_opportunity_flag | options_opportunity_reason |
|---------|-------------------------|---------------------------|
| Macro | ✅ | ✅ |
| Equity | ✅ | ✅ |
| Crypto | ✅ (added this task) | ✅ (added this task) |
| Sentiment | ✅ | ✅ |
| Risk | ✅ | ✅ |
