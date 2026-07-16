---
type: Wiki Overview
title: 'TASK-1071: Ontology schema extensions for entity extraction, authorization,
  tool_call'
id: doc:sdd-tasks-completed-task-1071-ontology-schema-extensions-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Spec §2 Data Models. This task lands the new Pydantic types every other task
  in FEAT-158 imports. Without it, TASK-1072/1073/1074/1075 are blocked.
relates_to:
- concept: mod:parrot.knowledge.ontology
  rel: mentions
- concept: mod:parrot.knowledge.ontology.schema
  rel: mentions
---

# TASK-1071: Ontology schema extensions for entity extraction, authorization, tool_call

**Feature**: FEAT-158 — Ontology Entity Extraction & Tool-Call Dispatch
**Spec**: `sdd/specs/ontology-entity-extraction.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §2 Data Models. This task lands the new Pydantic types every other task in FEAT-158 imports. Without it, TASK-1072/1073/1074/1075 are blocked.

The schema additions are purely additive — existing `TraversalPattern`, `ResolvedIntent`, `EnrichedContext` stay backwards compatible. `ContextEnvelope` is a new wrapping type, NOT a replacement for `EnrichedContext`.

---

## Scope

- Add `EntityExtractionRule` Pydantic model.
- Add `AuthorizationRule` + `AuthorizationSpec` Pydantic models. `rule: has_role` MUST require a non-null `role` field — enforce via a Pydantic `model_validator`.
- Add `ToolCallSpec` Pydantic model.
- Add `ContextEnvelope` Pydantic model wrapping `EnrichedContext`.
- Extend `TraversalPattern` with three NEW optional fields: `entity_extraction: dict[str, EntityExtractionRule]`, `authorization: AuthorizationSpec | None`, `tool_call: ToolCallSpec | None`. All default to empty/None to preserve backwards compat.
- Extend `ResolvedIntent` with: `resolved_entities: dict[str, str]`, `tool_call: ToolCallSpec | None`, `denial_reason: str | None`.
- All new models use `ConfigDict(extra="forbid")` matching the existing ontology schema convention.

**NOT in scope**:
- Cache key extension (TASK-1072).
- Any consumer of these models — resolver, dispatcher, mixin refactor (TASK-1073 onward).
- YAML fixture files (TASK-1078).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/ontology/schema.py` | MODIFY | Add 5 new models + extend `TraversalPattern` and `ResolvedIntent`. |
| `packages/ai-parrot/tests/knowledge/test_ontology_schema_extensions.py` | CREATE | Unit tests for new models. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from pydantic import BaseModel, Field, ConfigDict
from typing import Any, Literal
from parrot.knowledge.ontology.schema import (
    TraversalPattern,       # schema.py:131
    ResolvedIntent,         # schema.py:279
    EnrichedContext,        # schema.py:303
)
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/ontology/schema.py

class TraversalPattern(BaseModel):                          # line 131
    description: str
    trigger_intents: list[str]
    query_template: str
    post_action: Literal[...]   # currently includes "tool_call"
    post_query: str | None
    model_config = ConfigDict(extra="forbid")

class ResolvedIntent(BaseModel):                            # line 279
    action: Literal["graph_query", "vector_only"]
    pattern: str | None
    aql: str | None
    params: dict
    collection_binds: dict
    post_action: str
    post_query: str | None
    source: str

class EnrichedContext(BaseModel):                           # line 303
    source: str
    graph_context: list[dict] | None
    vector_context: list[dict] | None
    tool_hint: str | None
    intent: ResolvedIntent | None
    metadata: dict
```

### Does NOT Exist
- ~~`EnrichedContext.clarification_needed`~~ — DOES NOT exist; never add to `EnrichedContext`. The clarification state belongs on the new `ContextEnvelope`.
- ~~`EnrichedContext.auth_prompt`~~ — same as above.
- ~~`EnrichedContext.denial_reason`~~ — same as above.
- ~~`EnrichedContext.tool_result`~~ — same as above.

---

## Implementation Notes

### Pattern to Follow

Match the style of `EntityDef` (`schema.py:39`) and `RelationDef` (`schema.py:106`): Pydantic v2 model with `model_config = ConfigDict(extra="forbid")`, kebab-case `Literal` enums, `Field(default_factory=...)` for mutable defaults.

```python
class EntityExtractionRule(BaseModel):
    type: str
    resolver: Literal[
        "exact_id_match",
        "fuzzy_name_match",
        "ai_assisted",
        "hybrid_concept_match",
    ]
    scope: Literal["same_tenant", "same_department", "anywhere"] = "same_tenant"
    ambiguity_strategy: Literal[
        "ask_user", "pick_first", "use_context", "fail", "rerank_by_authority",
    ] = "ask_user"
    required: bool = True
    description: str | None = None
    model_config = ConfigDict(extra="forbid")
```

For `AuthorizationRule`, enforce `role` presence when `rule == "has_role"`:

```python
from pydantic import model_validator

class AuthorizationRule(BaseModel):
    rule: Literal["target_is_self", "target_in_management_chain",
                  "has_role", "same_department", "always"]
    role: str | None = None
    description: str | None = None
    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _require_role_for_has_role(self) -> "AuthorizationRule":
        if self.rule == "has_role" and not self.role:
            raise ValueError("rule='has_role' requires a non-empty 'role' field")
        return self
```

For `ContextEnvelope`:

```python
class ContextEnvelope(BaseModel):
    state: Literal[
        "ok", "ambiguous", "entity_not_found",
        "denied", "auth_required", "render_error", "tool_failed",
    ]
    context: EnrichedContext | None = None
    clarification: dict[str, Any] | None = None
    denial_reason: str | None = None
    auth_prompt: dict[str, Any] | None = None
    tool_result: dict[str, Any] | None = None
    error: str | None = None
    model_config = ConfigDict(extra="forbid")
```

### Key Constraints

- Pydantic v2 only — no `Config` inner class, use `model_config = ConfigDict(...)`.
- `extra="forbid"` on every new model — matches existing ontology schema convention.
- Backwards compat: extensions to `TraversalPattern` and `ResolvedIntent` MUST be optional with safe defaults so existing YAML/code still loads.
- No imports from `parrot.knowledge.ontology` modules other than `schema` itself — this module is the foundation.

### References in Codebase

- `packages/ai-parrot/src/parrot/knowledge/ontology/schema.py:39` — `EntityDef` style reference.
- `packages/ai-parrot/src/parrot/knowledge/ontology/schema.py:106` — `RelationDef` style reference.

---

## Acceptance Criteria

- [ ] All 5 new models exist in `schema.py` with `ConfigDict(extra="forbid")`.
- [ ] `TraversalPattern` has 3 new optional fields with safe defaults; existing YAML patterns still load without modification.
- [ ] `ResolvedIntent` has 3 new optional fields; existing call sites that construct it still work.
- [ ] `AuthorizationRule` rejects `{"rule": "has_role"}` without a `role` field at Pydantic validation time.
- [ ] All unit tests pass: `pytest packages/ai-parrot/tests/knowledge/test_ontology_schema_extensions.py -v`.
- [ ] No regression: `pytest packages/ai-parrot/tests/knowledge/test_ontology_mixin.py packages/ai-parrot/tests/knowledge/test_ontology_integration.py -v` still passes.
- [ ] Imports work: `from parrot.knowledge.ontology.schema import EntityExtractionRule, AuthorizationRule, AuthorizationSpec, ToolCallSpec, ContextEnvelope`.

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/test_ontology_schema_extensions.py
import pytest
from pydantic import ValidationError
from parrot.knowledge.ontology.schema import (
    EntityExtractionRule, AuthorizationRule, AuthorizationSpec,
    ToolCallSpec, ContextEnvelope, TraversalPattern, ResolvedIntent,
    EnrichedContext,
)


class TestEntityExtractionRule:
    def test_defaults(self):
        rule = EntityExtractionRule(type="Employee", resolver="fuzzy_name_match")
        assert rule.scope == "same_tenant"
        assert rule.ambiguity_strategy == "ask_user"
        assert rule.required is True

    def test_forbids_extra(self):
        with pytest.raises(ValidationError):
            EntityExtractionRule(type="Employee", resolver="exact_id_match", bogus=1)


class TestAuthorizationRule:
    def test_has_role_requires_role(self):
        with pytest.raises(ValidationError, match="has_role"):
            AuthorizationRule(rule="has_role")

    def test_has_role_with_role_ok(self):
        rule = AuthorizationRule(rule="has_role", role="hr_manager")
        assert rule.role == "hr_manager"

    def test_target_is_self_no_role_ok(self):
        AuthorizationRule(rule="target_is_self")  # no validator failure


class TestContextEnvelope:
    def test_ok_with_context(self):
        ctx = EnrichedContext(source="ontology", graph_context=None,
                              vector_context=None, tool_hint=None,
                              intent=None, metadata={})
        env = ContextEnvelope(state="ok", context=ctx)
        assert env.context is ctx

    def test_denied_with_reason(self):
        env = ContextEnvelope(state="denied", denial_reason="not authorized")
        assert env.context is None
        assert env.denial_reason == "not authorized"


class TestTraversalPatternBackCompat:
    def test_minimal_pattern_loads(self):
        # Existing-style pattern without any new sections still validates.
        TraversalPattern(
            description="t", trigger_intents=["x"],
            query_template="FOR e IN c RETURN e",
            post_action="vector_search", post_query=None,
        )

    def test_pattern_with_new_sections(self):
        p = TraversalPattern(
            description="t", trigger_intents=["x"],
            query_template="FOR e IN c RETURN e",
            post_action="tool_call", post_query=None,
            entity_extraction={
                "target": EntityExtractionRule(type="Employee", resolver="fuzzy_name_match")
            },
            authorization=AuthorizationSpec(rules=[AuthorizationRule(rule="target_is_self")]),
            tool_call=ToolCallSpec(
                toolkit="JiraToolkit", method="jira_search_issues",
                result_binding="issues",
            ),
        )
        assert "target" in p.entity_extraction
        assert p.tool_call.method == "jira_search_issues"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context.
2. **Verify the Codebase Contract** — `read packages/ai-parrot/src/parrot/knowledge/ontology/schema.py` and confirm lines 39, 106, 131, 279, 303 still match the signatures listed above. If anything has shifted, update the contract first.
3. **Implement** following the scope, contract, and notes above.
4. **Verify** all acceptance criteria.
5. **Move this file** to `sdd/tasks/completed/`.
6. **Update** `sdd/tasks/index/ontology-entity-extraction.json` → status `"done"`.
7. **Fill in** the Completion Note below.

---

## Completion Note

**Completed by**: claude-sonnet-4-6 (sdd-worker)
**Date**: 2026-05-11
**Notes**: Added 5 new Pydantic v2 models (EntityExtractionRule, AuthorizationRule,
AuthorizationSpec, ToolCallSpec, ContextEnvelope). Extended TraversalPattern with 3
optional fields (entity_extraction, authorization, tool_call). Extended ResolvedIntent
with 3 optional fields (resolved_entities, tool_call, denial_reason). All models use
ConfigDict(extra="forbid"). 29 unit tests pass; 14 existing mixin tests pass (no regression).
model_validator on AuthorizationRule enforces role field for has_role.

**Deviations from spec**: none
