---
type: Wiki Overview
title: 'TASK-974: Add catalog-driven and unknown-model tests for `_resolve_prefixes`'
id: doc:sdd-tasks-completed-task-974-tests-catalog-driven-and-unknown-model-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: After TASK-973 makes `_resolve_prefixes` a catalog-driven lookup, the
relates_to:
- concept: mod:parrot.embeddings.catalog
  rel: mentions
- concept: mod:parrot.embeddings.huggingface
  rel: mentions
---

# TASK-974: Add catalog-driven and unknown-model tests for `_resolve_prefixes`

**Feature**: FEAT-142 — Embedding Catalog as Prefix Source of Truth
**Spec**: `sdd/specs/embedding-catalog-as-prefix-source-of-truth.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-973
**Assigned-to**: unassigned

---

## Context

After TASK-973 makes `_resolve_prefixes` a catalog-driven lookup, the
existing test suite already covers the 11 historically-known prefix-requiring
models. What it does NOT yet cover is:

1. The general property that **every** catalog entry with
   `requires_prefix=True` resolves correctly via the catalog (including
   models added after FEAT-140, such as `microsoft/harrier-oss-v1-0.6b`).
2. The new unknown-model path: `(None, None)` plus one INFO log line.
3. Case-insensitive lookup behaviour.

These tests close the loop on the spec's central promise — adding a model
to the catalog is enough to make it work at runtime — and lock in the
backward-compatible silent-passthrough behaviour for out-of-catalog models.

This task implements **Modules 2 and 3** of the spec (combined into a
single task because both touch the same test file). See spec §3 (Module 2,
Module 3), §4 (Test Specification), and §5 (Acceptance Criteria).

---

## Scope

- Add a new test class `TestResolverIsCatalogDriven` to
  `packages/ai-parrot/tests/embeddings/test_resolve_prefixes.py` that
  iterates `EMBEDDING_MODELS` and asserts:
  - For every entry with `requires_prefix=True`,
    `_resolve_prefixes(entry["model"])` equals
    `(entry["prefix_query"], entry["prefix_passage"])`.
  - For every entry with `requires_prefix=False`,
    `_resolve_prefixes(entry["model"])` equals `(None, None)`.
- Add a parametric test `test_resolver_is_case_insensitive` that verifies
  uppercase/mixed-case identifiers still resolve to the catalog pair
  (e.g. `_resolve_prefixes("INTFLOAT/E5-BASE-V2") == ("query: ", "passage: ")`).
- Add a specific demo test `test_harrier_oss_resolves_via_catalog` that
  proves `microsoft/harrier-oss-v1-0.6b` (added in this branch without
  any change to the resolver) returns its catalog prefix pair. This is
  the regression anchor for the entire feature motivation.
- Add a new test class `TestResolverUnknownModel` covering:
  - `_resolve_prefixes("acme/unknown-model")` returns `(None, None)`.
  - The cache-miss path emits exactly one `INFO` log record mentioning
    the unknown model identifier (use pytest's `caplog` fixture).
  - Empty string and `None` continue to return `(None, None)` and emit
    NO log line (silent fast-path for falsy input — no need to log).
- Do NOT modify the existing test classes (`TestNewResolverBranches`,
  `TestExistingResolverUnchanged`, `TestNewModelsInCatalog`). They stay
  as regression coverage and must keep passing.
- Do NOT modify `test_catalog_consistency.py` — it already validates the
  bidirectional catalog ↔ resolver contract and continues to apply.

**NOT in scope**:
- The `_resolve_prefixes` refactor itself (TASK-973).
- Replacing the hand-maintained `known_prefix_models` fixture in
  `test_catalog_consistency.py` with a derived list — spec §8 leaves this
  decision open and explicitly defers it to the implementer; do NOT
  bundle that change here.
- Touching any source file under `packages/ai-parrot/src/`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/embeddings/test_resolve_prefixes.py` | MODIFY | Append two new test classes: `TestResolverIsCatalogDriven`, `TestResolverUnknownModel` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Existing imports at the top of test_resolve_prefixes.py — keep them.
# verified: packages/ai-parrot/tests/embeddings/test_resolve_prefixes.py:1-9
import pytest
from parrot.embeddings.huggingface import _resolve_prefixes

# Add this import for the new classes:
# verified: packages/ai-parrot/src/parrot/embeddings/catalog.py:171
from parrot.embeddings.catalog import EMBEDDING_MODELS
```

### Existing Test Classes (DO NOT MODIFY)

```python
# packages/ai-parrot/tests/embeddings/test_resolve_prefixes.py
class TestNewResolverBranches:
    # 8 tests covering Jina v3, gte-Qwen2-instruct, e5-mistral-7b-instruct, NV-Embed-v2

class TestExistingResolverUnchanged:
    # parametric tests covering E5 family (x4), BGE-EN-v1.5 (x3),
    # no-prefix models (x8), empty/None handling, BGE-M3 disambiguation

class TestNewModelsInCatalog:
    # 5 tests verifying catalog metadata for the FEAT-140 additions
```

### Catalog Schema (relevant fields)

```python
# packages/ai-parrot/src/parrot/embeddings/catalog.py:36-96
class EmbeddingModelEntry(BaseModel):
    model: str                            # e.g. "intfloat/e5-base-v2"
    requires_prefix: bool
    prefix_query: Optional[str] = None
    prefix_passage: Optional[str] = None
    # ... other fields irrelevant to this task
```

### Models Confirmed in the Catalog (as of branch HEAD)

```python
# Sample of prefix-requiring entries to spot-check while writing tests:
# - intfloat/e5-base-v2          (prefix_query="query: ", prefix_passage="passage: ")
# - BAAI/bge-base-en-v1.5        (prefix_query="Represent this sentence...", prefix_passage=None)
# - jinaai/jina-embeddings-v3    (prefix_query="Represent the query...", prefix_passage=None)
# - Alibaba-NLP/gte-Qwen2-1.5B-instruct  (prefix_query="Instruct: ...", prefix_passage=None)
# - intfloat/e5-mistral-7b-instruct       (prefix_query="Instruct: ...", prefix_passage=None)
# - nvidia/NV-Embed-v2                    (prefix_query="Instruct: ...", prefix_passage=None)
# - microsoft/harrier-oss-v1-0.6b         (prefix_query="Instruct: ...", prefix_passage=None)  ← motivating case

# Sample of non-prefix entries:
# - thenlper/gte-base, BAAI/bge-m3, Octen/Octen-Embedding-0.6B, etc.
```

### Does NOT Exist

- ~~`pytest.LogCaptureFixture`~~ — exists as a type but use the `caplog`
  fixture directly (lowercase), the way pytest documents it
- ~~`parrot.embeddings.huggingface._PREFIX_LOOKUP`~~ — added in TASK-973
  but it is private; tests should NOT import or assert on it. They go
  through `_resolve_prefixes` only.
- ~~`parrot.embeddings.catalog.get_prefix_for_model()`~~ — does not exist
- ~~A `parrot.embeddings.catalog.requires_prefix()` helper~~ — does not
  exist; iterate `EMBEDDING_MODELS` directly

---

## Implementation Notes

### Sketch (do not copy verbatim — adapt to your style)

```python
# Append to the end of test_resolve_prefixes.py

import logging
from parrot.embeddings.catalog import EMBEDDING_MODELS


class TestResolverIsCatalogDriven:
    """Verify _resolve_prefixes is driven by EMBEDDING_MODELS for all entries."""

    @pytest.mark.parametrize(
        "entry",
        [e for e in EMBEDDING_MODELS if e["requires_prefix"]],
        ids=lambda e: e["model"],
    )
    def test_prefix_requiring_entry_resolves_via_catalog(self, entry):
        """Every catalog entry with requires_prefix=True resolves to its catalog pair."""
        expected = (entry["prefix_query"], entry["prefix_passage"])
        actual = _resolve_prefixes(entry["model"])
        assert actual == expected, (
            f"{entry['model']}: catalog={expected!r} vs resolver={actual!r}"
        )

    @pytest.mark.parametrize(
        "entry",
        [e for e in EMBEDDING_MODELS if not e["requires_prefix"]],
        ids=lambda e: e["model"],
    )
    def test_non_prefix_entry_returns_none_pair(self, entry):
        """Every catalog entry with requires_prefix=False resolves to (None, None)."""
        assert _resolve_prefixes(entry["model"]) == (None, None)

    def test_resolver_is_case_insensitive(self):
        """Lookup must be case-insensitive — uppercase identifier still resolves."""
        assert _resolve_prefixes("INTFLOAT/E5-BASE-V2") == ("query: ", "passage: ")

    def test_harrier_oss_resolves_via_catalog(self):
        """Regression anchor: harrier-oss was added to the catalog WITHOUT touching
        _resolve_prefixes. This test proves the catalog-driven path works for
        models added after the original FEAT-140 family branches."""
        q, p = _resolve_prefixes("microsoft/harrier-oss-v1-0.6b")
        assert q is not None
        assert q.startswith("Instruct:")
        assert "Query:" in q
        assert p is None


class TestResolverUnknownModel:
    """Verify out-of-catalog models return (None, None) with one INFO log."""

    def test_unknown_model_returns_none_pair(self):
        assert _resolve_prefixes("acme/unknown-model") == (None, None)

    def test_unknown_model_logs_info(self, caplog):
        """One INFO log record is emitted for an unknown model."""
        caplog.clear()
        with caplog.at_level(logging.INFO, logger="parrot.embeddings.huggingface"):
            _resolve_prefixes("acme/unknown-model-xyz")
        info_records = [
            r for r in caplog.records
            if r.levelno == logging.INFO and "acme/unknown-model-xyz" in r.getMessage()
        ]
        assert len(info_records) == 1, (
            f"Expected 1 INFO record mentioning the unknown model, got {len(info_records)}"
        )

    def test_empty_string_silent(self, caplog):
        """Falsy input returns (None, None) without emitting any log."""
        caplog.clear()
        with caplog.at_level(logging.INFO, logger="parrot.embeddings.huggingface"):
            assert _resolve_prefixes("") == (None, None)
        assert not caplog.records, "Empty string should not trigger any log line"

    def test_none_silent(self, caplog):
        """None input returns (None, None) without emitting any log."""
        caplog.clear()
        with caplog.at_level(logging.INFO, logger="parrot.embeddings.huggingface"):
            assert _resolve_prefixes(None) == (None, None)
        assert not caplog.records, "None should not trigger any log line"
```

### Key Constraints

- **Use `caplog.at_level(..., logger="parrot.embeddings.huggingface")`**
  to scope log capture to the module under test. Without `logger=...`,
  capture pulls every record in the propagation chain and the assertions
  become flaky.
- **Use `caplog.clear()` before each scenario** so prior tests' log
  records don't bleed into your assertions.
- **Iterate `EMBEDDING_MODELS` directly in `@pytest.mark.parametrize`**.
  This auto-extends coverage as the catalog grows — exactly the behaviour
  the spec promises.
- **Do not import `_PREFIX_LOOKUP`**. It is private. Test the public
  function only.
- **Do not modify the existing test classes**. New tests append; old
  tests stay as the regression anchor.

### References in Codebase

- `packages/ai-parrot/tests/embeddings/test_resolve_prefixes.py:104-128` —
  existing parametric pattern using `@pytest.mark.parametrize` with a
  hand-maintained list. Match the style.
- `packages/ai-parrot/tests/embeddings/test_catalog_consistency.py:24-46`
  — existing fixture pattern that filters `EMBEDDING_MODELS` by provider.
  Same iteration approach applies here.

---

## Acceptance Criteria

- [ ] Two new test classes added to `test_resolve_prefixes.py`:
      `TestResolverIsCatalogDriven` and `TestResolverUnknownModel`.
- [ ] No existing test class is modified.
- [ ] `TestResolverIsCatalogDriven` includes a parametric test over all
      catalog entries with `requires_prefix=True` and another over all
      entries with `requires_prefix=False`.
- [ ] `test_harrier_oss_resolves_via_catalog` is present and passes.
- [ ] `test_resolver_is_case_insensitive` is present and passes.
- [ ] `TestResolverUnknownModel` includes the four cases listed in the
      sketch (unknown returns pair, unknown logs INFO, empty silent,
      None silent).
- [ ] All tests pass:
      `pytest packages/ai-parrot/tests/embeddings/test_resolve_prefixes.py -v`
- [ ] No regressions in catalog consistency:
      `pytest packages/ai-parrot/tests/embeddings/test_catalog_consistency.py -v`
- [ ] No lint regressions:
      `ruff check packages/ai-parrot/tests/embeddings/test_resolve_prefixes.py`
- [ ] No changes outside `packages/ai-parrot/tests/embeddings/test_resolve_prefixes.py`.

---

## Test Specification

The "test specification" of this task is the test code itself — the
sketch above is the minimal scaffold the implementing agent must produce
(adjusted for style). Adding more edge-case tests is welcome where they
genuinely add coverage; do NOT pad with redundant tests.

Run-and-verify command:

```bash
source .venv/bin/activate
pytest packages/ai-parrot/tests/embeddings/test_resolve_prefixes.py \
       packages/ai-parrot/tests/embeddings/test_catalog_consistency.py \
       -v --tb=short
# Expected: all existing tests + the new ones pass.
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context.
2. **Check dependencies**: TASK-973 must be in `sdd/tasks/completed/`. If
   not, stop — the catalog-driven behaviour you are testing does not exist
   yet.
3. **Verify the Codebase Contract**:
   - Confirm `_PREFIX_LOOKUP` exists in `huggingface.py` (proof TASK-973
     landed) but do NOT import it.
   - Confirm the module-level `logger` exists in `huggingface.py` (added
     by TASK-973) — needed for the `caplog` scoping.
4. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`.
5. **Append the two test classes** to the existing test file. Do not
   reorder or modify the existing classes.
6. **Run the test suite** to verify pass.
7. **Move this file** to `sdd/tasks/completed/TASK-974-tests-catalog-driven-and-unknown-model.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-05-04
**Notes**: Appended `TestResolverIsCatalogDriven` and `TestResolverUnknownModel`
to `test_resolve_prefixes.py`. The parametric tests auto-cover all 39 catalog entries
(11 prefix-requiring, 28 non-prefix). `test_harrier_oss_resolves_via_catalog` confirms
the motivating case (model added without touching the resolver). All 85 tests pass.
No modifications to existing test classes. No changes outside the single test file.

**Deviations from spec**: none
