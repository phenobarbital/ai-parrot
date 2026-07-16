---
type: Wiki Overview
title: 'TASK-1077: Wire IntentRouterMixin._run_graph_pageindex to forward user_context
  and tenant_id'
id: doc:sdd-tasks-completed-task-1077-intent-router-forward-context-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Spec §3 Module 7, §6 Codebase Contract (Does NOT Exist), §5 Acceptance Criteria.
  Today''s call site at `intent_router.py:636` is `await ontology_process(prompt)`
  — a single positional arg against a signature that requires three. The call is wrapped
  in `try/except Exception: pass` '
relates_to:
- concept: mod:parrot.knowledge.ontology.schema
  rel: mentions
---

# TASK-1077: Wire IntentRouterMixin._run_graph_pageindex to forward user_context and tenant_id

**Feature**: FEAT-158 — Ontology Entity Extraction & Tool-Call Dispatch
**Spec**: `sdd/specs/ontology-entity-extraction.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1076
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 7, §6 Codebase Contract (Does NOT Exist), §5 Acceptance Criteria. Today's call site at `intent_router.py:636` is `await ontology_process(prompt)` — a single positional arg against a signature that requires three. The call is wrapped in `try/except Exception: pass` at line 639, so the ontology strategy silently dies and the router falls through to direct graph-store query. This is the production gap that hides the entire ontology feature.

After this task, `ontology_process` actually receives `(query, user_context, tenant_id)` and the silent swallow is replaced with a narrow, logged catch — same fallthrough semantics, but visible errors.

---

## Scope

- Modify `packages/ai-parrot/src/parrot/bots/mixins/intent_router.py`:
  - Update `_run_graph_pageindex` so the ontology call becomes:
    ```python
    perm_ctx = self._get_permission_context() if hasattr(self, "_get_permission_context") else {}
    tenant_id = getattr(self, "_tenant_id", "default")
    result = await ontology_process(prompt, user_context=perm_ctx, tenant_id=tenant_id)
    ```
  - Replace the broad `try/except Exception: pass` (line 639) for THIS call path with a narrow catch that LOGS the exception at warning level before falling through. Do NOT silence errors silently.
  - Adapt the `result` handling for `ContextEnvelope` (TASK-1076 widened the return type):
    - If `result.state == "ok"` and `result.context is not None`, return a string suitable for the router (use the existing serialization convention — `str(result)` is fine if `ContextEnvelope` has a meaningful `__str__`; otherwise convert `result.context` to the router's expected format).
    - For non-`ok` states (ambiguous, denied, auth_required, etc.), return a string that the router/agent can present back to the user.
- Add a unit test verifying the forwarding via a spy.

**NOT in scope**:
- Changing other strategy runners (`_run_dataset_query`, etc.).
- The `_get_permission_context` hook itself (added in TASK-1076).
- Modifying `OntologyRAGMixin` (TASK-1076).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/mixins/intent_router.py` | MODIFY | Update `_run_graph_pageindex` — lines 615-640. |
| `packages/ai-parrot/tests/test_intent_router_e2e.py` OR `test_intent_router_unit.py` | MODIFY | Add forwarding test. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.knowledge.ontology.schema import ContextEnvelope     # NEW from TASK-1071
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/bots/mixins/intent_router.py:107
class IntentRouterMixin:
    async def _run_graph_pageindex(
        self, prompt: str, candidates: list[RouterCandidate],
    ) -> Optional[str]:                                          # lines 615-640
        # CURRENT BEHAVIOR (to be fixed):
        #   ontology_process = getattr(self, "ontology_process", None)
        #   if ontology_process:
        #       try:
        #           result = await ontology_process(prompt)      # MISSING user_context, tenant_id
        #           if result:
        #               return str(result)
        #       except Exception:                                # SILENT swallow
        #           pass
        #   # ... falls through to direct graph store ...
```

### Does NOT Exist
- ~~`self._tenant_id` reliably set on every agent~~ — use `getattr(self, "_tenant_id", "default")` for safety.
- ~~`self._get_permission_context` always present~~ — `OntologyRAGMixin` adds the default in TASK-1076, but `IntentRouterMixin` might be used WITHOUT `OntologyRAGMixin` in some agents. Guard with `hasattr`.

---

## Implementation Notes

### Pattern to Follow

```python
async def _run_graph_pageindex(
    self,
    prompt: str,
    candidates: list[RouterCandidate],
) -> Optional[str]:
    # Try OntologyRAGMixin integration
    ontology_process = getattr(self, "ontology_process", None)
    if ontology_process:
        perm_ctx = (
            self._get_permission_context()
            if hasattr(self, "_get_permission_context")
            else {}
        )
        tenant_id = getattr(self, "_tenant_id", "default")
        try:
            result = await ontology_process(
                prompt, user_context=perm_ctx, tenant_id=tenant_id,
            )
        except Exception as exc:  # noqa: BLE001
            _logger = getattr(self, "logger", logging.getLogger(__name__))
            _logger.warning("ontology_process failed: %s", exc)
            result = None
        if result:
            return str(result)

    # Try direct graph store query — unchanged
    for attr in ("_ont_graph_store", "graph_store"):
        # ... existing code ...
```

### Key Constraints

- Keep the fallthrough behavior intact — if `ontology_process` returns falsy or raises, the next strategy in the chain still runs.
- The `except Exception` is necessary (we still must not crash the router), but it MUST log. The original `pass` is unacceptable.
- Do not change the function signature or move it within the file.

### References in Codebase

- `packages/ai-parrot/src/parrot/bots/mixins/intent_router.py:615-667` — current implementation.

---

## Acceptance Criteria

- [ ] `_run_graph_pageindex` forwards `prompt`, `user_context`, `tenant_id` to `ontology_process`.
- [ ] When `ontology_process` raises, the exception is logged at WARNING level and the router falls through (no silent swallow).
- [ ] `test_intent_router_forwards_context` passes — spy on `ontology_process` confirms three kwargs received.
- [ ] No regression on existing `test_intent_router_e2e.py` / `test_intent_router_unit.py`.

---

## Test Specification

```python
# packages/ai-parrot/tests/test_intent_router_unit.py (additions)
import logging
import pytest
from unittest.mock import AsyncMock


class TestRunGraphPageIndexForwarding:
    async def test_forwards_user_context_and_tenant(self, agent_with_router):
        spy = AsyncMock(return_value="enriched")
        agent_with_router.ontology_process = spy
        agent_with_router._get_permission_context = lambda: {"user_id": "alice", "channel": "telegram"}
        agent_with_router._tenant_id = "tenant-A"
        out = await agent_with_router._run_graph_pageindex("hello", candidates=[])
        spy.assert_awaited_once_with(
            "hello",
            user_context={"user_id": "alice", "channel": "telegram"},
            tenant_id="tenant-A",
        )
        assert out == "enriched"

    async def test_logs_on_exception(self, agent_with_router, caplog):
        agent_with_router.ontology_process = AsyncMock(side_effect=RuntimeError("boom"))
        agent_with_router._get_permission_context = lambda: {}
        agent_with_router._tenant_id = "t1"
        with caplog.at_level(logging.WARNING):
            out = await agent_with_router._run_graph_pageindex("hello", candidates=[])
        assert out is None
        assert any("boom" in rec.message for rec in caplog.records)
```

---

## Agent Instructions

1. Read the spec.
2. Re-read `intent_router.py:615-667` to confirm current behavior.
3. Implement following the pattern.
4. Verify all acceptance criteria.
5. Move this file to `sdd/tasks/completed/`.
6. Update the per-spec index → `"done"`.

---

## Completion Note

**Completed by**: claude-sonnet-4-6
**Date**: 2026-05-11
**Notes**: Updated `_run_graph_pageindex` to call `ontology_process(prompt, user_context=perm_ctx, tenant_id=tenant_id)`
using `_get_permission_context()` hook and `_tenant_id` attr. Silent `pass` replaced with
`logger.warning(...)`. Added 4 unit tests (TestRunGraphPageIndexForwarding). Updated
`test_intent_router_e2e.py` mock signature to accept new kwargs. 65 total intent router tests pass.
**Deviations from spec**: None.
