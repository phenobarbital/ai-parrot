# TASK-185: Equity Analyst Derivatives Guidance

**Feature**: FEAT-027 (Analyst Derivatives Recommendations)
**Spec**: `sdd/specs/finance-analyst-derivatives-prompts.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: claude-session

---

## Context

> Add `<derivatives_guidance>` section to the Equity Analyst prompt with options
> recommendation capabilities (covered calls, protective puts, collars, long calls/puts).

---

## Scope

- Locate the Equity Analyst prompt in `prompts.py`
- Add `<derivatives_guidance>` XML block with:
  - Available strategies: covered call, protective put, long call/put, collar
  - When to recommend options over stock (table format)
  - Output format for options recommendations (delta, DTE suggestions)
  - `options_opportunity_flag` guidance for CIO awareness
- Delta targets left to CIO discretion (per Open Questions)

**NOT in scope**: Changes to other analyst prompts, schema changes.

---

## Files to Create / Modify

| File | Action | Description |
|------|--------|-------------|
| `parrot/finance/prompts.py` | MODIFY | Add `<derivatives_guidance>` to Equity Analyst |

---

## Implementation Notes

Insert the `<derivatives_guidance>` block after the `</sources_priority>` tag and
before the `<output_format>` tag in the Equity Analyst prompt.

Key strategies:
1. Covered call — income on existing positions
2. Protective put — hedge existing positions
3. Long call/put — directional with defined risk
4. Collar — protection + income

Decision table format for "when to use options over stock".

---

## Acceptance Criteria

- [x] Equity Analyst prompt contains `<derivatives_guidance>` block
- [x] Four strategies documented (covered call, protective put, long call/put, collar)
- [x] Decision table for "options vs stock" present
- [x] Output format shows `asset_class: options` with strategy field
- [x] `options_opportunity_flag` guidance included
- [x] `ruff check parrot/finance/prompts.py` passes

---

## Agent Instructions

1. Read the Equity Analyst prompt section in `prompts.py`
2. Identify insertion point (after `</sources_priority>`, before `<output_format>`)
3. Add the `<derivatives_guidance>` block from the spec (Section 2.2)
4. Run `ruff check parrot/finance/prompts.py`
5. Verify with grep: `grep -A5 "derivatives_guidance" parrot/finance/prompts.py | grep -i "covered"`
