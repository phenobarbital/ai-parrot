# TASK-495: Intent Router Unit Tests

**Feature**: intent-router
**Spec**: `sdd/specs/intent-router.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-489, TASK-490, TASK-491, TASK-492, TASK-493, TASK-494
**Assigned-to**: unassigned

---

## Context

> Implements Module 7 from the spec. Comprehensive unit tests for all components:
> models, registry, mixin, bot touch-point, auto-registration, resolver demotion.
> Individual tasks already include basic tests — this task covers cross-cutting
> scenarios and ensures full coverage.

---

## Scope

- Review and extend tests from individual tasks.
- Add cross-cutting unit tests:
  - Registry + auto-registration from real DataSource/Tool objects.
  - Mixin strategy discovery with various agent configurations.
  - Cascade chain: primary → cascade1 → cascade2 → FALLBACK.
  - Exhaustive mode with mixed results (some strategies return data, some don't).
  - HITL threshold edge cases (exactly at threshold, just below, just above).
  - RoutingTrace completeness (all strategies recorded, timing, produced_context).
  - MRO correctness: verify IntentRouterMixin.conversation() is called when MRO is correct.

**NOT in scope**: End-to-end integration tests (TASK-496).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/registry/test_capability_models.py` | MODIFY | Extend if needed |
| `tests/registry/test_capability_registry.py` | MODIFY | Extend with auto-registration |
| `tests/bots/test_intent_router.py` | MODIFY | Extend with cross-cutting scenarios |
| `tests/bots/test_abstractbot_routing.py` | MODIFY | Extend if needed |

---

## Acceptance Criteria

- [ ] All unit tests from Tasks 489-494 pass
- [ ] Cross-cutting cascade/exhaustive/HITL scenarios covered
- [ ] RoutingTrace completeness verified
- [ ] Full test suite: `pytest tests/registry/ tests/bots/test_intent_router*.py tests/bots/test_abstractbot_routing.py -v`

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-495-intent-router-unit-tests.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
