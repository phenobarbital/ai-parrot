---
type: Wiki Overview
title: 'Feature Specification: Embedding Catalog as Prefix Source of Truth'
id: doc:sdd-specs-embedding-catalog-as-prefix-source-of-truth-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Today, the runtime behaviour of `SentenceTransformerModel` (in
relates_to:
- concept: mod:parrot.embeddings.catalog
  rel: mentions
- concept: mod:parrot.embeddings.huggingface
  rel: mentions
---

# Feature Specification: Embedding Catalog as Prefix Source of Truth

**Feature ID**: FEAT-142
**Date**: 2026-05-04
**Author**: Jesus Lara
**Status**: approved
**Target version**: next minor

---

## 1. Motivation & Business Requirements

### Problem Statement

Today, the runtime behaviour of `SentenceTransformerModel` (in
`parrot/embeddings/huggingface.py`) is governed by `_resolve_prefixes()`, a
hand-maintained function that hardcodes substring matches for every
prefix-requiring model family (E5, BGE-EN-v1.5, Jina v3, NV-Embed-v2,
gte-Qwen2-instruct, e5-mistral-7b-instruct). The curated catalog at
`parrot/embeddings/catalog.py` *also* declares per-model prefix metadata
(`requires_prefix`, `prefix_query`, `prefix_passage`) — but only as
descriptive metadata for the operator-facing API. The catalog has **no
runtime authority**.

This double source of truth is real friction in production:

1. **Adding a new prefix-requiring model takes two PRs to do correctly**:
   one for the catalog entry, another for the resolver branch. Tests in
   `test_catalog_consistency.py` catch the omission only after CI runs —
   if the resolver branch is forgotten, the model silently degrades to
   near-random embeddings without raising.
2. **Even today's session demonstrated the failure mode**: after adding
   `microsoft/harrier-oss-v1-0.6b` to the catalog with
   `requires_prefix=True`, the model is still un-prefixed at inference
   time until a separate edit to `_resolve_prefixes` lands.
3. **The substring matcher is fragile**. The current implementation orders
   branches manually so `e5-mistral-7b-instruct` is not caught by the
   generic `e5-` branch. A future model whose name contains `e5-` would
   silently route through the wrong branch.

### Goals

- Make `parrot/embeddings/catalog.EMBEDDING_MODELS` the **single source of
  truth** for query / passage prefixes consumed by `SentenceTransformerModel`.
- Adding a new prefix-requiring model to the catalog is the **only** edit
  required for `HuggingFaceEmbeddings` to apply the prefix at runtime.
- Preserve the public signature of `_resolve_prefixes(model_name) -> tuple`
  so the change is drop-in for `SentenceTransformerModel.__init__`.
- Preserve the existing bidirectional consistency tests
  (`test_catalog_consistency.py`) — they should keep passing trivially.
- Preserve every behaviour exercised by `test_resolve_prefixes.py` for the
  11 currently-known prefix-requiring models.

### Non-Goals (explicitly out of scope)

- Refactoring the `SentenceTransformerModel.__init__` resolution path —
  it should keep calling `_resolve_prefixes(self.model_name)` unchanged.
- Removing the `ModelType` enum in `huggingface.py` — orthogonal cleanup.
- Adding a public API to register out-of-band models from third-party code.
  Out-of-catalog models continue to receive `(None, None)` (no prefix), which
  matches today's behaviour for unknown models.
- Touching loaders, vector stores, OpenAI/Google embedding wrappers, or any
  consumer of the catalog beyond `parrot/embeddings/huggingface.py`.
- Migrating the catalog to a database / external store. It remains a Python
  list literal compiled at import time.

---

## 2. Architectural Design

### Overview

Replace the body of `_resolve_prefixes(model_name)` with a catalog lookup.
The function keeps its signature `(Optional[str]) -> Tuple[Optional[str],
Optional[str]]` so `SentenceTransformerModel.__init__` is untouched.

Lookup contract:

1. If `model_name` is falsy → return `(None, None)`.
2. Find the entry in `EMBEDDING_MODELS` whose `entry["model"]` matches
   `model_name` (case-insensitive exact match — the HuggingFace identifier
   is canonical, but operators sometimes lowercase names in config files).
3. If found, return `(entry["prefix_query"], entry["prefix_passage"])`.
   This is correct by construction: the catalog's Pydantic validator
   already guarantees both are `None` when `requires_prefix=False` and
   at least one is non-empty when `requires_prefix=True`.
4. If not found, log a single `INFO` message
   (`"Model %s not in embedding catalog; encoding without prefix"`) and
   return `(None, None)`. This preserves today's silent-passthrough
   behaviour for unknown models while making the decision auditable.

The lookup is built once into a module-level `dict[str, tuple]` cache at
import time so the hot path stays O(1) and avoids re-scanning
`EMBEDDING_MODELS` on every `SentenceTransformerModel` instantiation.

### Component Diagram

```
┌──────────────────────────────────┐
│ parrot/embeddings/catalog.py     │  ← single source of truth
│   EMBEDDING_MODELS: list[dict]   │
└─────────────┬────────────────────┘
              │  built once at import
              ▼
┌──────────────────────────────────┐
│ parrot/embeddings/huggingface.py │
│   _PREFIX_LOOKUP: dict[str,tuple]│  ← module-level cache
│   _resolve_prefixes(name)        │  ← reads cache
└─────────────┬────────────────────┘
              │  called from __init__
              ▼
┌──────────────────────────────────┐
│ SentenceTransformerModel         │
│   self._query_prefix, _passage   │
│   embed_documents / embed_query  │
└──────────────────────────────────┘
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot.embeddings.catalog.EMBEDDING_MODELS` | reads | iterated once at import time of `huggingface.py` |
| `parrot.embeddings.huggingface._resolve_prefixes` | replaces body | signature preserved; substring-match branches deleted |
| `SentenceTransformerModel.__init__` | unchanged | keeps calling `_resolve_prefixes(self.model_name)` |
| `tests/embeddings/test_resolve_prefixes.py` | unchanged | every existing test must keep passing |
| `tests/embeddings/test_catalog_consistency.py` | unchanged | bidirectional consistency tests keep passing trivially |

### Data Models

No new Pydantic models. The `EmbeddingModelEntry` schema in `catalog.py`
already enforces the `requires_prefix` ↔ `prefix_query`/`prefix_passage`
invariant (see `_prefix_consistency` validator at `catalog.py:99`).

### New Public Interfaces

None. `_resolve_prefixes` remains a private (underscore-prefixed) helper
with the same signature.

A new module-level constant `_PREFIX_LOOKUP: dict[str, tuple[Optional[str],
Optional[str]]]` is added to `huggingface.py` but is also private.

---

## 3. Module Breakdown

### Module 1: `_PREFIX_LOOKUP` cache + new `_resolve_prefixes` body
- **Path**: `parrot/embeddings/huggingface.py`
- **Responsibility**: Build a `dict[str, tuple]` from `EMBEDDING_MODELS` at
  import time keyed by `model_name.lower()`. Replace the substring-match
  body of `_resolve_prefixes` with a `dict.get` lookup that also tries the
  lowercase form. Add an `INFO` log for cache misses.
- **Depends on**: `parrot.embeddings.catalog.EMBEDDING_MODELS`

### Module 2: Test additions for catalog-driven path
- **Path**: `packages/ai-parrot/tests/embeddings/test_resolve_prefixes.py`
- **Responsibility**: Add a test class
  `TestResolverIsCatalogDriven` that proves the resolver returns prefixes
  for **every** catalog entry where `requires_prefix=True`, including any
  entries added after FEAT-140 (e.g. `microsoft/harrier-oss-v1-0.6b`).
  Existing test classes (`TestNewResolverBranches`,
  `TestExistingResolverUnchanged`, `TestNewModelsInCatalog`) stay as
  regression coverage.
- **Depends on**: Module 1

### Module 3: Test addition for unknown-model behaviour
- **Path**: `packages/ai-parrot/tests/embeddings/test_resolve_prefixes.py`
- **Responsibility**: Add tests that confirm an unknown model
  (`"acme/unknown-model"`) returns `(None, None)` and that the cache miss
  is logged at `INFO` level (using `caplog`).
- **Depends on**: Module 1

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_resolver_returns_prefix_for_every_catalog_entry_requiring_one` | Module 2 | Iterate `EMBEDDING_MODELS` filtered by `requires_prefix=True` and assert `_resolve_prefixes(entry["model"]) == (entry["prefix_query"], entry["prefix_passage"])` for each |
| `test_resolver_returns_none_pair_for_every_catalog_entry_no_prefix` | Module 2 | Iterate `EMBEDDING_MODELS` filtered by `requires_prefix=False` and assert resolver returns `(None, None)` |
| `test_resolver_is_case_insensitive` | Module 2 | `_resolve_prefixes("INTFLOAT/E5-BASE-V2") == ("query: ", "passage: ")` |
| `test_resolver_unknown_model_returns_none_pair` | Module 3 | `_resolve_prefixes("acme/unknown-model") == (None, None)` |
| `test_resolver_unknown_model_logs_info` | Module 3 | `caplog` captures one `INFO` record mentioning the unknown model |
| `test_resolver_handles_empty_string` | Module 3 | `_resolve_prefixes("") == (None, None)` (already covered, confirm regression) |
| `test_resolver_handles_none` | Module 3 | `_resolve_prefixes(None) == (None, None)` (already covered, confirm regression) |
| `test_harrier_oss_resolves_via_catalog` | Module 2 | Specific check: `_resolve_prefixes("microsoft/harrier-oss-v1-0.6b")` returns the catalog's prefix pair (proves the original motivating case is fixed) |

### Integration Tests

| Test | Description |
|---|---|
| (existing) `test_catalog_consistency::TestCatalogToResolver::test_every_hf_entry_matches_resolver` | Must keep passing — now trivially true by construction |
| (existing) `test_catalog_consistency::TestResolverToCatalog::test_every_known_model_prefix_pair_matches` | Must keep passing — the resolver IS the catalog |
| (existing) `test_resolve_prefixes::TestNewResolverBranches::*` | Every test for Jina v3, gte-Qwen2-instruct, e5-mistral-7b-instruct, NV-Embed-v2 must keep passing |
| (existing) `test_resolve_prefixes::TestExistingResolverUnchanged::*` | Every regression test for E5, BGE-EN-v1.5, BGE-M3, no-prefix models must keep passing |

### Test Data / Fixtures

No new fixtures required — every test sources its data from the live
`EMBEDDING_MODELS` list. The cache miss test uses a fabricated identifier
(`"acme/unknown-model"`) that intentionally doesn't appear in the catalog.

---

## 5. Acceptance Criteria

This feature is complete when ALL of the following are true:

- [ ] `_resolve_prefixes` body in `parrot/embeddings/huggingface.py` no longer
      contains any hardcoded `if "..." in lower:` substring branch. All
      family-specific knowledge has been removed.
- [ ] A module-level `_PREFIX_LOOKUP` dict is built once at import time from
      `EMBEDDING_MODELS`.
- [ ] Lookup is case-insensitive (lowercased keys).
- [ ] Unknown models return `(None, None)` and emit one `INFO` log line.
- [ ] All existing tests in `tests/embeddings/test_resolve_prefixes.py`
      pass without modification: `pytest packages/ai-parrot/tests/embeddings/test_resolve_prefixes.py -v`
- [ ] All existing tests in `tests/embeddings/test_catalog_consistency.py`
      pass without modification.
- [ ] New tests from Module 2 and Module 3 pass.
- [ ] Adding `microsoft/harrier-oss-v1-0.6b` (already in the catalog as of
      this branch) requires **zero** edits to `huggingface.py` for the
      resolver to return its prefix pair. Demonstrated by
      `test_harrier_oss_resolves_via_catalog`.
- [ ] No breaking changes to the public API: `_resolve_prefixes` keeps its
      signature; `SentenceTransformerModel.__init__` keeps its call site.
- [ ] No new external dependencies added to `pyproject.toml`.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**

### Verified Imports

```python
# verified: packages/ai-parrot/src/parrot/embeddings/catalog.py:171
from parrot.embeddings.catalog import EMBEDDING_MODELS

# verified: packages/ai-parrot/src/parrot/embeddings/huggingface.py:11
from parrot.embeddings.huggingface import _resolve_prefixes
```

### Existing Class & Function Signatures

```python
# packages/ai-parrot/src/parrot/embeddings/huggingface.py
def _resolve_prefixes(
    model_name: Optional[str],
) -> Tuple[Optional[str], Optional[str]]:  # line 11
    ...

class SentenceTransformerModel(EmbeddingModel):  # line 151
    model_name: str = "sentence-transformers/all-mpnet-base-v2"
    def __init__(self, model_name: str, **kwargs):  # line 157
        super().__init__(model_name=model_name, **kwargs)
        self._query_prefix, self._passage_prefix = _resolve_prefixes(
            self.model_name
        )  # line 169
        ...

    def _apply_query_prefix(self, text: str) -> str:  # line 181
    def _apply_passage_prefix(self, texts: List[str]) -> List[str]:  # line 187
    async def embed_documents(self, texts, batch_size=None) -> List[List[float]]:  # line 193
    async def embed_query(self, text, as_nparray=False) -> Any:  # line 211
```

```python
# packages/ai-parrot/src/parrot/embeddings/catalog.py
class EmbeddingModelEntry(BaseModel):  # line 36
    model: str                         # line 76
    requires_prefix: bool              # line 86
    prefix_query: Optional[str] = None # line 87
    prefix_passage: Optional[str] = None  # line 88

    @model_validator(mode="after")
    def _prefix_consistency(self) -> "EmbeddingModelEntry":  # line 99
        # If requires_prefix=True, at least one prefix must be non-None.
        # If requires_prefix=False, both must be None.
        ...

EMBEDDING_MODELS: List[Dict[str, Any]] = [...]  # line 171
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `_PREFIX_LOOKUP` (new module-level dict) | `EMBEDDING_MODELS` | one-time iteration at import | `packages/ai-parrot/src/parrot/embeddings/huggingface.py` (top-of-module, post-import) |
| `_resolve_prefixes` (refactored body) | `_PREFIX_LOOKUP` | `dict.get(name.lower())` | same file |
| `SentenceTransformerModel.__init__` | `_resolve_prefixes(self.model_name)` | function call (UNCHANGED) | `packages/ai-parrot/src/parrot/embeddings/huggingface.py:169` |

### Existing Tests That Must Keep Passing

```
packages/ai-parrot/tests/embeddings/test_resolve_prefixes.py
  TestNewResolverBranches::test_jina_v3_query_prefix
  TestNewResolverBranches::test_jina_v3_exact_prefix
  TestNewResolverBranches::test_gte_qwen2_instruct_prefix
  TestNewResolverBranches::test_gte_qwen2_instruct_exact_prefix
  TestNewResolverBranches::test_e5_mistral_instruct_not_caught_by_generic_e5
  TestNewResolverBranches::test_e5_mistral_instruct_exact_prefix
  TestNewResolverBranches::test_nv_embed_v2_prefix
  TestNewResolverBranches::test_nv_embed_v2_exact_prefix
  TestExistingResolverUnchanged::test_e5_family_unchanged (parametrized x4)
  TestExistingResolverUnchanged::test_bge_en_v15_unchanged (parametrized x3)
  TestExistingResolverUnchanged::test_no_prefix_models_unchanged (parametrized x8)
  TestExistingResolverUnchanged::test_empty_model_name
  TestExistingResolverUnchanged::test_none_model_name
  TestExistingResolverUnchanged::test_bge_m3_not_caught_by_bge_en_v15_branch

packages/ai-parrot/tests/embeddings/test_catalog_consistency.py
  TestCatalogToResolver::test_every_hf_entry_matches_resolver
  TestCatalogToResolver::test_no_hf_entry_has_prefix_false_with_nonnone_prefix
  TestResolverToCatalog::test_every_known_model_in_catalog
  TestResolverToCatalog::test_every_known_model_requires_prefix
  TestResolverToCatalog::test_every_known_model_prefix_pair_matches
```

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot.embeddings.catalog.get_prefix_for_model()`~~ — does not exist; use `EMBEDDING_MODELS` iteration or build a lookup
- ~~`EmbeddingModelEntry.resolve_prefixes()`~~ — not a method; prefixes are plain dict fields
- ~~`SentenceTransformerModel.set_prefixes()`~~ — does not exist; prefixes are set in `__init__`
- ~~`parrot.embeddings.huggingface.PREFIX_REGISTRY`~~ — no such public constant; the new cache is private (`_PREFIX_LOOKUP`)
- ~~A separate `parrot/embeddings/registry.py` for prefixes~~ — `registry.py` exists but is unrelated to prefixes (it is the model class registry)

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Build the lookup once at module import time, after `EMBEDDING_MODELS` is
  imported. This mirrors the existing pattern in `catalog.py:1218` where
  Pydantic validation of every entry happens at import time.
- Key the lookup by `entry["model"].lower()` to allow case-insensitive
  callers without re-scanning the list per call.
- Keep the `_resolve_prefixes` docstring updated — its current docstring
  enumerates families and is the most-read piece of documentation in this
  module. New docstring should explain that the function is now a thin
  cache lookup driven by the catalog, and that adding a model is a
  catalog-only operation.
- Use `self.logger`-style logging via the module-level
  `logging.getLogger(__name__)` (already imported at `huggingface.py:3`).

### Known Risks / Gotchas

- **Case-insensitive matching can mask typos**. If an operator writes
  `"intfloat/E5-base-v2"` (uppercase E) in a config, today's resolver
  catches it because the substring `"intfloat/e5"` is matched
  case-insensitively. The new resolver should preserve this. Implement by
  storing keys lowercased in `_PREFIX_LOOKUP` and lowercasing the lookup
  argument.
- **Out-of-band models lose any "smart" inference**. Today, an unknown
  model whose name happens to contain `"e5-"` would be matched by the
  generic E5 branch. After this refactor, an out-of-band model returns
  `(None, None)`. This is intentional — silent miscategorisation is worse
  than a known no-op. The cache miss INFO log makes the situation
  observable in production.
- **Import ordering**: building the cache requires `EMBEDDING_MODELS` to
  be fully validated. Place the cache build *after* the existing
  validation loop in `catalog.py` finishes — i.e. import `EMBEDDING_MODELS`
  at the top of `huggingface.py` (already the case via the new import)
  and build the dict once.
- **Test data drift**: the catalog grew during this branch
  (`microsoft/harrier-oss-v1-0.6b`, `Octen/Octen-Embedding-0.6B`). The
  existing `test_catalog_consistency.py::known_prefix_models` fixture is
  a hand-maintained list of 11 names; it must be extended (or replaced
  with a derived list from the catalog) to cover newly-added prefix
  models. This is an explicit task in §3.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| (none) | — | Pure refactor inside `parrot/embeddings/` |

---

## 8. Open Questions

- [x] Should the resolver raise on unknown models, or stay silent? —
      *Resolved by spec author*: stay silent (return `(None, None)`) and
      emit a single `INFO` log per call. Matches today's behaviour and
      keeps backward compatibility for operators using out-of-catalog
      models.
- [x] Should matching be substring or exact? —
      *Resolved by spec author*: case-insensitive **exact** match. The HF
      identifier is canonical; substring matching is what created the
      `e5-mistral-7b-instruct` ordering hazard in the first place.
- [x] Should `_resolve_prefixes` be removed entirely in favour of inlining
      the dict lookup at the call site? —
      *Resolved by spec author*: keep the function. Preserving the public
      symbol means existing tests, imports, and the `SentenceTransformerModel`
      `__init__` line stay untouched.
- [x] Should the existing `test_catalog_consistency.py::known_prefix_models`
      fixture be replaced by a derived list (`[m["model"] for m in
      EMBEDDING_MODELS if m["requires_prefix"]]`) to remove the hand-
      maintenance burden? — *Owner: implementer*. Reasonable yes, but the
      explicit list also acts as documentation. Decide during implementation: Yes, replace it

---

## Worktree Strategy

- **Default isolation unit**: `per-spec`.
- **Rationale**: Three small, sequential modules — refactor + two test
  additions — all touching `parrot/embeddings/huggingface.py` and
  `tests/embeddings/test_resolve_prefixes.py`. No parallelism gain.
- **Cross-feature dependencies**: none. FEAT-140 (catalog metadata
  extension) is already merged on `dev` and provides the prerequisite
  fields.

Suggested worktree name: `feat-142-embedding-catalog-as-prefix-source-of-truth`.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-05-04 | Jesus Lara | Initial draft |
