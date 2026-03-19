# TASK-186: Sentiment Analyst Derivatives Guidance

**Feature**: FEAT-027 (Analyst Derivatives Recommendations)
**Spec**: `sdd/specs/finance-analyst-derivatives-prompts.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (1-2h)
**Depends-on**: none
**Assigned-to**: claude-session
**Completed**: 2026-03-05

---

## Context

> Add `<derivatives_guidance>` section to the Sentiment Analyst prompt for
> translating options flow signals into actionable recommendations.

---

## Scope

- Locate the Sentiment Analyst prompt in `prompts.py`
- Add `<derivatives_guidance>` XML block with:
  - Flow signals to recommendations table (unusual call/put buying, IV spike, etc.)
  - Output format for flow-based options recommendations
  - `options_opportunity_flag` guidance for CIO awareness

**NOT in scope**: Changes to other analyst prompts, schema changes.

---

## Files to Create / Modify

| File | Action | Description |
|------|--------|-------------|
| `parrot/finance/prompts.py` | MODIFY | Add `<derivatives_guidance>` to Sentiment Analyst |

---

## Implementation Notes

The Sentiment Analyst already analyzes "options flow" — this task adds the
translation layer from flow observation to recommendation.

Key flow signals:
- Unusual call/put buying → directional signal
- IV spike without news → event anticipation
- Put/call ratio extremes → contrarian signals
- Gamma exposure flip → volatility regime change

---

## Acceptance Criteria

- [x] Sentiment Analyst prompt contains `<derivatives_guidance>` block
- [x] Flow signals table with interpretations present
- [x] Output format shows `flow_signal` and `flow_interpretation` fields
- [x] `options_opportunity_flag` guidance included
- [x] `ruff check parrot/finance/prompts.py` passes

---

## Agent Instructions

1. Read the Sentiment Analyst prompt section in `prompts.py`
2. Identify insertion point (after `</sources_priority>`, before `<output_format>`)
3. Add the `<derivatives_guidance>` block from the spec (Section 2.3)
4. Run `ruff check parrot/finance/prompts.py`

---

## Completion Note

**Completed**: 2026-03-05
**Implemented by**: claude-session

### Summary

Added `<derivatives_guidance>` section to the Sentiment Analyst prompt for translating
options flow signals into actionable recommendations.

### Changes

1. **New section**: `<derivatives_guidance>` with OPTIONS FLOW TRANSLATION framework
2. **Flow signals table**: 8 signal types with interpretation and recommendation
   - Unusual call/put buying
   - IV spike without news
   - Put/call ratio extremes
   - Gamma exposure flip
   - Sweep orders
   - Dark pool + options activity
3. **Output schema updated**:
   - `asset_class` now includes `'options'`
   - Added `flow_signal`, `flow_premium`, `flow_interpretation` fields
   - Added `options_opportunity_flag` and `options_opportunity_reason`

### Verification

```bash
ruff check parrot/finance/prompts.py  # All checks passed
grep -c "derivatives_guidance" parrot/finance/prompts.py  # 6 (3 analysts done)
```
