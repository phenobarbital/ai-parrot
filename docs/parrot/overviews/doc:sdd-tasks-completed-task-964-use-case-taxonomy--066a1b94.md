---
type: Wiki Overview
title: 'TASK-964: Extend USE_CASE_DESCRIPTIONS taxonomy and reassign tags on existing
  entries'
id: doc:sdd-tasks-completed-task-964-use-case-taxonomy-extension-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The catalog currently advertises 5 use-case tags (`similarity`, `retrieval`,
relates_to:
- concept: mod:parrot.embeddings
  rel: mentions
- concept: mod:parrot.embeddings.catalog
  rel: mentions
---

# TASK-964: Extend USE_CASE_DESCRIPTIONS taxonomy and reassign tags on existing entries

**Feature**: FEAT-140 — Embeddings Catalog Update
**Spec**: `sdd/specs/embeddings-catalog-update.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-962, TASK-963
**Assigned-to**: unassigned

---

## Context

The catalog currently advertises 5 use-case tags (`similarity`, `retrieval`,
`clustering`, `multilingual`, `code`). This taxonomy is too coarse to express
practically important distinctions:

- **QA-specific** retrievers (`multi-qa-*`) vs general retrieval models.
- **Long-context** models (>4096 tokens) vs ordinary 512-token models.
- **Instruct-tuned** retrievers (gte-Qwen2, e5-mistral, NV-Embed-v2) which
  require task-specific prompts.
- **Asymmetric** (query/passage trained differently) vs **symmetric**
  (paraphrase-style) models.

This task implements **Module 3 — Use-Case Taxonomy Extension**. It is purely
additive: existing tags stay on every entry; only new tags are appended where
applicable. Frontends already consuming the original five tags keep working.

---

## Scope

### A. Extend `USE_CASE_DESCRIPTIONS`

Add 5 new keys to the dict at `catalog.py:480-501`:

```python
"qa": (
    "Question-answering retrieval — models trained or fine-tuned "
    "specifically on Q&A pairs (e.g. multi-qa-mpnet, NV-Embed-v2)."
),
"long-context": (
    "Long-context embedding — models that natively handle "
    "≥4096-token inputs (e.g. bge-m3, jina-embeddings-v3)."
),
"instruct": (
    "Instruction-tuned retrievers — require a task-specific "
    "instruction template prepended to queries (e.g. gte-Qwen2-instruct, "
    "e5-mistral-7b-instruct, NV-Embed-v2)."
),
"asymmetric": (
    "Asymmetric retrieval — query and passage are encoded with "
    "different prompts/prefixes (e.g. E5, BGE-EN-v1.5, Jina v3)."
),
"symmetric": (
    "Symmetric similarity — query and passage encoded the same way "
    "(e.g. paraphrase-multilingual-mpnet, all-mpnet-base-v2)."
),
```

### B. Reassign tags on existing entries

Walk every existing `EMBEDDING_MODELS` entry and **append** the new tags where
applicable (do NOT remove existing tags):

| Rule | Add this tag |
|---|---|
| Model name contains `multi-qa-` | `"qa"` |
| Model name contains `multi-qa-` OR is `e5-*` (any) OR is `bge-*-en-v1.5` OR is Jina v3 OR is any instruct variant | `"asymmetric"` |
| Model name contains `paraphrase-` | `"symmetric"` |
| Entry has `max_seq_length >= 4096` | `"long-context"` |
| Entry has `requires_prefix=True` AND name contains `instruct` OR is `nv-embed-v2` | `"instruct"` |

The new entries already added in TASK-963 should already carry these tags
where relevant — this task fills in the gaps on existing entries (E5 family
gets `asymmetric`; BGE-EN-v1.5 gets `asymmetric`; bge-m3 gets `long-context`;
Jina v2 entries with 8192 ctx get `long-context`; paraphrase-* gets
`symmetric`; multi-qa-mpnet-base-dot-v1 gets `qa` + `asymmetric`).

**NOT in scope**:
- Modifying `get_embedding_models()` (TASK-965).
- Removing or renaming any existing tag (this is purely additive).
- Modifying `huggingface.py` (TASK-963 owns that).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/embeddings/catalog.py` | MODIFY | Extend `USE_CASE_DESCRIPTIONS` and append new tags to existing entries |
| `packages/ai-parrot/tests/embeddings/test_use_case_taxonomy.py` | CREATE | Unit tests for the new tags and tag-assignment rules |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED references.

### Verified Imports

```python
from parrot.embeddings.catalog import EMBEDDING_MODELS       # line 12
from parrot.embeddings.catalog import USE_CASE_DESCRIPTIONS  # line 480
from parrot.embeddings.catalog import get_use_cases          # line 528
from parrot.embeddings import USE_CASE_DESCRIPTIONS          # re-exported
```

### Existing Signatures

```python
# packages/ai-parrot/src/parrot/embeddings/catalog.py:480-501
USE_CASE_DESCRIPTIONS: Dict[str, str] = {
    "similarity": "...",
    "retrieval": "...",
    "clustering": "...",
    "multilingual": "...",
    "code": "...",
}

# packages/ai-parrot/src/parrot/embeddings/catalog.py:528
def get_use_cases() -> Dict[str, str]:
    """Return available use-case categories and their descriptions."""
    return dict(USE_CASE_DESCRIPTIONS)
```

### Existing per-entry `use_case` examples (verified)

```python
# catalog.py:23 — all-mpnet-base-v2
"use_case": ["similarity", "clustering"]

# catalog.py:64 — gte-small
"use_case": ["retrieval", "similarity"]

# catalog.py:116 — multi-qa-mpnet-base-dot-v1
"use_case": ["retrieval"]
```

### Does NOT Exist (Anti-Hallucination)

- ~~Use-case keys `qa` / `long-context` / `instruct` / `asymmetric` /
  `symmetric` in `USE_CASE_DESCRIPTIONS`~~ — only the original 5 exist today
  (verified: catalog.py:480-501).
- ~~A method that auto-derives use_case tags from metadata~~ — assignment
  is manual. We do NOT add machinery for it.

---

## Implementation Notes

### Pattern to Follow

Edit each existing entry's `"use_case"` list in place. Example for
`multi-qa-mpnet-base-dot-v1` (catalog.py:116):

```python
# before
"use_case": ["retrieval"],
# after
"use_case": ["retrieval", "qa", "asymmetric"],
```

For E5 entries:

```python
# before
"use_case": ["retrieval", "similarity"],
# after
"use_case": ["retrieval", "similarity", "asymmetric"],
```

### Key Constraints

- Adding tags MUST keep the order: existing tags first, new tags appended.
  This makes diffs reviewable and preserves the "primary use case first"
  intuition consumers might rely on.
- Run the new test `test_existing_use_cases_preserved` (below) to be sure
  no existing tag was accidentally dropped.
- Tag assignment is a per-entry judgement informed by the rules in §B above —
  if a rule is ambiguous (e.g. is `bge-m3` long-context? It has 8192 ctx →
  yes), apply the rule literally.

### References in Codebase

- `packages/ai-parrot/src/parrot/embeddings/catalog.py:480-501` — current
  `USE_CASE_DESCRIPTIONS` dict
- `packages/ai-parrot/src/parrot/embeddings/catalog.py:12-476` — every entry
  whose `use_case` list may need extending

---

## Acceptance Criteria

- [ ] `USE_CASE_DESCRIPTIONS` contains 10 keys: original 5
      (`similarity`, `retrieval`, `clustering`, `multilingual`, `code`) +
      new 5 (`qa`, `long-context`, `instruct`, `asymmetric`, `symmetric`).
- [ ] Every original tag is still present on every entry that had it before
      this task started (no regressions).
- [ ] Every `multi-qa-*` entry has `"qa"` in its `use_case` list.
- [ ] Every E5 / BGE-EN-v1.5 / Jina v3 / `*-instruct` / NV-Embed-v2 entry has
      `"asymmetric"` in its `use_case` list.
- [ ] Every entry where `max_seq_length >= 4096` has `"long-context"` in its
      `use_case` list.
- [ ] Every `paraphrase-*` entry has `"symmetric"` in its `use_case` list.
- [ ] `bge-m3` has `"long-context"` (8192 ctx).
- [ ] `get_use_cases()` returns the 10-key dict.
- [ ] Catalog still validates at import (TASK-962 validators are unchanged).
- [ ] All tests pass: `pytest packages/ai-parrot/tests/embeddings/ -v`.

---

## Test Specification

```python
# packages/ai-parrot/tests/embeddings/test_use_case_taxonomy.py
import pytest
from parrot.embeddings.catalog import (
    EMBEDDING_MODELS, USE_CASE_DESCRIPTIONS, get_use_cases,
)


class TestUseCaseDescriptionsExtended:
    def test_original_five_preserved(self):
        for key in ("similarity", "retrieval", "clustering",
                    "multilingual", "code"):
            assert key in USE_CASE_DESCRIPTIONS

    def test_five_new_keys_present(self):
        for key in ("qa", "long-context", "instruct",
                    "asymmetric", "symmetric"):
            assert key in USE_CASE_DESCRIPTIONS

    def test_get_use_cases_returns_ten_keys(self):
        assert set(get_use_cases().keys()) >= {
            "similarity", "retrieval", "clustering", "multilingual", "code",
            "qa", "long-context", "instruct", "asymmetric", "symmetric",
        }


class TestTagAssignmentRules:
    def test_multi_qa_models_have_qa_tag(self):
        for entry in EMBEDDING_MODELS:
            if "multi-qa-" in entry["model"]:
                assert "qa" in entry["use_case"], (
                    f"{entry['model']} missing 'qa' tag"
                )

    def test_paraphrase_models_have_symmetric(self):
        for entry in EMBEDDING_MODELS:
            if "paraphrase-" in entry["model"]:
                assert "symmetric" in entry["use_case"]

    def test_long_context_tag_for_4k_plus(self):
        for entry in EMBEDDING_MODELS:
            if entry["max_seq_length"] >= 4096:
                assert "long-context" in entry["use_case"], (
                    f"{entry['model']} (ctx={entry['max_seq_length']}) "
                    "missing 'long-context' tag"
                )

    def test_e5_and_bge_en_v15_have_asymmetric(self):
        for entry in EMBEDDING_MODELS:
            name = entry["model"].lower()
            is_e5 = "/e5-" in name or "intfloat/e5" in name or "multilingual-e5" in name
            is_bge_en = "baai/bge-" in name and "en-v1.5" in name
            if (is_e5 or is_bge_en) and "-instruct" not in name:
                assert "asymmetric" in entry["use_case"], (
                    f"{entry['model']} missing 'asymmetric' tag"
                )

    def test_instruct_models_have_instruct_tag(self):
        for entry in EMBEDDING_MODELS:
            name = entry["model"].lower()
            if "instruct" in name or "nv-embed-v2" in name:
                assert "instruct" in entry["use_case"]
```

---

## Agent Instructions

When you pick up this task:

1. Verify TASK-962 and TASK-963 are in `sdd/tasks/completed/`.
2. Update status in `sdd/tasks/.index.json` → `"in-progress"`.
3. Add the 5 new keys to `USE_CASE_DESCRIPTIONS`.
4. Walk every entry in `EMBEDDING_MODELS` and append the new tags per the
   rules above. Existing tags stay first; new tags appended.
5. Run `pytest packages/ai-parrot/tests/embeddings/ -v`.
6. Move this file to `sdd/tasks/completed/` and update the index.

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-05-04
**Notes**: USE_CASE_DESCRIPTIONS extended with 5 new keys. Tags reassigned
on all existing entries per spec rules. Two OpenAI models (text-embedding-3-large,
text-embedding-3-small) and Alibaba-NLP/gte-multilingual-base received the
long-context tag (their max_seq_length >= 4096 was caught by the taxonomy test).
No existing tags were removed.

**Deviations from spec**: None.
