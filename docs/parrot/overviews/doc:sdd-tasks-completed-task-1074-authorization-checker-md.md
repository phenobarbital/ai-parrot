---
type: Wiki Overview
title: 'TASK-1074: Implement AuthorizationChecker with 5 declarative rules'
id: doc:sdd-tasks-completed-task-1074-authorization-checker-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Spec §2 New Public Interfaces, §3 Module 3. `AuthorizationChecker` enforces
  intent-level authorization AFTER entity resolution but BEFORE graph traversal. Without
  it, any user matching a trigger phrase could execute any pattern — there is no defense
  against cross-department or of
relates_to:
- concept: mod:parrot.auth
  rel: mentions
- concept: mod:parrot.knowledge.ontology.authorization
  rel: mentions
- concept: mod:parrot.knowledge.ontology.graph_store
  rel: mentions
- concept: mod:parrot.knowledge.ontology.schema
  rel: mentions
---

# TASK-1074: Implement AuthorizationChecker with 5 declarative rules

**Feature**: FEAT-158 — Ontology Entity Extraction & Tool-Call Dispatch
**Spec**: `sdd/specs/ontology-entity-extraction.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1071
**Assigned-to**: unassigned

---

## Context

Spec §2 New Public Interfaces, §3 Module 3. `AuthorizationChecker` enforces intent-level authorization AFTER entity resolution but BEFORE graph traversal. Without it, any user matching a trigger phrase could execute any pattern — there is no defense against cross-department or off-role queries.

Rules are OR-combined and default-deny: if no rule matches, the request is denied.

---

## Scope

- Create `packages/ai-parrot/src/parrot/knowledge/ontology/authorization.py` with `class AuthorizationChecker`.
- Async method `check(spec, user_context, resolved_entities, tenant_id) -> tuple[bool, str | None]`.
- Implement 5 rules (dispatched on `rule.rule`):
  - `always` → always allow.
  - `target_is_self` → allow if `user_context["user_id"]` equals the resolved `_id` of any extracted entity OR equals the asking user's own `_id` (when the resolver returned themselves).
  - `target_in_management_chain` → bounded AQL traversal (depth ≤ 10) along the `reports_to` edge from the asking user toward each resolved entity. Allow if ANY resolved entity is in the chain.
  - `has_role` → allow if `rule.role` ∈ `user_context.get("roles", [])`.
  - `same_department` → allow if `user_context.get("department")` matches the resolved entity's `department` field (requires a graph lookup of the entity by `_id`).
- OR semantics: iterate rules in order, return `(True, None)` on first match.
- Default-deny: if no rule matches AND `spec.default_deny is True`, return `(False, "no authorization rule matched")`. If `default_deny is False`, return `(True, None)` (intentional override for trusted patterns).
- Log every decision at `info` level: `f"auth check: pattern=... user=... result=allow|deny rule=... reason=..."`.

**NOT in scope**:
- Wiring into the Mixin (TASK-1076).
- The `rerank_by_authority` resolver hint (reserved for FEAT-concept-document-authority).
- A general-purpose RBAC system — this module is intent-level only.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/ontology/authorization.py` | CREATE | `AuthorizationChecker` class. |
| `packages/ai-parrot/tests/knowledge/test_authorization.py` | CREATE | Unit tests for all 5 rules + OR-combine + default-deny. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.knowledge.ontology.schema import (
    AuthorizationSpec,          # NEW from TASK-1071
    AuthorizationRule,          # NEW from TASK-1071
)
from parrot.knowledge.ontology.graph_store import OntologyGraphStore   # graph_store.py:33
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py:33
class OntologyGraphStore:
    async def execute_traversal(
        self, ctx: TenantContext, aql: str,
        bind_vars: dict[str, Any] | None = None,
        collection_binds: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:                                  # lines 185-223
```

### Does NOT Exist
- ~~A global `parrot.auth.rbac`~~ — there is no project-level RBAC module to delegate to. This task implements rule evaluation inline.
- ~~`OntologyGraphStore.is_in_management_chain(...)`~~ — no such helper; write the AQL traversal yourself.

---

## Implementation Notes

### Pattern to Follow

Management-chain AQL (depth ≤ 10):

```aql
LET start = DOCUMENT(@asker_id)
FOR v IN 1..10 OUTBOUND start._id @@reports_to
  FILTER v._id == @target_id
  RETURN v._id
```

If the query returns ≥ 1 row, the target is in the management chain.

```python
class AuthorizationChecker:
    def __init__(self, graph_store: OntologyGraphStore) -> None:
        self._graph_store = graph_store
        self.logger = logging.getLogger(__name__)

    async def check(
        self,
        spec: AuthorizationSpec,
        user_context: dict[str, Any],
        resolved_entities: dict[str, str],
        tenant_id: str,
    ) -> tuple[bool, str | None]:
        for rule in spec.rules:
            allowed, reason = await self._evaluate(rule, user_context, resolved_entities, tenant_id)
            if allowed:
                self.logger.info("auth check: allow rule=%s", rule.rule)
                return True, None
        if not spec.default_deny:
            return True, None
        return False, "no authorization rule matched"
```

### Key Constraints

- Async throughout.
- AQL bind variables ONLY; do not interpolate IDs or strings into AQL.
- The `reports_to` edge collection name must come from the ontology's relation definitions or be passed in via `collection_binds={"reports_to": "<actual_collection_name>"}`. For this task, accept an optional `reports_to_collection` constructor arg defaulting to `"reports_to"`.
- `same_department` requires looking up the resolved entity's `department` — use `execute_traversal` with `RETURN DOCUMENT(@target_id).department`.
- If `user_context["user_id"]` is missing, ALL rules except `always` MUST deny (return `(False, "missing user_id in permission_context")`).

### References in Codebase

- `packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py:185` — AQL execution.

---

## Acceptance Criteria

- [ ] `test_auth_target_is_self_allows` passes.
- [ ] `test_auth_target_in_management_chain` passes (depth-3 subordinate → allow).
- [ ] `test_auth_target_in_management_chain_denies_depth_11` passes.
- [ ] `test_auth_has_role_allows` passes.
- [ ] `test_auth_has_role_denies_when_role_missing` passes.
- [ ] `test_auth_same_department_allows` passes.
- [ ] `test_auth_default_deny` passes.
- [ ] `test_auth_or_combine` passes: two rules, first denies, second allows → allowed.
- [ ] `test_auth_default_deny_false_allows_unmatched` passes.
- [ ] All unit tests pass: `pytest packages/ai-parrot/tests/knowledge/test_authorization.py -v`.

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/test_authorization.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from parrot.knowledge.ontology.authorization import AuthorizationChecker
from parrot.knowledge.ontology.schema import AuthorizationSpec, AuthorizationRule


@pytest.fixture
def graph_store():
    gs = MagicMock()
    gs.execute_traversal = AsyncMock()
    return gs


@pytest.fixture
def checker(graph_store):
    return AuthorizationChecker(graph_store=graph_store)


class TestAuthorizationChecker:
    async def test_target_is_self_allows(self, checker):
        spec = AuthorizationSpec(rules=[AuthorizationRule(rule="target_is_self")])
        allowed, reason = await checker.check(
            spec,
            user_context={"user_id": "Employee/me"},
            resolved_entities={"target": "Employee/me"},
            tenant_id="t1",
        )
        assert allowed
        assert reason is None

    async def test_target_in_management_chain_depth_3(self, checker, graph_store):
        graph_store.execute_traversal.return_value = [{"_id": "Employee/sub3"}]
        spec = AuthorizationSpec(rules=[AuthorizationRule(rule="target_in_management_chain")])
        allowed, _ = await checker.check(
            spec,
            user_context={"user_id": "Employee/mgr"},
            resolved_entities={"target": "Employee/sub3"},
            tenant_id="t1",
        )
        assert allowed

    async def test_target_in_management_chain_depth_11_denies(self, checker, graph_store):
        graph_store.execute_traversal.return_value = []  # depth-10 found nothing
        spec = AuthorizationSpec(rules=[AuthorizationRule(rule="target_in_management_chain")])
        allowed, reason = await checker.check(
            spec,
            user_context={"user_id": "Employee/mgr"},
            resolved_entities={"target": "Employee/sub11"},
            tenant_id="t1",
        )
        assert not allowed
        assert "no authorization rule matched" in reason

    async def test_has_role_allows(self, checker):
        spec = AuthorizationSpec(rules=[AuthorizationRule(rule="has_role", role="hr_manager")])
        allowed, _ = await checker.check(
            spec,
            user_context={"user_id": "u1", "roles": ["employee", "hr_manager"]},
            resolved_entities={},
            tenant_id="t1",
        )
        assert allowed

    async def test_has_role_denies_when_role_missing(self, checker):
        spec = AuthorizationSpec(rules=[AuthorizationRule(rule="has_role", role="hr_manager")])
        allowed, _ = await checker.check(
            spec,
            user_context={"user_id": "u1", "roles": ["employee"]},
            resolved_entities={},
            tenant_id="t1",
        )
        assert not allowed

    async def test_or_combine_second_rule_passes(self, checker):
        spec = AuthorizationSpec(rules=[
            AuthorizationRule(rule="has_role", role="hr_manager"),
            AuthorizationRule(rule="target_is_self"),
        ])
        allowed, _ = await checker.check(
            spec,
            user_context={"user_id": "Employee/me", "roles": []},
            resolved_entities={"target": "Employee/me"},
            tenant_id="t1",
        )
        assert allowed

    async def test_default_deny_when_no_rules_match(self, checker):
        spec = AuthorizationSpec(rules=[AuthorizationRule(rule="target_is_self")])
        allowed, reason = await checker.check(
            spec,
            user_context={"user_id": "Employee/me"},
            resolved_entities={"target": "Employee/other"},
            tenant_id="t1",
        )
        assert not allowed
        assert reason

    async def test_default_deny_false_allows_unmatched(self, checker):
        spec = AuthorizationSpec(
            rules=[AuthorizationRule(rule="target_is_self")],
            default_deny=False,
        )
        allowed, _ = await checker.check(
            spec,
            user_context={"user_id": "Employee/me"},
            resolved_entities={"target": "Employee/other"},
            tenant_id="t1",
        )
        assert allowed
```

---

## Agent Instructions

1. Read the spec.
2. Verify the contract: re-read `schema.py` (post TASK-1071) and `graph_store.py`.
3. Implement following the scope and pattern.
4. Verify all acceptance criteria.
5. Move this file to `sdd/tasks/completed/`.
6. Update the per-spec index → `"done"`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session>
**Date**: YYYY-MM-DD
**Notes**: ...
**Deviations from spec**: none | describe if any
