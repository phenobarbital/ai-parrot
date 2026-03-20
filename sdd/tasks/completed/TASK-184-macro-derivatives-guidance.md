# TASK-184: Macro Analyst Derivatives Guidance

**Feature**: FEAT-027 (Analyst Derivatives Recommendations)
**Spec**: `sdd/specs/finance-analyst-derivatives-prompts.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: claude-session
**Completed**: 2026-03-05

---

## Context

> Add `<derivatives_guidance>` section to the Macro Analyst prompt with futures
> recommendation capabilities (ES, NQ, ZB, ZN, micro alternatives).

---

## Scope

- Locate the Macro Analyst prompt in `prompts.py`
- Add `<derivatives_guidance>` XML block with:
  - Available futures list (ES, NQ, YM, ZB, ZN, ZF, ZT + micro versions)
  - When to recommend futures over ETFs (leverage, tax, 24h, hedging, duration)
  - Output format for futures recommendations
  - `options_opportunity_flag` guidance for CIO awareness
- Add margin consideration note (per Open Questions)

**NOT in scope**: Changes to other analyst prompts, schema changes, CIO changes.

---

## Files to Create / Modify

| File | Action | Description |
|------|--------|-------------|
| `parrot/finance/prompts.py` | MODIFY | Add `<derivatives_guidance>` to Macro Analyst |

---

## Implementation Notes

Insert the `<derivatives_guidance>` block after the `</instructions>` tag and before
the `<output_format>` tag in the Macro Analyst prompt.

Key futures to include:
- Index: ES/MES, NQ/MNQ, YM/MYM
- Bonds: ZB, ZN, ZF, ZT

Include margin awareness: "Consider margin requirements (~5-10% for index futures)
when sizing recommendations."

---

## Acceptance Criteria

- [x] Macro Analyst prompt contains `<derivatives_guidance>` block
- [x] Futures list includes ES, NQ, YM, ZB, ZN with micro alternatives
- [x] "When to recommend futures over ETFs" section present
- [x] Output format shows `asset_class: futures` example
- [x] `options_opportunity_flag` guidance included
- [x] Margin consideration mentioned
- [x] `ruff check parrot/finance/prompts.py` passes

---

## Agent Instructions

1. Read the Macro Analyst prompt section in `prompts.py`
2. Identify insertion point (after `</instructions>`, before `<output_format>`)
3. Add the `<derivatives_guidance>` block from the spec (Section 2.1)
4. Add margin note per Open Questions answer
5. Run `ruff check parrot/finance/prompts.py`
6. Verify with grep: `grep -c "derivatives_guidance" parrot/finance/prompts.py`

---

## Completion Note

**Completed**: 2026-03-05
**Implemented by**: claude-session

### Summary

Added `<derivatives_guidance>` section to the Macro Analyst prompt (`ANALYST_MACRO` in `prompts.py`).

### Changes

1. **New section**: `<derivatives_guidance>` added after `</instructions>`, before `<output_format>`
2. **Futures list**: ES/MES, NQ/MNQ, YM/MYM (index), ZB, ZN, ZF, ZT (bonds)
3. **When to use futures**: 5 criteria (leverage, tax, 24h trading, hedging, duration)
4. **Margin note**: ~5-10% for index futures, ~3-5% for micros
5. **Output schema updated**:
   - `asset_class` now includes `'futures'`
   - Added `contract_month` and `micro_alternative` fields
   - Added `options_opportunity_flag` and `options_opportunity_reason` fields

### Verification

```bash
ruff check parrot/finance/prompts.py  # All checks passed
grep -c "derivatives_guidance" parrot/finance/prompts.py  # 2 (open/close tags)
```
