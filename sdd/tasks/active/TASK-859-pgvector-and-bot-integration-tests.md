# TASK-859: Integration tests — pgvector end-to-end + bot composition

**Feature**: FEAT-128 — Parent-Child Retrieval with Composable Parent Searcher
**Spec**: `sdd/specs/parent-child-retrieval.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-857, TASK-858
**Assigned-to**: unassigned

---

## Context

Module 5 of FEAT-128. Validate the full pipeline against a real (or
near-real) pgvector store: ingestion → marker filtering →
similarity_search → reranker (optional, mocked) → parent expansion →
LLM context. Catches integration bugs that unit tests miss, such as:

- The default similarity_search filter not being pushed into SQL
  (causing parents to leak into the candidate set).
- Parent fetching returning rows in the wrong shape.
- The 3-level path producing parent_chunks that don't match the
  searcher's filter predicate.
- Composition order with a (mocked) reranker.

Reference: spec §4 (Integration Tests table), §7 Risk #4 & #5.

---

## Scope

- Add an integration test module exercising the 2-level end-to-end
  path: small docs → ingestion → query → expand_to_parent → assert
  full-document Documents are returned.
- Add an integration test for the 3-level end-to-end path: large doc
  → ingestion → query for content in a specific parent_chunk → assert
  ONLY that parent_chunk is returned (not the whole doc, not other
  parent_chunks).
- Add an integration test composing a mocked reranker with parent
  expansion: verify reranker runs first, expansion runs on reranked
  top-K, dedupe is correct.
- Add an end-to-end `BaseBot.ask()` test against a mock LLM verifying
  the answer was synthesised from a parent-sized context (longer than
  any individual chunk).
- Reuse existing pgvector test fixtures (`pg_store`,
  `pg_test_collection` or whatever is already in
  `packages/ai-parrot/tests/integration/`). If none exist, gate the new
  tests behind a `pytest.mark.integration` marker and document the
  required env vars in the test module docstring.

**NOT in scope**:
- New unit tests (those live with their respective tasks).
- Performance benchmark enforcement (spec leaves the 50 ms P95 budget
  unenforced; just record observed numbers in a print/log).
- Tests for non-postgres stores.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/integration/stores/__init__.py` | CREATE if missing | Test package marker. |
| `packages/ai-parrot/tests/integration/stores/test_parent_child_pgvector.py` | CREATE | 2-level + 3-level end-to-end. |
| `packages/ai-parrot/tests/integration/bots/__init__.py` | CREATE if missing | Test package marker. |
| `packages/ai-parrot/tests/integration/bots/test_basebot_parent_expansion.py` | CREATE | `BaseBot.ask()` end-to-end + reranker composition. |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: Verified against the codebase on 2026-04-27.

### Verified Imports

```python
from parrot.bots.abstract import AbstractBot                       # parrot/bots/abstract.py:144
from parrot.stores.parents import (                                 # CREATED by TASK-855
    AbstractParentSearcher, InTableParentSearcher,
)
from parrot.stores.utils.chunking import LateChunkingProcessor      # parrot/stores/utils/chunking.py:20
from parrot.stores.models import Document                            # parrot/stores/models.py:21
```

### Existing Signatures to Use

```python
# Concrete BaseBot subclass to instantiate in tests — pick the simplest
# one available (e.g., the test fixtures used by other integration tests).
# Inspect packages/ai-parrot/tests/integration/ for the existing pattern.

# Reranker mock interface — IF FEAT-126 has shipped, use its real type.
# Otherwise mock as a callable: list[child] -> list[(child, score)].
```

```python
# Test-fixture conventions in this repo:
# - Async tests use `pytest-asyncio` (existing dep)
# - pgvector fixtures gated by env vars (look for existing
#   `PG_VECTOR_DSN` / `PG_TEST_DSN` in conftest.py)
```

### Does NOT Exist

- ~~A general `parent_child` test fixture~~ — write yours.
- ~~`BaseBot.parent_searcher` set automatically from collection~~ —
  must be injected explicitly in tests.

---

## Implementation Notes

### Pattern to Follow — env-gated integration tests

Look for an existing `conftest.py` in `packages/ai-parrot/tests/integration/`
or its parents to find the established gating pattern. If a marker
like `pytest.mark.integration` or an env-var skip exists, use it.

If no precedent exists, gate as:

```python
import os, pytest
pytestmark = pytest.mark.skipif(
    not os.getenv("PG_VECTOR_DSN"),
    reason="Requires PG_VECTOR_DSN env var pointing to a test DB.",
)
```

Document this in the module docstring.

### 2-level end-to-end test

```python
async def test_pgvector_end_to_end_2level(pg_store, in_memory_parent_searcher):
    """Small doc (< 16k tokens) → ingestion uses 2-level path
    (doc is its own parent) → query → expand_to_parent → full doc returned."""
    docs = [_make_small_doc(i) for i in range(5)]
    await pg_store.from_documents(docs)

    bot = _make_test_bot(
        store=pg_store,
        parent_searcher=in_memory_parent_searcher,
        expand_to_parent=True,
    )
    ctx, meta = await bot.get_vector_context("question matching doc 2")
    # Assert: ctx contains the FULL doc-2 content, not a chunk
    assert _full_text_of(docs[2]) in ctx
```

### 3-level end-to-end test

```python
async def test_pgvector_end_to_end_3level(pg_store, in_memory_parent_searcher):
    """Large doc (~24k tokens) → ingestion uses 3-level path → query for
    content in middle parent_chunk → ONLY that parent_chunk returned."""
    big_doc = _make_doc_with_distinct_sections(
        sections=[
            ("intro",  "ALPHA marker text " * 1000),
            ("middle", "BETA marker text "  * 1000),
            ("end",    "GAMMA marker text " * 1000),
        ]
    )
    await pg_store.from_documents([big_doc])

    bot = _make_test_bot(
        store=pg_store,
        parent_searcher=in_memory_parent_searcher,
        expand_to_parent=True,
    )
    ctx, _ = await bot.get_vector_context("BETA marker")
    # Assert: ctx contains BETA, does NOT contain ALPHA or GAMMA
    assert "BETA" in ctx
    assert "ALPHA" not in ctx
    assert "GAMMA" not in ctx
    # Length should be roughly one parent_chunk worth, not the full doc
    assert len(ctx) < len(big_doc.page_content) * 0.6
```

### Reranker composition test

If FEAT-126 has shipped, compose with the real reranker. Otherwise
inject a mocked reranker callable that reverses the candidate order.
Assert that `parent_searcher.fetch` is called with parent IDs in the
reranker's output order, NOT the similarity_search original order.

```python
async def test_pgvector_compose_with_reranker(pg_store, in_memory_parent_searcher):
    docs = [_make_small_doc(i) for i in range(5)]
    await pg_store.from_documents(docs)

    reverse_reranker = _make_mock_reranker(reverse=True)   # see notes
    bot = _make_test_bot(
        store=pg_store,
        parent_searcher=in_memory_parent_searcher,
        expand_to_parent=True,
        reranker=reverse_reranker,
    )
    spy = _spy_on(in_memory_parent_searcher, "fetch")
    await bot.get_vector_context("anything")
    fetched_ids = spy.call_args[0][0]
    # The reverse_reranker put doc-0 last; if expansion happened BEFORE
    # rerank, fetched_ids would lead with doc-0's parent. Assert the
    # opposite — last-rank parent appears first.
    assert fetched_ids[0].endswith("0") is False   # adjust per fixture
```

### `BaseBot.ask()` mock-LLM end-to-end

```python
async def test_basebot_ask_with_parent_expansion(pg_store, in_memory_parent_searcher):
    """Full ask() path with a mock LLM. Verify the LLM received a
    parent-sized context (longer than any individual chunk)."""
    ...
    captured_prompt = mock_llm.last_prompt
    assert len(captured_prompt) > MAX_CHUNK_LENGTH
```

### Key Constraints

- Each integration test MUST be hermetic: ingest its own docs, query,
  assert, drop the collection. Use a unique collection name per test
  (e.g., `f"feat128_{test_name}_{uuid4().hex[:6]}"`).
- Async throughout. Use the existing `pytest-asyncio` setup.
- Do NOT enforce performance budgets in CI — only record observations
  via `caplog` or `print` for benchmark visibility.
- Tests MUST work with the mocked reranker even before FEAT-126 ships.

### References in Codebase

- Existing pgvector tests under `packages/ai-parrot/tests/integration/`
  — mirror their fixture and gating patterns.
- `parrot/stores/utils/chunking.py:42` — `process_document_late_chunking`
  internals, useful when constructing fixture documents that span
  predictable token counts.

---

## Acceptance Criteria

- [ ] `test_pgvector_end_to_end_2level` passes: small doc ingested →
      query → full doc returned in context.
- [ ] `test_pgvector_end_to_end_3level` passes: large doc → only the
      relevant parent_chunk returned (not the full doc).
- [ ] `test_pgvector_compose_with_reranker` passes: parent expansion
      runs on reranked top-K (mocked reranker).
- [ ] `test_basebot_ask_with_parent_expansion` passes: mock LLM receives
      a parent-sized prompt.
- [ ] All integration tests are hermetic (own collection, own
      cleanup).
- [ ] All tests pass: `pytest packages/ai-parrot/tests/integration/stores/test_parent_child_pgvector.py packages/ai-parrot/tests/integration/bots/test_basebot_parent_expansion.py -v`
- [ ] Tests skip gracefully (with a clear reason) when the integration
      env var is not set.

---

## Test Specification

> See **Implementation Notes** above for full sketches. The four tests
> listed in the Acceptance Criteria are the minimum scope.

---

## Agent Instructions

When you pick up this task:

1. **Confirm dependencies**: TASK-857 AND TASK-858 must be in
   `sdd/tasks/completed/`.
2. **Read the spec** — §4 lists each integration test verbatim.
3. **Find existing pgvector fixtures** in
   `packages/ai-parrot/tests/integration/` and reuse them. If none
   exist, write your own and gate behind an env-var check.
4. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`.
5. **Implement** the four tests. Make sure cleanup runs even on failure
   (use fixture teardown).
6. **Run the suite** end-to-end. Iterate until green.
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** — include observed P95 latency for
   the 2-level path with 10 unique parents, even though the budget is
   not enforced.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Observed performance** (informational, not enforced):

**Deviations from spec**:
