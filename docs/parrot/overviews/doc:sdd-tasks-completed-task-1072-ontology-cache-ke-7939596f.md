---
type: Wiki Overview
title: 'TASK-1072: Extend OntologyCache.build_key to include resolved entities'
id: doc:sdd-tasks-completed-task-1072-ontology-cache-key-resolved-entities-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Spec §3 Module 6, §5 Acceptance Criteria. Without this, two users querying
  the same pattern with different target entities can share a cache entry — a correctness
  bug and a confidentiality risk. The current key shape `f"{prefix}:{tenant_id}:{user_id}:{pattern}"`
  (`cache.py:43-55`
relates_to:
- concept: mod:parrot.knowledge.ontology.cache
  rel: mentions
---

# TASK-1072: Extend OntologyCache.build_key to include resolved entities

**Feature**: FEAT-158 — Ontology Entity Extraction & Tool-Call Dispatch
**Spec**: `sdd/specs/ontology-entity-extraction.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1071
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6, §5 Acceptance Criteria. Without this, two users querying the same pattern with different target entities can share a cache entry — a correctness bug and a confidentiality risk. The current key shape `f"{prefix}:{tenant_id}:{user_id}:{pattern}"` (`cache.py:43-55`) is unaware of resolved entities.

This change is backwards-compatible: callers that do not pass `resolved_entities` produce today's key shape exactly.

---

## Scope

- Add an optional `resolved_entities: dict[str, str] | None = None` parameter to `OntologyCache.build_key`.
- When `resolved_entities` is `None` or empty, return today's key shape unchanged.
- When non-empty, append a deterministic suffix derived from `sorted(resolved_entities.items())`. Format: `:e=key1=val1,key2=val2` (sorted by key).
- Update the docstring.

**NOT in scope**:
- Calling the extended `build_key` from the Mixin — that lands in TASK-1076.
- Any other change to `cache.py` semantics (TTL, eviction, etc.).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/ontology/cache.py` | MODIFY | Extend `build_key` signature + body. |
| `packages/ai-parrot/tests/knowledge/test_ontology_cache_key.py` | CREATE | Unit tests for old and new key shapes. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.knowledge.ontology.cache import OntologyCache    # cache.py
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/ontology/cache.py
class OntologyCache:
    @staticmethod
    def build_key(tenant_id: str, user_id: str, pattern: str) -> str:    # lines 43-55
        # Returns: f"{prefix}:{tenant_id}:{user_id}:{pattern}"
```

### Does NOT Exist
- ~~`OntologyCache.build_key` already including entities~~ — DOES NOT today; this task is what adds it.

---

## Implementation Notes

### Pattern to Follow

```python
@staticmethod
def build_key(
    tenant_id: str,
    user_id: str,
    pattern: str,
    resolved_entities: dict[str, str] | None = None,
) -> str:
    """Build a cache key scoped by tenant, user, pattern, and (optionally)
    resolved entities to prevent cross-target poisoning."""
    base = f"{prefix}:{tenant_id}:{user_id}:{pattern}"
    if not resolved_entities:
        return base
    items = ",".join(f"{k}={v}" for k, v in sorted(resolved_entities.items()))
    return f"{base}:e={items}"
```

### Key Constraints

- Default `None` (or empty dict) MUST produce today's exact key shape — verify via test against the current production string.
- Sorting MUST be by key, not insertion order, for determinism across Python dict semantics in different traversal paths.
- Do not change the `prefix` constant or any other module behavior.

### References in Codebase

- `packages/ai-parrot/src/parrot/knowledge/ontology/cache.py:43-55` — current implementation.

---

## Acceptance Criteria

- [ ] `build_key(tenant_id, user_id, pattern)` without the new arg returns the EXACT current string (regression-safe).
- [ ] `build_key(..., resolved_entities={"a":"1", "b":"2"})` is deterministic and equal to `build_key(..., resolved_entities={"b":"2", "a":"1"})`.
- [ ] Two distinct `resolved_entities` dicts produce distinct keys.
- [ ] `build_key(..., resolved_entities={})` equals the no-arg version.
- [ ] All unit tests pass: `pytest packages/ai-parrot/tests/knowledge/test_ontology_cache_key.py -v`.

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/test_ontology_cache_key.py
from parrot.knowledge.ontology.cache import OntologyCache


class TestBuildKey:
    def test_backwards_compatible_shape(self):
        k = OntologyCache.build_key("t1", "u1", "team")
        assert k.endswith(":t1:u1:team")

    def test_empty_entities_matches_no_arg(self):
        assert OntologyCache.build_key("t1", "u1", "team") == \
               OntologyCache.build_key("t1", "u1", "team", resolved_entities={})

    def test_deterministic_sort(self):
        k1 = OntologyCache.build_key("t1", "u1", "team",
                                     resolved_entities={"a": "1", "b": "2"})
        k2 = OntologyCache.build_key("t1", "u1", "team",
                                     resolved_entities={"b": "2", "a": "1"})
        assert k1 == k2

    def test_different_entities_distinct_keys(self):
        k1 = OntologyCache.build_key("t1", "u1", "team",
                                     resolved_entities={"target": "Emp/1"})
        k2 = OntologyCache.build_key("t1", "u1", "team",
                                     resolved_entities={"target": "Emp/2"})
        assert k1 != k2
```

---

## Agent Instructions

1. Read the spec at the path above.
2. Verify the contract: `read packages/ai-parrot/src/parrot/knowledge/ontology/cache.py` and confirm lines 43-55 still match.
3. Implement following the scope and pattern.
4. Verify all acceptance criteria.
5. Move this file to `sdd/tasks/completed/`.
6. Update `sdd/tasks/index/ontology-entity-extraction.json` → `"done"`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session>
**Date**: YYYY-MM-DD
**Notes**: ...
**Deviations from spec**: none | describe if any
