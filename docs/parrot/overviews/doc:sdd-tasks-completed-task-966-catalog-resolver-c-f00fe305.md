---
type: Wiki Overview
title: 'TASK-966: Cross-consistency pytest between catalog and _resolve_prefixes'
id: doc:sdd-tasks-completed-task-966-catalog-resolver-consistency-pytest-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Modules 1-4 added a contract: a catalog entry where `requires_prefix=True`'
relates_to:
- concept: mod:parrot.embeddings
  rel: mentions
- concept: mod:parrot.embeddings.catalog
  rel: mentions
- concept: mod:parrot.embeddings.huggingface
  rel: mentions
---

# TASK-966: Cross-consistency pytest between catalog and _resolve_prefixes

**Feature**: FEAT-140 — Embeddings Catalog Update
**Spec**: `sdd/specs/embeddings-catalog-update.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-962, TASK-963, TASK-964, TASK-965
**Assigned-to**: unassigned

---

## Context

Modules 1-4 added a contract: a catalog entry where `requires_prefix=True`
declares specific `prefix_query` / `prefix_passage` strings, and the loader's
`_resolve_prefixes()` must return matching strings for that model name. If the
two ever drift apart, the catalog advertises capabilities the loader does not
deliver — silent retrieval-quality regression.

This task implements **Module 5 — Cross-Consistency Pytest**: a CI test that
fails the build if a prefix-requiring model is added on either side without the
matching counterpart.

---

## Scope

Create `packages/ai-parrot/tests/embeddings/test_catalog_consistency.py`
with two assertions:

### A. Catalog → Resolver direction

For every catalog entry with `provider == "huggingface"`:

```python
expected = (entry["prefix_query"], entry["prefix_passage"])
actual = _resolve_prefixes(entry["model"])
assert actual == expected, (
    f"{entry['model']}: catalog says {expected}, resolver says {actual}"
)
```

This catches: catalog claims `requires_prefix=True` with specific strings,
but resolver returns `(None, None)` or the wrong strings.

### B. Resolver → Catalog direction

For every "known" prefix-requiring model — defined as the fixture list in
spec §4 (`hf_catalog_entries` + `known_prefix_models`):

```python
known = [
    "intfloat/e5-base-v2",
    "intfloat/e5-large-v2",
    "intfloat/multilingual-e5-base",
    "intfloat/multilingual-e5-large",
    "BAAI/bge-small-en-v1.5",
    "BAAI/bge-base-en-v1.5",
    "BAAI/bge-large-en-v1.5",
    "jinaai/jina-embeddings-v3",
    "Alibaba-NLP/gte-Qwen2-1.5B-instruct",
    "intfloat/e5-mistral-7b-instruct",
    "nvidia/NV-Embed-v2",
]
```

For each name, assert:

1. There is a catalog entry with `entry["model"] == name`.
2. That entry has `requires_prefix is True`.
3. `(entry["prefix_query"], entry["prefix_passage"])` matches
   `_resolve_prefixes(name)`.

This catches: resolver knows about a model that the catalog does not advertise,
or advertises with `requires_prefix=False`.

**NOT in scope**:
- Implementing the schema, new entries, taxonomy, or helper (TASK-962 through 965).
- Modifying `_resolve_prefixes` or the catalog (this task is read-only / test-only).
- Integration tests against actual SentenceTransformer downloads.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/embeddings/test_catalog_consistency.py` | CREATE | Cross-consistency pytest |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
import pytest
from parrot.embeddings.catalog import EMBEDDING_MODELS         # line 12
from parrot.embeddings.huggingface import _resolve_prefixes    # line 11
```

### Existing Signatures

```python
# packages/ai-parrot/src/parrot/embeddings/huggingface.py:11
def _resolve_prefixes(
    model_name: str,
) -> Tuple[Optional[str], Optional[str]]:
    ...

# After TASK-962, every entry has:
{
    "model": str,
    "provider": "huggingface" | "openai" | "google",
    "requires_prefix": bool,
    "prefix_query": Optional[str],
    "prefix_passage": Optional[str],
    ...
}
```

### Test directory layout (verified)

```
packages/ai-parrot/tests/embeddings/
├── __init__.py
├── test_base_registry.py      # not modified — does not import EMBEDDING_MODELS
├── test_registry.py           # not modified
└── test_catalog_consistency.py  # NEW (this task)
```

### Does NOT Exist

- ~~A pre-existing `test_catalog_consistency.py`~~ — verified empty under
  `tests/embeddings/`.
- ~~A `_resolve_prefixes` re-export from `parrot.embeddings`~~ — must import
  from `parrot.embeddings.huggingface` directly.

---

## Implementation Notes

### Pattern to Follow

```python
# packages/ai-parrot/tests/embeddings/test_catalog_consistency.py
"""Cross-consistency between EMBEDDING_MODELS and _resolve_prefixes.

The catalog and the loader's prefix resolver are kept in sync by this test:
adding a prefix-requiring model on either side without the matching
counterpart will fail CI.
"""
import pytest

from parrot.embeddings.catalog import EMBEDDING_MODELS
from parrot.embeddings.huggingface import _resolve_prefixes


@pytest.fixture
def hf_catalog_entries() -> list[dict]:
    """Entries that the resolver actually serves (HuggingFace only)."""
    return [e for e in EMBEDDING_MODELS if e["provider"] == "huggingface"]


@pytest.fixture
def known_prefix_models() -> list[str]:
    """Models that MUST be handled by both sides (per spec §4)."""
    return [
        "intfloat/e5-base-v2",
        "intfloat/e5-large-v2",
        "intfloat/multilingual-e5-base",
        "intfloat/multilingual-e5-large",
        "BAAI/bge-small-en-v1.5",
        "BAAI/bge-base-en-v1.5",
        "BAAI/bge-large-en-v1.5",
        "jinaai/jina-embeddings-v3",
        "Alibaba-NLP/gte-Qwen2-1.5B-instruct",
        "intfloat/e5-mistral-7b-instruct",
        "nvidia/NV-Embed-v2",
    ]


class TestCatalogToResolver:
    def test_every_hf_entry_matches_resolver(self, hf_catalog_entries):
        mismatches = []
        for entry in hf_catalog_entries:
            expected = (entry["prefix_query"], entry["prefix_passage"])
            actual = _resolve_prefixes(entry["model"])
            if actual != expected:
                mismatches.append(
                    f"{entry['model']}: catalog={expected!r}  resolver={actual!r}"
                )
        assert not mismatches, "Catalog ↔ resolver mismatch:\n" + "\n".join(mismatches)


class TestResolverToCatalog:
    def test_every_known_model_in_catalog(self, known_prefix_models):
        catalog_names = {e["model"] for e in EMBEDDING_MODELS}
        missing = [m for m in known_prefix_models if m not in catalog_names]
        assert not missing, f"Resolver knows but catalog missing: {missing}"

    def test_every_known_model_requires_prefix(self, known_prefix_models):
        problems = []
        for name in known_prefix_models:
            entry = next(
                (e for e in EMBEDDING_MODELS if e["model"] == name), None
            )
            if entry is None:
                continue  # caught by the previous test
            if entry["requires_prefix"] is not True:
                problems.append(f"{name}: requires_prefix={entry['requires_prefix']}")
        assert not problems, "\n".join(problems)

    def test_every_known_model_prefix_pair_matches(self, known_prefix_models):
        problems = []
        for name in known_prefix_models:
            entry = next(
                (e for e in EMBEDDING_MODELS if e["model"] == name), None
            )
            if entry is None:
                continue
            expected = (entry["prefix_query"], entry["prefix_passage"])
            actual = _resolve_prefixes(name)
            if actual != expected:
                problems.append(
                    f"{name}: catalog={expected!r}  resolver={actual!r}"
                )
        assert not problems, "\n".join(problems)
```

### Key Constraints

- Use only `pytest` and the two imports above. No external network, no fixtures
  beyond the two listed.
- Tests must run in <1 second. They are pure data comparisons.
- Diagnostic output: when an assertion fails, list every offender — do NOT
  bail on the first one. Engineering rule: when CI fails, the human running
  it should see the full picture.

### References in Codebase

- `packages/ai-parrot/tests/embeddings/test_base_registry.py` — pytest style
  for this directory (class-based grouping).
- Spec section 4 "Test Specification" — fixtures defined there are the source
  of the lists used here.

---

## Acceptance Criteria

- [ ] File `packages/ai-parrot/tests/embeddings/test_catalog_consistency.py` exists.
- [ ] All catalog ↔ resolver pairs match for every HF entry (test_every_hf_entry_matches_resolver passes).
- [ ] All 11 "known prefix models" are present in the catalog.
- [ ] All 11 are flagged `requires_prefix=True` and have matching prefix pairs.
- [ ] Suite runs in <1 second:
      `pytest packages/ai-parrot/tests/embeddings/test_catalog_consistency.py -v`.
- [ ] Existing tests still pass: `pytest packages/ai-parrot/tests/embeddings/ -v`.
- [ ] No ruff errors: `ruff check packages/ai-parrot/tests/embeddings/test_catalog_consistency.py`.

---

## Test Specification

The file IS the test specification — see "Implementation Notes" above for the
full scaffold. The agent may add additional sanity checks (e.g. assert that no
HF entry has `requires_prefix=False` AND a non-None prefix — this is already
enforced by the `EmbeddingModelEntry` validator, but a redundant test here
makes the contract explicit at the test layer too).

---

## Agent Instructions

1. Verify TASK-962, TASK-963, TASK-964, TASK-965 are all in
   `sdd/tasks/completed/`.
2. Update status in `sdd/tasks/.index.json` → `"in-progress"`.
3. Create the test file using the scaffold above.
4. Run the suite — every test must pass on the first try (TASK-962 and
   TASK-963 should already have aligned the catalog and resolver).
5. If a test fails: this is a real defect upstream — STOP, document in the
   completion note, do not paper over with weakened assertions.
6. Run the full embeddings suite to confirm no regressions:
   `pytest packages/ai-parrot/tests/embeddings/ -v`.
7. Move this file to `sdd/tasks/completed/` and update the index.

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-05-04
**Notes**: test_catalog_consistency.py created with both consistency
directions (catalog->resolver and resolver->catalog). All 5 tests in
the file pass on first run. Suite runs in < 2s (pure data comparison).
All 11 known prefix models are present and consistent.

**Deviations from spec**: None.
