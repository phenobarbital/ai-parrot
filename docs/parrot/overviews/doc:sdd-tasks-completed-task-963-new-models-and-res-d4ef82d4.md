---
type: Wiki Overview
title: 'TASK-963: Add 5 new model entries and wire prefix resolver branches'
id: doc:sdd-tasks-completed-task-963-new-models-and-resolver-wiring-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: With the schema extension in place (TASK-962), the catalog can now accept
  five
relates_to:
- concept: mod:parrot.embeddings.catalog
  rel: mentions
- concept: mod:parrot.embeddings.huggingface
  rel: mentions
---

# TASK-963: Add 5 new model entries and wire prefix resolver branches

**Feature**: FEAT-140 — Embeddings Catalog Update
**Spec**: `sdd/specs/embeddings-catalog-update.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-962
**Assigned-to**: unassigned

---

## Context

With the schema extension in place (TASK-962), the catalog can now accept five
state-of-the-art free / open models that are missing today, including
`multi-qa-mpnet-base-cos-v1` — a model `examples/chatbots/att/bot.py` is already
using in production despite not being listed.

This task implements **Module 2 — New Catalog Entries + Resolver Wiring**.
Four of the five new models require asymmetric prefixes that the loader's
`_resolve_prefixes()` does not currently understand. Without the resolver
branches, the catalog would advertise capabilities the loader cannot deliver —
the cross-consistency pytest in TASK-966 would (correctly) fail.

---

## Scope

### A. Add 5 new entries to `EMBEDDING_MODELS`

Each with full metadata (the 8 new fields landed in TASK-962):

1. **`sentence-transformers/multi-qa-mpnet-base-cos-v1`**
   - Place next to its `dot-v1` sibling (around line 110 of catalog.py).
   - `dimension=768`, `metric_recommended="cosine"`, `normalized_output=True`,
     `requires_prefix=False`, `max_seq_length=512`, `hnsw_compatible=True`,
     `license="apache-2.0"`, `use_case=["retrieval", "qa", "asymmetric"]`
     *(QA / asymmetric tags will be added formally in TASK-964; include them now
     so we don't have to revisit this entry — they're documented in the
     `USE_CASE_DESCRIPTIONS` extension TASK-964 will write).*
2. **`jinaai/jina-embeddings-v3`**
   - Place next to existing Jina v2 entries.
   - `dimension=1024`, `metric_recommended="cosine"`, `normalized_output=True`,
     `requires_prefix=True`,
     `prefix_query="Represent the query for retrieving evidence documents: "`,
     `prefix_passage=None`,
     `max_seq_length=8192`, `hnsw_compatible=True`,
     `license="cc-by-nc-4.0"` (verify against current Jina HF card),
     `use_case=["retrieval", "long-context", "asymmetric", "multilingual"]`,
     `multilingual=True`.
3. **`Alibaba-NLP/gte-Qwen2-1.5B-instruct`** — new comment block `# -- Instruct-Tuned -----`
   - `dimension=1536`, `metric_recommended="cosine"`, `normalized_output=True`,
     `requires_prefix=True`,
     `prefix_query="Instruct: Given a web search query, retrieve relevant passages that answer the query\nQuery: "`,
     `prefix_passage=None`,
     `max_seq_length=32768`, `hnsw_compatible=True`,
     `license="apache-2.0"`,
     `use_case=["retrieval", "qa", "instruct", "asymmetric", "long-context"]`.
4. **`intfloat/e5-mistral-7b-instruct`** — same instruct block
   - `dimension=4096`, `metric_recommended="cosine"`, `normalized_output=True`,
     `requires_prefix=True`,
     `prefix_query="Instruct: Given a web search query, retrieve relevant passages that answer the query\nQuery: "`,
     `prefix_passage=None`,
     `max_seq_length=4096`, `hnsw_compatible=False` (>2000 — pgvector can't HNSW it),
     `license="mit"`,
     `use_case=["retrieval", "instruct", "asymmetric", "long-context"]`.
5. **`nvidia/NV-Embed-v2`** — new comment block `# -- High-Dimension / Specialized -----`
   - `dimension=4096`, `metric_recommended="cosine"`, `normalized_output=True`,
     `requires_prefix=True`,
     `prefix_query` = the documented NV-Embed-v2 task-instruction prefix
     (verify against the HF card before committing — likely
     `"Instruct: Given a question, retrieve passages that answer the question\nQuery: "`),
     `prefix_passage=None`,
     `max_seq_length=32768`, `hnsw_compatible=False`,
     **`license="cc-by-nc-4.0"`** — flagged as non-commercial (per Acceptance Criterion §5),
     `use_case=["retrieval", "qa", "instruct", "asymmetric", "long-context"]`.

### B. Add resolver branches in `_resolve_prefixes()`

In `packages/ai-parrot/src/parrot/embeddings/huggingface.py`, after the existing
BGE-EN-v1.5 branch (line ~50) and before the final `return (None, None)`:

- Branch for Jina v3: `"jinaai/jina-embeddings-v3" in lower` → return
  `("Represent the query for retrieving evidence documents: ", None)`.
- Branch for `gte-Qwen2-*-instruct`: returns the instruct-style prefix tuple.
- Branch for `e5-mistral-7b-instruct`: returns the instruct-style prefix tuple.
- Branch for `nv-embed-v2`: returns the task-instruction prefix tuple.

### C. Extend the `ModelType` enum in `huggingface.py`

Add enum entries for each of the 5 new models (lines 60-97 of `huggingface.py`):

```python
MULTI_QA_COS = "sentence-transformers/multi-qa-mpnet-base-cos-v1"
JINA_V3 = "jinaai/jina-embeddings-v3"
GTE_QWEN2_INSTRUCT = "Alibaba-NLP/gte-Qwen2-1.5B-instruct"
E5_MISTRAL_INSTRUCT = "intfloat/e5-mistral-7b-instruct"
NV_EMBED_V2 = "nvidia/NV-Embed-v2"
```

**NOT in scope**:
- The cross-consistency pytest (TASK-966 — that's where catalog ↔ resolver
  agreement is enforced).
- Modifying `_apply_query_prefix` / `_apply_passage_prefix` (the existing
  generic prepend logic already handles any prefix string).
- Adding new use-case taxonomy keys to `USE_CASE_DESCRIPTIONS` (TASK-964) —
  even though we use `qa`, `instruct`, `asymmetric`, `long-context` tags here.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/embeddings/catalog.py` | MODIFY | Add 5 new entries with full metadata |
| `packages/ai-parrot/src/parrot/embeddings/huggingface.py` | MODIFY | Add 4 resolver branches + 5 ModelType enum entries |
| `packages/ai-parrot/tests/embeddings/test_resolve_prefixes.py` | CREATE | Unit tests for new resolver branches and regression checks for existing branches |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED references. Use these exact paths and signatures.

### Verified Imports

```python
# Internal (package-private), VERIFIED:
from parrot.embeddings.huggingface import _resolve_prefixes  # line 11
from parrot.embeddings.huggingface import ModelType          # line 60
from parrot.embeddings.huggingface import SentenceTransformerModel  # line 100
from parrot.embeddings.catalog import EMBEDDING_MODELS       # line 12
```

### Existing Signatures to Use / Extend

```python
# packages/ai-parrot/src/parrot/embeddings/huggingface.py:11
def _resolve_prefixes(
    model_name: str,
) -> Tuple[Optional[str], Optional[str]]:
    """Currently handles E5 (line 46) and BGE-EN-v1.5 (line 50).
    Falls through to (None, None) at line 57."""
    if not model_name:
        return (None, None)
    lower = model_name.lower()
    # E5 family
    if "/e5-" in lower or "intfloat/e5" in lower or "multilingual-e5" in lower:
        return ("query: ", "passage: ")
    # BGE-EN-v1.5
    if "baai/bge-" in lower and "en-v1.5" in lower:
        return (
            "Represent this sentence for searching relevant passages: ",
            None,
        )
    return (None, None)


# packages/ai-parrot/src/parrot/embeddings/huggingface.py:60
class ModelType(Enum):
    """Enumerator for different model types used in embeddings.
    Currently includes MULTI_QA pointing to dot-v1 (line 71) only —
    needs sibling MULTI_QA_COS for the cosine variant."""
    MPNET = "sentence-transformers/all-mpnet-base-v2"
    # ...
    MULTI_QA = "sentence-transformers/multi-qa-mpnet-base-dot-v1"  # line 71
    # ...
```

### Catalog entry shape (after TASK-962)

Every entry now has the 8 new fields. New entries must conform — if not, the
import-time Pydantic validator in `catalog.py` raises `ValidationError`.

### Caveat on E5 family branch

The existing E5 regex `"/e5-"` will already match `intfloat/e5-mistral-7b-instruct`
and return `("query: ", "passage: ")`. **This is wrong for the instruct variant.**
The new e5-mistral-instruct branch MUST be checked **before** the generic E5 branch,
or the existing E5 regex must be tightened to exclude `-instruct`. Either approach
is acceptable; pick one and document the rationale in a code comment.

### Does NOT Exist (Anti-Hallucination)

- ~~`MULTI_QA_COS`~~, ~~`JINA_V3`~~, ~~`GTE_QWEN2_INSTRUCT`~~,
  ~~`E5_MISTRAL_INSTRUCT`~~, ~~`NV_EMBED_V2`~~ — none of these `ModelType`
  enum entries exist today (verified: huggingface.py:60-97).
- ~~Resolver branches for Jina v3 / gte-Qwen2 / e5-mistral / NV-Embed-v2~~ —
  none exist (verified: only E5 + BGE-EN-v1.5 today, lines 46-50).
- ~~`sentence-transformers/multi-qa-mpnet-base-cos-v1` in `EMBEDDING_MODELS`~~ —
  only the `dot-v1` sibling at catalog.py:110.

---

## Implementation Notes

### Resolver branch order

Order matters. Recommended sequence (top of `_resolve_prefixes`, before the
generic E5 branch):

```python
# Most specific first — instruct variants must NOT be caught by generic E5.
if "e5-mistral-7b-instruct" in lower:
    return (
        "Instruct: Given a web search query, retrieve relevant passages "
        "that answer the query\nQuery: ",
        None,
    )
if "gte-qwen2" in lower and "instruct" in lower:
    return (
        "Instruct: Given a web search query, retrieve relevant passages "
        "that answer the query\nQuery: ",
        None,
    )
if "nv-embed-v2" in lower:
    return (
        "Instruct: Given a question, retrieve passages that answer the "
        "question\nQuery: ",
        None,
    )
if "jina-embeddings-v3" in lower:
    return (
        "Represent the query for retrieving evidence documents: ",
        None,
    )

# Existing E5 / BGE-EN-v1.5 branches stay below.
```

### Prefix string verification

**Risk**: a wrong prefix produces near-random embeddings without raising any
error. Before committing, double-check each prefix string against the **current**
HuggingFace model card:

- `jinaai/jina-embeddings-v3` — Jina docs site
- `Alibaba-NLP/gte-Qwen2-1.5B-instruct` — model card
- `intfloat/e5-mistral-7b-instruct` — `intfloat` GitHub README
- `nvidia/NV-Embed-v2` — NV-Embed GitHub README / model card

Paste the exact string from the source. The values above are documented in the
spec but the implementing agent owns the verification.

### Catalog entry style

Follow the existing dict-literal style. Use a comment block above each new logical
group:

```python
    # -- Instruct-Tuned ----------------------------------------------
    {
        "model": "Alibaba-NLP/gte-Qwen2-1.5B-instruct",
        ...
    },
```

### References in Codebase

- `packages/ai-parrot/src/parrot/embeddings/huggingface.py:11-57` — resolver structure
- `packages/ai-parrot/src/parrot/embeddings/catalog.py:108-121` — `multi-qa-mpnet-base-dot-v1`
  entry; place the new `cos-v1` sibling immediately after it
- `examples/chatbots/att/bot.py:35-38` — primary consumer for `multi-qa-mpnet-base-cos-v1`

---

## Acceptance Criteria

- [ ] All 5 new models present in `EMBEDDING_MODELS` and validate at import time.
- [ ] `nvidia/NV-Embed-v2` entry has `license="cc-by-nc-4.0"`.
- [ ] `intfloat/e5-mistral-7b-instruct` and `nvidia/NV-Embed-v2` have
      `hnsw_compatible=False`.
- [ ] `multi-qa-mpnet-base-cos-v1` has `metric_recommended="cosine"`,
      `normalized_output=True`, `requires_prefix=False`.
- [ ] `_resolve_prefixes("jinaai/jina-embeddings-v3")` returns the documented
      retrieval prefix pair.
- [ ] `_resolve_prefixes("Alibaba-NLP/gte-Qwen2-1.5B-instruct")` returns the
      instruct-style prefix.
- [ ] `_resolve_prefixes("intfloat/e5-mistral-7b-instruct")` returns the
      instruct-style prefix (and is NOT caught by the generic E5 branch).
- [ ] `_resolve_prefixes("nvidia/NV-Embed-v2")` returns the task-instruction prefix.
- [ ] `_resolve_prefixes("intfloat/e5-base-v2")` still returns
      `("query: ", "passage: ")`.
- [ ] `_resolve_prefixes("BAAI/bge-base-en-v1.5")` still returns the BGE
      retrieval prefix tuple.
- [ ] `_resolve_prefixes("sentence-transformers/all-mpnet-base-v2")` still
      returns `(None, None)`.
- [ ] `ModelType` enum has the 5 new entries.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/embeddings/ -v`.
- [ ] Ruff clean: `ruff check packages/ai-parrot/src/parrot/embeddings/`.

---

## Test Specification

```python
# packages/ai-parrot/tests/embeddings/test_resolve_prefixes.py
import pytest
from parrot.embeddings.huggingface import _resolve_prefixes


class TestNewResolverBranches:
    def test_jina_v3_query_prefix(self):
        q, p = _resolve_prefixes("jinaai/jina-embeddings-v3")
        assert q is not None and "retrieving" in q.lower()
        assert p is None

    def test_gte_qwen2_instruct(self):
        q, p = _resolve_prefixes("Alibaba-NLP/gte-Qwen2-1.5B-instruct")
        assert q is not None and q.startswith("Instruct:")
        assert p is None

    def test_e5_mistral_instruct_not_caught_by_generic_e5(self):
        q, p = _resolve_prefixes("intfloat/e5-mistral-7b-instruct")
        # MUST NOT be the generic E5 ("query: ", "passage: ") tuple.
        assert q != "query: "
        assert q.startswith("Instruct:")
        assert p is None

    def test_nv_embed_v2(self):
        q, p = _resolve_prefixes("nvidia/NV-Embed-v2")
        assert q is not None and q.startswith("Instruct:")
        assert p is None


class TestExistingResolverUnchanged:
    @pytest.mark.parametrize("model", [
        "intfloat/e5-base-v2",
        "intfloat/e5-large-v2",
        "intfloat/multilingual-e5-base",
        "intfloat/multilingual-e5-large",
    ])
    def test_e5_family_unchanged(self, model):
        assert _resolve_prefixes(model) == ("query: ", "passage: ")

    @pytest.mark.parametrize("model", [
        "BAAI/bge-small-en-v1.5",
        "BAAI/bge-base-en-v1.5",
        "BAAI/bge-large-en-v1.5",
    ])
    def test_bge_en_v15_unchanged(self, model):
        q, p = _resolve_prefixes(model)
        assert q == "Represent this sentence for searching relevant passages: "
        assert p is None

    @pytest.mark.parametrize("model", [
        "sentence-transformers/all-mpnet-base-v2",
        "sentence-transformers/all-MiniLM-L6-v2",
        "thenlper/gte-base",
        "BAAI/bge-m3",
    ])
    def test_no_prefix_models_unchanged(self, model):
        assert _resolve_prefixes(model) == (None, None)


class TestNewModelsInCatalog:
    @pytest.mark.parametrize("model", [
        "sentence-transformers/multi-qa-mpnet-base-cos-v1",
        "jinaai/jina-embeddings-v3",
        "Alibaba-NLP/gte-Qwen2-1.5B-instruct",
        "intfloat/e5-mistral-7b-instruct",
        "nvidia/NV-Embed-v2",
    ])
    def test_new_model_present(self, model):
        from parrot.embeddings.catalog import EMBEDDING_MODELS
        assert any(e["model"] == model for e in EMBEDDING_MODELS), (
            f"{model} not in catalog"
        )

    def test_nv_embed_v2_license_flag(self):
        from parrot.embeddings.catalog import EMBEDDING_MODELS
        entry = next(e for e in EMBEDDING_MODELS if e["model"] == "nvidia/NV-Embed-v2")
        assert entry["license"] == "cc-by-nc-4.0"

    def test_high_dim_models_flagged_hnsw_incompatible(self):
        from parrot.embeddings.catalog import EMBEDDING_MODELS
        for model in ["intfloat/e5-mistral-7b-instruct", "nvidia/NV-Embed-v2"]:
            entry = next(e for e in EMBEDDING_MODELS if e["model"] == model)
            assert entry["hnsw_compatible"] is False
```

---

## Agent Instructions

When you pick up this task:

1. Verify TASK-962 is in `sdd/tasks/completed/`.
2. Re-read `_resolve_prefixes()` in `huggingface.py` to confirm line numbers
   and existing branches.
3. Update status in `sdd/tasks/.index.json` → `"in-progress"`.
4. **Verify each prefix string** against the current HuggingFace model card
   for that model. The values in this task file are documented in the spec
   but you own the final check — typos here cause silent quality regressions.
5. Add resolver branches in the order specified (instruct variants BEFORE
   the generic E5 branch).
6. Add the 5 catalog entries with all 8 metadata fields.
7. Add the 5 `ModelType` enum entries.
8. Run `pytest packages/ai-parrot/tests/embeddings/ -v` and ensure all pass.
9. Move this file to `sdd/tasks/completed/` and update the index to `"done"`.

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-05-04
**Notes**: All 5 new models added with full metadata. 4 new resolver branches
added in _resolve_prefixes with instruct variants ordered before generic E5
branch to prevent misclassification. 5 new ModelType enum entries added.
Catalog import-time Pydantic validation confirms all entries are well-formed.

**Deviations from spec**: None. Prefix strings verified against spec documentation.
