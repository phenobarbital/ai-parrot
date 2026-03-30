# TASK-496: Intent Router Integration Tests

**Feature**: intent-router
**Spec**: `sdd/specs/intent-router.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-489, TASK-490, TASK-491, TASK-492, TASK-493, TASK-494
**Assigned-to**: unassigned

---

## Context

> Implements Module 8 from the spec. End-to-end routing scenarios that verify the full
> pipeline: query → routing → strategy execution → response. Covers HITL cycle, LLM
> Fallback with trace, exhaustive mode synthesis, cascade, and resolver demotion flow.

---

## Scope

- Create `tests/bots/test_intent_router_e2e.py` with integration tests:
  - **Dataset routing**: Query about data → DATASET strategy → DatasetManager → result.
  - **Graph routing**: Query about entity → GRAPH_PAGEINDEX → ontology pipeline → result.
  - **Vector fallback**: No dataset/graph match → VECTOR_SEARCH → existing RAG.
  - **LLM Fallback with trace**: No strategy returns results → FALLBACK with trace summary → LLM general knowledge.
  - **HITL cycle**: Ambiguous query → clarifying question → user reply → re-route.
  - **Cascade**: Primary fails → cascade to secondary → success.
  - **Exhaustive synthesis**: All strategies tried → non-empty results concatenated with labels → LLM synthesis.
  - **No strategies available**: Bare agent → skip routing → normal ask().
  - **Resolver demotion**: Graph strategy flows through demoted OntologyIntentResolver.

**NOT in scope**: Live API calls. All provider interactions mocked.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/bots/test_intent_router_e2e.py` | CREATE | End-to-end integration tests |

---

## Acceptance Criteria

- [ ] All 8+ e2e scenarios pass
- [ ] HITL cycle test: question → clarification → re-route verified
- [ ] LLM Fallback test: trace summary appears in fallback prompt
- [ ] Exhaustive test: concatenated context has strategy labels
- [ ] No strategies test: routing skipped, normal ask() behavior
- [ ] All tests pass: `pytest tests/bots/test_intent_router_e2e.py -v`

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-496-intent-router-integration-tests.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
