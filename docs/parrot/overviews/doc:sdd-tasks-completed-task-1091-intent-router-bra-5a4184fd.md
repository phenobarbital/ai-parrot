---
type: Wiki Overview
title: 'TASK-1091: IntentRouterMixin Branch Logic'
id: doc:sdd-tasks-completed-task-1091-intent-router-branch-logic-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'from parrot.bots.mixins.intent_router import IntentRouterMixin # verified:
  intent_router.py:107'
relates_to:
- concept: mod:parrot
  rel: mentions
- concept: mod:parrot.bots.mixins.intent_router
  rel: mentions
- concept: mod:parrot.knowledge.ontology.schema
  rel: mentions
---

# TASK-1091: IntentRouterMixin Branch Logic

**Feature**: FEAT-159 — Concept-Document Authority Layer
**Spec**: `sdd/specs/concept-document-authority.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1090
**Assigned-to**: unassigned

---

## Context

> Module 8 of the spec. Minor refinement to `IntentRouterMixin._run_graph_pageindex`
> so that unscoped `PageIndexRetriever.retrieve(prompt)` is only called when the
> ontology degradation chain returns `state="ok"` with BOTH `graph_context` and
> `vector_context` empty (i.e., no concept modeled AND vector retrieval returned nothing).
> Otherwise, the envelope's context is formatted with provenance and passed through.

---

## Scope

- Modify `packages/ai-parrot/src/parrot/bots/mixins/intent_router.py`:
  - In `_run_graph_pageindex` (line 615), refine the branch logic on `ContextEnvelope.state`:
    - `state="ok"` with populated `graph_context` or `vector_context` → format and return with provenance.
    - `state="ok"` with both empty → fall back to unscoped `PageIndexRetriever.retrieve(prompt)`.
    - Other states → pass through (already handled by FEAT-158).
- Write unit tests for both branches.

**NOT in scope**: Modifying `ontology_process` (TASK-1090), modifying PageIndex (TASK-1089), YAML changes (TASK-1084).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/mixins/intent_router.py` | MODIFY | Refine branch logic in _run_graph_pageindex |
| `packages/ai-parrot/tests/bots/test_intent_router_branch.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.mixins.intent_router import IntentRouterMixin  # verified: intent_router.py:107
from parrot.pageindex.retriever import PageIndexRetriever  # verified: retriever.py:11
# FEAT-158 additions:
from parrot.knowledge.ontology.schema import ContextEnvelope, EnrichedContext
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/mixins/intent_router.py:107
class IntentRouterMixin:
    async def _run_graph_pageindex(
        self,
        prompt: str,
        candidates: list,  # RouterCandidate
    ) -> Optional[str]:  # line 615
        # After FEAT-158 refactor: forwards user_context + tenant_id to ontology_process.
        # This task refines what happens AFTER ontology_process returns.

# packages/ai-parrot/src/parrot/pageindex/retriever.py:11
class PageIndexRetriever:
    async def retrieve(
        self,
        query: str,
        pdf_pages: Optional[list[tuple[str, int]]] = None,
    ) -> str:  # line 81
        # This is the UNSCOPED fallback — searches all trees.
```

### Does NOT Exist
- ~~`_run_graph_pageindex` already branching on `ContextEnvelope.state`~~ — FEAT-158 adds the call to `ontology_process` and basic error handling; this task refines the branch on `state="ok"` with empty vs populated context
- ~~`ContextEnvelope` on `dev` today~~ — added by FEAT-158

---

## Implementation Notes

### Branch logic
```python
async def _run_graph_pageindex(self, prompt, candidates):
    # ... existing setup ...

    envelope = await self.ontology_process(prompt, user_context, tenant_id, domain)

    # Refined branching:
    if envelope.state == "ok":
        has_graph = envelope.context and envelope.context.graph_context
        has_vector = envelope.context and envelope.context.vector_context
        if has_graph or has_vector:
            # Format with provenance (source label)
            return self._format_envelope_context(envelope)
        else:
            # Degradation chain returned nothing — last resort: unscoped PageIndex
            return await self._pageindex_retriever.retrieve(prompt)

    # Other states (ambiguous, denied, etc.) — handled by FEAT-158
    # ...
```

### Key Constraints
- This is a MINOR change — do not restructure the method.
- Unscoped PageIndex is the absolute last resort, only for queries where no concept is modeled.
- Verify how `_run_graph_pageindex` currently handles the return from `ontology_process` after FEAT-158 lands.
- The provenance formatting should include `envelope.context.source` in the output.

### References in Codebase
- `packages/ai-parrot/src/parrot/bots/mixins/intent_router.py:615` — the method to modify
- `packages/ai-parrot/src/parrot/knowledge/ontology/mixin.py` — `ontology_process` return type

---

## Acceptance Criteria

- [ ] `state="ok"` with populated graph_context → formatted output with provenance, no unscoped PageIndex call
- [ ] `state="ok"` with empty graph + empty vector → unscoped `PageIndexRetriever.retrieve(prompt)` called
- [ ] Other envelope states pass through to FEAT-158's handling
- [ ] Provenance (`context.source`) is included in formatted output
- [ ] All tests pass: `pytest packages/ai-parrot/tests/bots/test_intent_router_branch.py -v`

---

## Test Specification

```python
# packages/ai-parrot/tests/bots/test_intent_router_branch.py
import pytest
from unittest.mock import AsyncMock, MagicMock


class TestIntentRouterBranchLogic:
    async def test_state_ok_with_graph_context(self):
        """state=ok + graph_context populated → formatted with provenance, no unscoped PageIndex."""

    async def test_state_ok_empty_envelope(self):
        """state=ok + empty graph + empty vector → unscoped PageIndex called."""

    async def test_state_ambiguous_passthrough(self):
        """state=ambiguous → FEAT-158 handling, no unscoped PageIndex."""
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-1090 is in `tasks/completed/`
3. **CRITICAL**: Verify FEAT-158 has landed and refactored `_run_graph_pageindex`
4. **Verify the Codebase Contract** — before writing ANY code:
   - Read `intent_router.py` around line 615 to see FEAT-158's refactored version
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
5. **Update status** in `sdd/tasks/index/concept-document-authority.json` → `"in-progress"` with your session ID
6. **Implement** following the scope, codebase contract, and notes above
7. **Verify** all acceptance criteria are met
8. **Move this file** to `sdd/tasks/completed/TASK-1091-intent-router-branch-logic.md`
9. **Update index** → `"done"`
10. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
