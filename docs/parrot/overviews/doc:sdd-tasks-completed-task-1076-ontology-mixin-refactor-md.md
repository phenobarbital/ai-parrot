---
type: Wiki Overview
title: 'TASK-1076: Refactor OntologyRAGMixin.ontology_process to compose entity resolution,
  authorization, and tool dispatch'
id: doc:sdd-tasks-completed-task-1076-ontology-mixin-refactor-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Spec §2 Component Diagram, §3 Module 5, §5 Acceptance Criteria. This task
  wires the three new modules into the production pipeline. After this task lands,
  the *"team of Jesús"* flow runs end-to-end inside `ontology_process` — only the
  IntentRouter forwarding fix (TASK-1077) and t
relates_to:
- concept: mod:parrot.auth.exceptions
  rel: mentions
- concept: mod:parrot.knowledge.ontology.authorization
  rel: mentions
- concept: mod:parrot.knowledge.ontology.cache
  rel: mentions
- concept: mod:parrot.knowledge.ontology.entity_resolver
  rel: mentions
- concept: mod:parrot.knowledge.ontology.schema
  rel: mentions
- concept: mod:parrot.knowledge.ontology.tool_dispatcher
  rel: mentions
---

# TASK-1076: Refactor OntologyRAGMixin.ontology_process to compose entity resolution, authorization, and tool dispatch

**Feature**: FEAT-158 — Ontology Entity Extraction & Tool-Call Dispatch
**Spec**: `sdd/specs/ontology-entity-extraction.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1071, TASK-1072, TASK-1073, TASK-1074, TASK-1075
**Assigned-to**: unassigned

---

## Context

Spec §2 Component Diagram, §3 Module 5, §5 Acceptance Criteria. This task wires the three new modules into the production pipeline. After this task lands, the *"team of Jesús"* flow runs end-to-end inside `ontology_process` — only the IntentRouter forwarding fix (TASK-1077) and the E2E test (TASK-1078) remain.

The return type widens from `EnrichedContext` to `ContextEnvelope`. This is a breaking change for callers reading `result.graph_context` directly — they must migrate to `result.context.graph_context`. The only known internal caller is `IntentRouterMixin._run_graph_pageindex`, fixed in TASK-1077.

---

## Scope

- Modify `packages/ai-parrot/src/parrot/knowledge/ontology/mixin.py`:
  - Add `_get_permission_context(self) -> dict[str, Any]` instance method returning `{}` by default.
  - Refactor `ontology_process(query, user_context, tenant_id, domain=None)`:
    - After intent resolution (existing), if `pattern.entity_extraction` is non-empty:
      - Call `EntityResolver.extract_and_resolve(...)`.
      - Catch `EntityAmbiguityError` → return `ContextEnvelope(state="ambiguous", clarification={"rule": …, "mention": …, "candidates": …})`.
      - Catch `EntityNotFoundError` → return `ContextEnvelope(state="entity_not_found")`.
      - Merge resolved IDs into `intent.params` using the rule-name → `@{rule_name}_id` convention (e.g., rule `target_employee` binds key `target_employee_id`). The exact key naming convention MUST be documented in the docstring.
    - If `pattern.authorization` set, call `AuthorizationChecker.check(...)`. On deny → return `ContextEnvelope(state="denied", denial_reason=…)`.
    - **Cache lookup** uses the extended `OntologyCache.build_key(tenant_id, user_id, pattern, resolved_entities=resolved)` from TASK-1072.
    - Execute the graph traversal (existing).
    - For `post_action == "tool_call"`:
      - If `pattern.tool_call is None`, fall through to the existing `_build_tool_hint` (backwards compat).
      - Else, call `ToolCallDispatcher.dispatch(pattern.tool_call, graph_result, user_context)`.
      - Catch `AuthorizationRequired` → return `ContextEnvelope(state="auth_required", auth_prompt={"auth_url": exc.auth_url, "provider": exc.provider, "scopes": exc.scopes})`.
      - Catch `RenderError` → return `ContextEnvelope(state="render_error", error=str(exc))`.
      - On success, wrap the `EnrichedContext` in `ContextEnvelope(state="ok", context=..., tool_result=dispatcher_output)`.
    - For all other paths, return `ContextEnvelope(state="ok", context=enriched_context)`.
  - Widen the return-type annotation from `EnrichedContext` to `ContextEnvelope`.
  - Construct `EntityResolver`, `AuthorizationChecker`, `ToolCallDispatcher` lazily inside the Mixin — accept optional constructor args for injection in tests; default to wiring them from `self._graph_store`, `self._ontology`, `self._tool_manager`, `self._llm_client` (only set the LLM client if available).

**NOT in scope**:
- Modifying `IntentRouterMixin` (TASK-1077).
- E2E test (TASK-1078).
- Removing `_build_tool_hint` — it stays as the fallback for patterns without an explicit `tool_call` spec.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/ontology/mixin.py` | MODIFY | Refactor `ontology_process`; add `_get_permission_context`. |
| `packages/ai-parrot/tests/knowledge/test_ontology_mixin.py` | MODIFY | Add tests for new states; update existing happy-path assertions to read `result.context.graph_context`. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.knowledge.ontology.schema import (
    TraversalPattern, ResolvedIntent, EnrichedContext,        # existing
    ContextEnvelope,                                           # NEW from TASK-1071
    ToolCallSpec,                                              # NEW from TASK-1071
)
from parrot.knowledge.ontology.entity_resolver import (
    EntityResolver, EntityAmbiguityError, EntityNotFoundError,   # NEW from TASK-1073
)
from parrot.knowledge.ontology.authorization import AuthorizationChecker   # NEW from TASK-1074
from parrot.knowledge.ontology.tool_dispatcher import (
    ToolCallDispatcher, RenderError,                            # NEW from TASK-1075
)
from parrot.knowledge.ontology.cache import OntologyCache       # MODIFIED in TASK-1072
from parrot.auth.exceptions import AuthorizationRequired        # auth/exceptions.py:12
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/ontology/mixin.py:27
class OntologyRAGMixin:
    async def ontology_process(
        self, query: str, user_context: dict[str, Any], tenant_id: str,
        domain: str | None = None,
    ) -> EnrichedContext:                                       # lines 65-177 — WIDENS to ContextEnvelope
        # Current cache call at line 114:
        #   cache_key = OntologyCache.build_key(tenant_id, user_id, pattern_name)
        # Current tool_call branch lines 150-151:
        #   elif intent.post_action == "tool_call" and graph_result:
        #       tool_hint = self._build_tool_hint(graph_result)

    @staticmethod
    def _build_tool_hint(graph_result: list[dict[str, Any]]) -> str:    # lines 235-256
```

### Does NOT Exist
- ~~`OntologyRAGMixin._get_permission_context`~~ — this task introduces it. Default returns `{}`.
- ~~`ContextEnvelope` as a return type today~~ — return type widens in this task.

---

## Implementation Notes

### Pattern to Follow

```python
async def ontology_process(
    self,
    query: str,
    user_context: dict[str, Any],
    tenant_id: str,
    domain: str | None = None,
) -> ContextEnvelope:
    intent = await self._intent_resolver.resolve(query, user_context)
    if intent.action == "vector_only":
        # ... existing path; wrap result at the end ...
        ...

    pattern = self._patterns[intent.pattern]
    resolved_entities: dict[str, str] = {}

    if pattern.entity_extraction:
        try:
            resolved_entities = await self._entity_resolver.extract_and_resolve(
                pattern, query, user_context, tenant_id,
            )
        except EntityAmbiguityError as exc:
            return ContextEnvelope(
                state="ambiguous",
                clarification={
                    "rule": exc.rule_name,
                    "mention": exc.mention,
                    "candidates": exc.candidates,
                },
            )
        except EntityNotFoundError as exc:
            return ContextEnvelope(state="entity_not_found",
                                   error=f"{exc.rule_name} not found")
        # Bind into AQL params: rule "target_employee" -> @target_employee_id
        for rule_name, _id in resolved_entities.items():
            intent.params[f"{rule_name}_id"] = _id

    if pattern.authorization is not None:
        allowed, reason = await self._auth_checker.check(
            pattern.authorization, user_context, resolved_entities, tenant_id,
        )
        if not allowed:
            return ContextEnvelope(state="denied", denial_reason=reason)

    user_id = user_context.get("user_id", "anonymous")
    cache_key = OntologyCache.build_key(
        tenant_id, user_id, pattern_name, resolved_entities=resolved_entities,
    )
    # ... cache lookup ...

    graph_result = await self._graph_store.execute_traversal(...)
    enriched = EnrichedContext(...)   # existing

    if intent.post_action == "tool_call":
        if pattern.tool_call is None:
            enriched.tool_hint = self._build_tool_hint(graph_result)
            return ContextEnvelope(state="ok", context=enriched)
        try:
            tool_output = await self._tool_dispatcher.dispatch(
                pattern.tool_call, graph_result, user_context,
            )
        except AuthorizationRequired as exc:
            return ContextEnvelope(
                state="auth_required",
                auth_prompt={
                    "auth_url": exc.auth_url,
                    "provider": exc.provider,
                    "scopes": list(exc.scopes or []),
                },
            )
        except RenderError as exc:
            return ContextEnvelope(state="render_error", error=str(exc))
        return ContextEnvelope(state="ok", context=enriched,
                               tool_result=tool_output)

    return ContextEnvelope(state="ok", context=enriched)


def _get_permission_context(self) -> dict[str, Any]:
    """Return the current session's permission context.
    Default returns {}. Concrete agents override to surface user_id,
    channel, department, roles, manager_id, etc."""
    return {}
```

### Key Constraints

- **Backwards compatibility for vector_search post-action**: still works; `ContextEnvelope(state="ok", context=enriched)` is the wrapper.
- **`pattern.tool_call is None` is a valid case** — falls back to `_build_tool_hint`. Tests must cover this.
- **Cache key**: use the new `resolved_entities` kwarg from TASK-1072. Never bypass.
- **AQL bind-key naming convention**: `rule "target_employee" -> @target_employee_id`. Document this in the docstring; pattern authors need to know the binding shape.
- Logger calls at each state transition (info level), including ambiguity, denial, auth_required, and ok-with-tool.

### References in Codebase

- `packages/ai-parrot/src/parrot/knowledge/ontology/mixin.py:65-177` — current `ontology_process` body.
- `packages/ai-parrot/src/parrot/knowledge/ontology/mixin.py:235-256` — `_build_tool_hint` (retained).
- `packages/ai-parrot/tests/knowledge/test_ontology_mixin.py` — existing test patterns to extend.

---

## Acceptance Criteria

- [ ] `test_mixin_ontology_process_happy_path` passes — full pipeline returns `ContextEnvelope(state="ok", tool_result=…)`.
- [ ] `test_mixin_ontology_process_ambiguity` passes.
- [ ] `test_mixin_ontology_process_denied` passes.
- [ ] `test_mixin_ontology_process_auth_required` passes — `AuthorizationRequired` translated correctly with `auth_url`.
- [ ] `test_mixin_ontology_process_render_error` passes.
- [ ] `test_mixin_get_permission_context_default` passes — returns `{}`.
- [ ] `test_mixin_tool_call_without_spec_uses_build_tool_hint` passes — backwards-compat fallback.
- [ ] `test_mixin_cache_uses_resolved_entities` passes — two users querying same pattern with distinct targets get distinct cache keys.
- [ ] Existing `test_ontology_mixin.py` tests updated for `ContextEnvelope` wrapping and continue to pass.
- [ ] No regression on `test_ontology_integration.py`.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/knowledge/test_ontology_mixin.py -v`.

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/test_ontology_mixin.py (additions)
import pytest
from unittest.mock import AsyncMock, MagicMock
from parrot.knowledge.ontology.schema import (
    ContextEnvelope, ToolCallSpec, AuthorizationSpec, AuthorizationRule,
    EntityExtractionRule,
)
from parrot.knowledge.ontology.entity_resolver import (
    EntityAmbiguityError, EntityNotFoundError,
)
from parrot.knowledge.ontology.tool_dispatcher import RenderError
from parrot.auth.exceptions import AuthorizationRequired


class TestOntologyProcessStates:
    async def test_happy_path_returns_ok_envelope(self, agent_with_full_pipeline):
        env = await agent_with_full_pipeline.ontology_process(
            "el equipo de Jesús", user_context={"user_id": "alice"}, tenant_id="t1",
        )
        assert isinstance(env, ContextEnvelope)
        assert env.state == "ok"
        assert env.context is not None
        assert env.tool_result == {"in_progress_issues": ...}

    async def test_ambiguity_translates_to_envelope(self, agent_ambiguity_mock):
        env = await agent_ambiguity_mock.ontology_process(
            "el equipo de Jesús", user_context={"user_id": "alice"}, tenant_id="t1",
        )
        assert env.state == "ambiguous"
        assert env.clarification["rule"] == "target_employee"
        assert len(env.clarification["candidates"]) == 2

    async def test_denied_translates_to_envelope(self, agent_denied_mock):
        env = await agent_denied_mock.ontology_process(...)
        assert env.state == "denied"
        assert env.denial_reason

    async def test_auth_required_translates_to_envelope(self, agent_auth_required_mock):
        env = await agent_auth_required_mock.ontology_process(...)
        assert env.state == "auth_required"
        assert env.auth_prompt["auth_url"] == "https://auth/url"
        assert env.auth_prompt["provider"] == "jira"

    async def test_tool_call_without_spec_falls_back_to_tool_hint(self, agent_no_tool_call_spec):
        env = await agent_no_tool_call_spec.ontology_process(...)
        assert env.state == "ok"
        assert env.context.tool_hint
        assert env.tool_result is None

    def test_get_permission_context_default_empty(self, agent_with_full_pipeline):
        assert agent_with_full_pipeline._get_permission_context() == {}

    async def test_cache_key_includes_resolved_entities(self, agent_with_full_pipeline, monkeypatch):
        seen_keys = []
        def fake_build_key(tenant_id, user_id, pattern, resolved_entities=None):
            key = f"{tenant_id}:{user_id}:{pattern}:{sorted((resolved_entities or {}).items())}"
            seen_keys.append(key)
            return key
        monkeypatch.setattr(
            "parrot.knowledge.ontology.cache.OntologyCache.build_key",
            staticmethod(fake_build_key),
        )
        await agent_with_full_pipeline.ontology_process(
            "el equipo de Jesús", user_context={"user_id": "alice"}, tenant_id="t1",
        )
        await agent_with_full_pipeline.ontology_process(
            "el equipo de Pérez", user_context={"user_id": "alice"}, tenant_id="t1",
        )
        assert seen_keys[0] != seen_keys[1]
```

---

## Agent Instructions

1. Read the spec.
2. Verify the contract: re-read `mixin.py:65-256` and confirm the existing structure of `ontology_process` and `_build_tool_hint`. Note that other branches of `ontology_process` (e.g., `vector_search` post-action) MUST also be wrapped in `ContextEnvelope(state="ok", context=…)` — they don't disappear.
3. Implement following the pattern and constraints.
4. Run the existing `test_ontology_mixin.py` and fix breakage caused by the return-type widening.
5. Verify all acceptance criteria.
6. Move this file to `sdd/tasks/completed/`.
7. Update the per-spec index → `"done"`.

---

## Completion Note

**Completed by**: claude-sonnet-4-6
**Date**: 2026-05-11
**Notes**: Refactored `ontology_process` to return `ContextEnvelope` wrapping `EnrichedContext`.
Added `_get_permission_context()` hook returning `{}` by default. `EntityResolver`,
`AuthorizationChecker`, and `ToolCallDispatcher` are imported at module level and constructed
lazily inside the pipeline. `tool_manager` added as optional constructor arg. All 14 existing
integration tests and 9 new state-machine tests pass (266 total in knowledge suite).
Test files updated: `test_ontology_mixin.py` (23 tests), `test_ontology_integration.py` (4 fixed).
**Deviations from spec**: None — all acceptance criteria met.
