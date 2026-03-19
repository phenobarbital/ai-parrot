# TASK-141: Options Strategy Schemas

**Feature**: Multi-Leg Options Strategy Execution (FEAT-023)
**Spec**: `sdd/specs/options-multi-leg-strategies.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (1-2h)
**Depends-on**: none
**Assigned-to**: claude-session
**Completed**: 2026-03-04

---

## Context

> Define Pydantic schemas for options strategies. These schemas are foundational
> and must be created first so other tasks can import and use them.

---

## Scope

- Add to `parrot/finance/schemas.py`:
  - `OptionsLeg` — Single leg with contract details and Greeks
  - `OptionsPosition` — Multi-leg position with aggregated Greeks
  - `OptionsStrategyConfig` — Configuration for building strategies
  - `OptionsStrategyRecommendation` — CIO recommendation output
  - `StrategyLeg` — Lightweight leg config for StrategyFactory

**NOT in scope**: Execution logic, API calls.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/finance/schemas.py` | MODIFY | Add 5 new Pydantic models |

---

## Implementation Notes

### Key Constraints
- Use `Literal` types for strategy_type, contract_type, side
- All price fields should be `float`
- Greeks fields should be `float | None` (may not always be available)
- Include proper Field descriptions for tool schema generation

### References in Codebase
- Existing `PortfolioSnapshot` in same file for pattern reference
- `ResearchBriefing` for complex nested model example

---

## Acceptance Criteria

- [x] `OptionsLeg` model defined with all fields from spec
- [x] `OptionsPosition` model includes aggregated Greeks fields
- [x] `OptionsStrategyConfig` has proper validation (ge, le constraints)
- [x] `OptionsStrategyRecommendation` includes confidence field 0-1
- [x] All models have proper Field descriptions
- [x] Models are exported in `__all__` (implicitly via module import)

---

## Completion Note

Added 5 Pydantic models to `parrot/finance/schemas.py` (Section 10):

1. **StrategyLeg** - Lightweight leg config for StrategyFactory
2. **OptionsLeg** - Full contract details with Greeks
3. **OptionsPosition** - Multi-leg position with aggregated Greeks/P&L
4. **OptionsStrategyConfig** - Strategy builder configuration with validation
5. **OptionsStrategyRecommendation** - CIO recommendation output

All models use `pydantic.Field` with descriptions for tool schema generation.
Validation tested: expiration_days (7-60), short_delta (0.15-0.45), confidence (0-1).

---
**Verification (2026-03-05)**:
- Verified schemas in `parrot/finance/schemas.py`.
- Added explicit `__all__` export to `parrot/finance/schemas.py` (including all 5 models).
- Created `tests/finance/test_options_schemas.py` and verified all models and validations pass (9 tests).

