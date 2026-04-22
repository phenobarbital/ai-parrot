# TASK-788: Fast-Path Rules Engine

**Feature**: FEAT-111 — Router-Based Adaptive RAG (Store-Level)
**Spec**: `sdd/specs/router-based-adaptive-rag.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-785
**Assigned-to**: unassigned

---

## Context

Implements **Module 4** of FEAT-111. The fast path scores candidate stores based on deterministic heuristic rules (hardcoded defaults plus per-agent `StoreRule`s from the config). This avoids an LLM call for most queries.

---

## Scope

- Create `parrot/registry/routing/rules.py`.
- Implement `apply_rules(query, rules, available_stores, ontology_annotations) -> list[StoreScore]`:
  - Accepts the user query, a list of `StoreRule` (custom rules merged on top of defaults by the caller), the set of `StoreType`s actually configured on the bot, and optional ontology annotations.
  - Returns a ranked list of `StoreScore` objects (descending by `confidence`).
  - Substring matching by default; regex when `rule.regex is True` (compile once, cached).
  - Ontology annotations influencing scores:
    - If annotations include graph-shaped hints (e.g. `action == "graph_query"`, or `entities` with relations) → boost `ARANGO`.
    - If annotations mark the query as `vector_only` → boost `PGVECTOR`.
- Define a `DEFAULT_STORE_RULES: list[StoreRule]` constant with sensible defaults:
  - Keyword patterns ("what is", "define") → `PGVECTOR`, weight 0.7.
  - Patterns ("graph", "relationship", "between", "connect") → `ARANGO`, weight 0.85.
  - Pattern ("similar to", "like", "resembling") → `FAISS`, weight 0.65.
- Write unit tests under `tests/unit/registry/routing/test_rules.py`.

**NOT in scope**: LLM fallback, cache, bot integration, YAML loading.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/registry/routing/rules.py` | CREATE | Rules engine + default rules |
| `packages/ai-parrot/src/parrot/registry/routing/__init__.py` | MODIFY | Re-export `apply_rules`, `DEFAULT_STORE_RULES` |
| `packages/ai-parrot/tests/unit/registry/routing/test_rules.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import re
import logging
from typing import Optional
from parrot.registry.routing import StoreRule, StoreScore   # introduced in TASK-785
from parrot.tools.multistoresearch import StoreType         # verified: multistoresearch.py:30
```

### Existing Signatures to Use
```python
# Introduced by TASK-785 in parrot/registry/routing/models.py
class StoreRule(BaseModel):
    pattern: str
    store: StoreType
    weight: float = 1.0
    regex: bool = False

class StoreScore(BaseModel):
    store: StoreType
    confidence: float
    reason: str
```

### Does NOT Exist
- ~~`parrot.registry.routing.rules.default_rules`~~ — use `DEFAULT_STORE_RULES` constant.
- ~~A stateful `RulesEngine` class~~ — this is a stateless pure function.

---

## Implementation Notes

### Key Constraints
- Stateless pure function; no `self`, no globals mutated.
- Pre-compile regex once per call (do NOT compile per-rule per-query repeatedly inside a hot loop).
- Lowercase the query ONCE; compare against lowercase patterns.
- Filter out `StoreScore` entries whose `store` is NOT in `available_stores`.
- Aggregate multiple rule matches on the same store: pick the MAX weight (do not sum — keeps confidences bounded in [0,1]).
- When `ontology_annotations` is `None` or empty dict, skip the ontology-influenced boosts — do NOT raise.
- Ontology boost amount: `min(1.0, current_score + 0.15)`.
- If no rules match and no ontology signal applies, return an empty list (caller handles via `StoreFallbackPolicy`).
- Sort result: descending by `confidence`; ties broken by insertion order.

### References in Codebase
- `packages/ai-parrot/src/parrot/bots/mixins/intent_router.py:42` — `_KEYWORD_STRATEGY_MAP` as a precedent for substring-matching keyword rules (we follow the same idea at the store level).

---

## Acceptance Criteria

- [ ] `from parrot.registry.routing import apply_rules, DEFAULT_STORE_RULES` works.
- [ ] `apply_rules` filters out stores not in `available_stores`.
- [ ] Ontology hint `action=graph_query` boosts `ARANGO` confidence.
- [ ] Ontology hint `action=vector_only` boosts `PGVECTOR` confidence.
- [ ] Regex rule (`regex=True`) matches via `re.search`, not `startswith`.
- [ ] Multiple matches on same store → MAX weight (not sum).
- [ ] Empty / missing annotations → no crash, no boost applied.
- [ ] All unit tests pass: `pytest packages/ai-parrot/tests/unit/registry/routing/test_rules.py -v`.

---

## Test Specification

```python
import pytest
from parrot.registry.routing import (
    StoreRule, StoreScore, apply_rules, DEFAULT_STORE_RULES,
)
from parrot.tools.multistoresearch import StoreType


ALL_STORES = [StoreType.PGVECTOR, StoreType.FAISS, StoreType.ARANGO]


def test_keyword_rule_selects_pgvector():
    scores = apply_rules("what is an endcap?", DEFAULT_STORE_RULES, ALL_STORES, None)
    assert scores
    assert scores[0].store == StoreType.PGVECTOR


def test_graph_keyword_selects_arango():
    scores = apply_rules(
        "show the relationship between suppliers and warehouses",
        DEFAULT_STORE_RULES, ALL_STORES, None,
    )
    assert scores[0].store == StoreType.ARANGO


def test_ontology_hint_boosts_arango():
    scores = apply_rules(
        "supplier warehouse",
        DEFAULT_STORE_RULES, ALL_STORES,
        {"action": "graph_query"},
    )
    top = next(s for s in scores if s.store == StoreType.ARANGO)
    assert top.confidence >= 0.85


def test_unavailable_store_is_filtered():
    scores = apply_rules(
        "relationship", DEFAULT_STORE_RULES,
        [StoreType.PGVECTOR],    # ARANGO NOT available
        None,
    )
    assert all(s.store != StoreType.ARANGO for s in scores)


def test_regex_rule():
    custom = [StoreRule(pattern=r"^find\s+\d+", store=StoreType.FAISS, regex=True)]
    scores = apply_rules("find 10 similar products", custom, ALL_STORES, None)
    assert scores and scores[0].store == StoreType.FAISS


def test_no_match_returns_empty():
    scores = apply_rules("zzzz completely unmatched", [], ALL_STORES, None)
    assert scores == []


def test_max_weight_wins_over_sum():
    custom = [
        StoreRule(pattern="foo", store=StoreType.PGVECTOR, weight=0.5),
        StoreRule(pattern="foo", store=StoreType.PGVECTOR, weight=0.9),
    ]
    scores = apply_rules("foo foo foo", custom, ALL_STORES, None)
    assert scores[0].confidence == 0.9   # MAX, not 1.4
```

---

## Agent Instructions

1. Read the spec (§3 Module 4).
2. Verify TASK-785 artifacts land on this branch; confirm `StoreRule` / `StoreScore` / `StoreType` imports.
3. Implement the rules engine and the default rule set.
4. Run the test suite.
5. Move this file to `sdd/tasks/completed/` and update the index.

---

## Completion Note

*(Agent fills this in when done)*
