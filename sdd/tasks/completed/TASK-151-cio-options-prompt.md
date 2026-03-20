# TASK-151: CIO Options Strategy Prompt

**Feature**: Multi-Leg Options Strategy Execution (FEAT-023)
**Spec**: `sdd/specs/options-multi-leg-strategies.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: S (2h)
**Depends-on**: TASK-146, TASK-147
**Assigned-to**: claude-session
**Completed**: 2026-03-04

---

## Context

> Update CIO agent prompt to include options strategy decision framework.
> CIO must know when to use Iron Butterfly vs Iron Condor based on market conditions.

---

## Scope

- Add `<options_strategies>` section to CIO prompt in `parrot/finance/prompts.py`
- Document available strategy tools
- Provide decision framework (IV percentile, market outlook)
- Include risk limits (max % per strategy, total options exposure)
- Add usage examples

**NOT in scope**: Tool implementation (already done), Risk Analyst updates.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/finance/prompts.py` | MODIFY | Add CIO_OPTIONS_STRATEGIES_PROMPT |

---

## Implementation Notes

### Decision Framework

| Condition | Strategy | Rationale |
|-----------|----------|-----------|
| IV percentile > 70 | Iron Butterfly | Maximize IV crush credit |
| IV percentile 40-70 | Iron Condor | Balance credit vs. probability |
| Clear range, low IV | Iron Condor | Wide wings for safety |
| Post-catalyst | Iron Butterfly | Capture vol contraction |

### Risk Limits
- Maximum 5% of portfolio in any single options strategy
- Maximum 15% total options exposure
- Minimum 14 DTE, maximum 45 DTE
- Only trade underlyings with sufficient liquidity

---

## Acceptance Criteria

- [x] `<options_strategies>` section added to CIO prompt
- [x] Both strategies documented with use cases
- [x] Decision framework table included
- [x] Risk limits clearly stated
- [x] Tool usage examples provided
- [x] Integrated into full CIO prompt composition

---

## Completion Note

Added comprehensive options strategy guidance to the CIO agent prompt:

1. **CIO_OPTIONS_STRATEGIES_PROMPT** (standalone constant, 3942 chars):
   - Reusable constant for composition with other agents
   - Complete documentation of Iron Butterfly and Iron Condor strategies
   - Can be imported independently for TASK-153 (Risk Analyst)

2. **CIO_ARBITER** (updated, 9010 chars total):
   - Embedded `<options_strategies>` section after `</mandate>` tag
   - Integrated with CIO deliberation workflow

**Content Added:**

- **AVAILABLE STRATEGIES**: Iron Butterfly, Iron Condor with structure, use cases, P&L
- **STRATEGY SELECTION FRAMEWORK**: Decision table based on IV percentile and market conditions
- **RISK LIMITS**: 5% per strategy, 15% total, 14-45 DTE, liquidity requirements
- **WHEN TO USE/AVOID**: Clear conditions for recommending or avoiding options
- **TOOL USAGE EXAMPLES**: Two complete JSON examples with rationale
- **INTEGRATION WITH DELIBERATION**: How to incorporate into consensus_assessment and revision_requests

Verified: Both `CIO_ARBITER` and `CIO_OPTIONS_STRATEGIES_PROMPT` import successfully.
