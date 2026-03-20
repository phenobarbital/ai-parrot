# TASK-187: Risk Analyst Derivatives Guidance

**Feature**: FEAT-027 (Analyst Derivatives Recommendations)
**Spec**: `sdd/specs/finance-analyst-derivatives-prompts.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: claude-session

---

## Context

> Add `<derivatives_guidance>` section to the Risk Analyst prompt for
> recommending hedges via options and futures.

---

## Scope

- Locate the Risk Analyst prompt in `prompts.py`
- Add `<derivatives_guidance>` XML block with:
  - Hedging strategies (portfolio protection, sector hedge, single-stock, futures hedge, collar)
  - When to recommend derivatives table (VAR > limit, correlation spike, concentration, etc.)
  - `hedge_recommendation` output format
  - `options_opportunity_flag` guidance for CIO awareness

**NOT in scope**: Changes to other analyst prompts, schema changes.

---

## Files to Create / Modify

| File | Action | Description |
|------|--------|-------------|
| `parrot/finance/prompts.py` | MODIFY | Add `<derivatives_guidance>` to Risk Analyst |

---

## Implementation Notes

The Risk Analyst already has `<options_risk_tools>` for analyzing existing
options positions. This task adds the **recommendation** capability — when
to suggest NEW derivatives for hedging.

Key hedge types:
1. Portfolio protection — SPY puts, VIX calls
2. Sector hedge — XLF/XLE/XLK puts
3. Single-stock hedge — individual puts
4. Futures hedge — short ES/NQ to reduce beta
5. Collar — protect gains + generate income

Insert after `</options_risk_tools>` block for logical flow.

---

## Acceptance Criteria

- [x] Risk Analyst prompt contains `<derivatives_guidance>` block
- [x] Five hedging strategies documented
- [x] "When to recommend derivatives" table present
- [x] `hedge_recommendation` output format included
- [x] `options_opportunity_flag` guidance included
- [x] `ruff check parrot/finance/prompts.py` passes

---

## Agent Instructions

1. Read the Risk Analyst prompt section in `prompts.py`
2. Identify insertion point (after `</options_risk_tools>`, before `</instructions>`)
3. Add the `<derivatives_guidance>` block from the spec (Section 2.4)
4. Run `ruff check parrot/finance/prompts.py`
