# TASK-861: Surface `contextual_header` in `SearchResult.metadata`

**Feature**: FEAT-127 — Metadata-Driven Contextual Embedding Headers
**Spec**: `sdd/specs/contextual-embedding-headers.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-857
**Assigned-to**: unassigned

---

## Context

Spec §8 Open Question 2 — answered "Yes" by Jesus Lara. At retrieval
time, callers should be able to see the `contextual_header` that was
embedded for each chunk so they can:

1. re-build the augmented text for debugging,
2. feed it into a reranker that wants the contextual signal,
3. display "this chunk came from <Title> § <Section>" in UI without
   round-tripping to the parent document.

The mechanism is cheap: `SearchResult.metadata` is already a `Dict[str, Any]`
(`parrot/stores/models.py:13`) and the row-level metadata column already
carries `contextual_header` (written by TASK-857). We just need to verify
the search paths in `PgVectorStore` propagate the JSON metadata field
into `SearchResult.metadata` rather than stripping or whitelisting keys.

---

## Scope

- Audit every place in `parrot/stores/postgres.py` where a `SearchResult`
  is constructed from a SQL row and confirm the `metadata=` argument is
  built from the full `cmetadata` JSON blob (not a hand-picked subset).
- If a path is found that strips/projects metadata keys, fix it so
  `contextual_header` (and any other custom keys) survive.
- Add an integration test that:
  1. inserts a doc with `contextual_embedding=True`,
  2. runs `similarity_search`,
  3. asserts `result.metadata["contextual_header"]` is present and
     matches the header that was embedded.

**NOT in scope**:

- Other stores (Milvus, Faiss, Arango). Their metadata propagation is
  symmetric in current code; if regressions surface they get follow-up
  tickets.
- A new `SearchResult.contextual_header` top-level field — explicitly
  rejected (see spec §6 "Does NOT Exist"). The header lives inside
  `metadata`.
- Modifying retrieval rankers / rerankers to USE the header — that's a
  separate research task.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/stores/postgres.py` | MODIFY (if needed) | Patch any `SearchResult(...)` construction that drops keys. |
| `packages/ai-parrot/tests/integration/stores/test_contextual_pgvector.py` | MODIFY | Append a propagation test (file created in TASK-857). |

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-04-27.

### Verified Imports

```python
from parrot.stores.models import SearchResult, Document   # parrot/stores/models.py:7,21
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/stores/models.py:7
class SearchResult(BaseModel):
    id: str
    content: str
    metadata: Dict[str, Any] = Field(default_factory=dict)        # line 13
    score: float
    ensemble_score: float = None
    search_source: str = None
    similarity_rank: Optional[int] = None
    mmr_rank: Optional[int] = None
```

### Audit Targets

```bash
# Find every SearchResult construction in postgres.py:
grep -n "SearchResult(" packages/ai-parrot/src/parrot/stores/postgres.py
```

For each hit, verify:

- The `metadata=` kwarg is the full row's `cmetadata` JSON (typically
  `row.cmetadata` or `result.cmetadata` — depends on local naming).
- No projection like `metadata={k: v for k, v in cmetadata.items() if k in ALLOWED}`.
- No silent drop of keys via `metadata=cmetadata.get("public_meta", {})`.

If projection IS happening, surface the change in the completion note —
the precise fix depends on local code; treat it as a small targeted edit.

### Does NOT Exist

- ~~`SearchResult.contextual_header`~~ — top-level field. Header lives in
  `metadata['contextual_header']`.
- ~~A `SEARCH_RESULT_METADATA_WHITELIST` constant~~ — not in the codebase.
  If you see one introduced by an unrelated change, do not extend it
  silently; surface it.

---

## Implementation Notes

The expected outcome is "no change is needed" — the existing code passes
the full `cmetadata` blob through. This task exists to **verify** that
assumption with a test, not to invent a new feature. If verification
passes, the only artifact is the new test in
`tests/integration/stores/test_contextual_pgvector.py`.

If verification fails, the fix is one or two targeted edits in
`postgres.py` to stop dropping keys.

### Test to Add

```python
# Append to packages/ai-parrot/tests/integration/stores/test_contextual_pgvector.py
async def test_contextual_header_round_trips_to_search_result(store, docs_with_meta):
    """End-to-end: header written at insert is visible on the SearchResult."""
    from parrot.stores.utils.contextual import DEFAULT_TEMPLATE
    from parrot.stores.models import SearchResult

    store.contextual_embedding = True
    store.contextual_template = DEFAULT_TEMPLATE

    # Stand-in: simulate what similarity_search returns by exercising the
    # row-to-SearchResult conversion the production path uses. Implementer:
    # locate the helper (typically a method like _row_to_search_result or
    # an inline construction inside similarity_search) and invoke it on a
    # synthetic row whose cmetadata contains 'contextual_header'.
    fake_row = MagicMock()
    fake_row.cmetadata = {"contextual_header": "Title: Handbook", "other": "x"}
    fake_row.document = "Body."
    # ... build SearchResult per the production path; assert below.
    result: SearchResult = ...
    assert result.metadata["contextual_header"] == "Title: Handbook"
    assert result.metadata["other"] == "x"
```

The implementer is expected to read the actual `similarity_search` body in
`postgres.py` and adapt the test to the real row→SearchResult path
(stubbing the surrounding I/O is acceptable; the goal is to assert the
metadata kwarg behaviour, not to spin up Postgres).

---

## Acceptance Criteria

- [ ] Every `SearchResult(...)` construction in `postgres.py` passes the
      full row metadata through (no key projection).
- [ ] New test asserts `contextual_header` is present in `result.metadata`
      after a round-trip insert + search (mocked I/O is fine).
- [ ] `pytest packages/ai-parrot/tests/integration/stores/test_contextual_pgvector.py -v` passes.

---

## Agent Instructions

1. Read the spec §8 open question 2 (the "Yes" answer is the trigger).
2. Verify TASK-857 is completed.
3. Update status to in-progress.
4. Audit `postgres.py` `SearchResult(...)` constructions; patch any that
   drop keys.
5. Add the test.
6. Move to completed; update index.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none | describe if any
