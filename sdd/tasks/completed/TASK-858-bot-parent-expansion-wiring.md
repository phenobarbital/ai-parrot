# TASK-858: Bot-side wiring (`expand_to_parent` + `parent_searcher`)

**Feature**: FEAT-128 — Parent-Child Retrieval with Composable Parent Searcher
**Spec**: `sdd/specs/parent-child-retrieval.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-855, TASK-856
**Assigned-to**: unassigned

---

## Context

Module 4 of FEAT-128 — the **core** of the feature. Wire the bot to use
the `ParentSearcher` (TASK-855) after retrieval, deduping by
`parent_document_id` and substituting parents for children in the LLM
context. Also expose `expand_to_parent` as a per-call kwarg and through
the DB-driven config (`_from_db` path) per spec §8.

Composes with FEAT-126 (cross-encoder reranker): when configured,
reranking runs on **children** first, then parent expansion runs on the
top-K reranked children. Order matters — do not invert.

Reference: spec §2 (Retrieval-side expansion), §3 (Module 4),
§7 (Risk #1, Risk #4 — composition with FEAT-126), §8 (DB-driven
exposure of `expand_to_parent`).

---

## Scope

- Add to `AbstractBot.__init__` (`parrot/bots/abstract.py:144`,
  attributes near line 387):
  - `self.parent_searcher: Optional[AbstractParentSearcher] = kwargs.get("parent_searcher", None)`
  - `self.expand_to_parent: bool = kwargs.get("expand_to_parent", False)`
- Add an `expand_to_parent: Optional[bool] = None` per-call kwarg to
  both `get_vector_context` (line 1587) and `_build_vector_context`
  (line 2239). Resolution order: explicit kwarg → `self.expand_to_parent`
  → `False`.
- Implement the post-retrieval expansion routine in a private helper
  on `AbstractBot` (e.g., `_expand_to_parents(results) -> list`):
  1. Walk `results` in their existing order (already ranked / reranked).
  2. Group by `metadata['parent_document_id']`. Track `(parent_id,
     best_score, first_index, fallback_child)` per group.
  3. Drop entries without a `parent_document_id` from the grouping but
     keep them in the output stream as-is (legacy chunks fall through).
  4. Call `await self.parent_searcher.fetch(unique_parent_ids)` with
     order preserved (Python 3.7+ dict ordering = insertion order).
  5. For each group: if parent fetched, replace child with parent
     Document carrying the child's score; if not fetched, keep the
     fallback child + DEBUG log.
  6. Return the new list, ordered by best-child-score across groups.
- When `expand_to_parent=True` but `self.parent_searcher is None`:
  emit a `WARNING` log **once** (use a flag to avoid spam) and return
  the original results unmodified.
- Update `parrot/bots/chatbot.py:_from_db` (line 174-onward) to read
  `expand_to_parent` from the DB-stored bot config (e.g., via
  `self.expand_to_parent = self._from_db(bot, 'expand_to_parent',
  default=self.expand_to_parent)`). Add it next to other context-search
  knobs near line 236. Constructor injection of `parent_searcher`
  remains the only path (registries / import-string lookup are deferred
  per §8 final answer).
- Write unit tests covering: dedupe, ordering by best score, per-call
  override, missing-parent fall-through, missing-searcher warning,
  legacy-chunks-without-parent-id pass-through, composition with a
  mocked reranker.

**NOT in scope**:
- The `ParentSearcher` package itself (TASK-855).
- Default-filter changes to `similarity_search` (TASK-856).
- The 3-level ingestion path (TASK-857).
- Integration tests against a real pgvector (TASK-859).
- Documentation (TASK-860).
- A `ParentSearcher` registry / import-string resolution (deferred per
  spec §8).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/abstract.py` | MODIFY | New attributes in `__init__` near line 387; per-call kwarg in `get_vector_context` (line 1587) and `_build_vector_context` (line 2239); private `_expand_to_parents` helper. |
| `packages/ai-parrot/src/parrot/bots/chatbot.py` | MODIFY | Read `expand_to_parent` from DB config in `_from_db`-driven init path (around line 236). |
| `packages/ai-parrot/tests/bots/test_parent_expansion.py` | CREATE | Unit tests covering all behaviour above. |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: Verified against the codebase on 2026-04-27.

### Verified Imports

```python
from typing import Optional, Dict, Any, List
from parrot.bots.abstract import AbstractBot                        # parrot/bots/abstract.py:144
from parrot.stores.parents import AbstractParentSearcher            # CREATED by TASK-855
from parrot.stores.models import Document                            # parrot/stores/models.py:21
```

### Existing Signatures to Use

```python
# parrot/bots/abstract.py
class AbstractBot(VectorInterface, ...):                            # line 144

    def __init__(self, ...):                                         # line 188
        ...
        self.context_search_limit: int = kwargs.get('context_search_limit', 10)   # line 387
        self.context_score_threshold: float = kwargs.get(
            'context_score_threshold', 0.7)                          # line 388
        # ADD here:
        # self.parent_searcher: Optional[AbstractParentSearcher] = kwargs.get(
        #     'parent_searcher', None)
        # self.expand_to_parent: bool = kwargs.get('expand_to_parent', False)

    async def get_vector_context(...) -> Tuple[str, Dict[str, Any]]: # line 1587
        ...
        limit = limit or self.context_search_limit                   # line 1615
        score_threshold = score_threshold or self.context_score_threshold  # 1616
        ...

    async def _build_vector_context(...) -> Tuple[str, Dict[str, Any]]:    # 2239
        ...
```

```python
# parrot/bots/chatbot.py
def _from_db(self, botobj, key, default=None) -> Any:                # line 174
    ...

# Existing pattern in the _from_db-consuming init block (around 236):
self.context_search_limit = getattr(self, 'context_search_limit', 10)  # line 236
# Pattern for _from_db assignments — see lines 327-353 for many examples:
self.pre_instructions = self._from_db(bot, 'pre_instructions', default=...)  # 327
```

### Does NOT Exist

- ~~`AbstractBot.parent_searcher` / `AbstractBot.expand_to_parent`~~ —
  CREATED by this task.
- ~~`AbstractBot._expand_to_parents`~~ — CREATED by this task as a
  private helper.
- ~~A `ParentSearcher` registry~~ — deferred per spec §8.
- ~~`parent_searcher` field in DB-driven config~~ — explicitly
  out-of-scope. Only `expand_to_parent` is exposed through DB config.
- ~~`SearchResult.parent_document` attribute~~ — parents are linked
  via `metadata['parent_document_id']` only. Use `result.metadata.get(
  'parent_document_id')`.

---

## Implementation Notes

### Resolution order for `expand_to_parent`

```python
def _resolve_expand_flag(self, override: Optional[bool]) -> bool:
    if override is not None:
        return override
    return self.expand_to_parent
```

Apply this at the top of both `get_vector_context` and
`_build_vector_context`.

### Expansion algorithm (preserves order, deduplicates, falls through)

```python
async def _expand_to_parents(
    self,
    results: list,                # list[SearchResult|Document|RerankedDocument]
) -> list:
    """Replace children with their parents, dedupe by parent_document_id,
    preserve best-score-first ordering. Children with no parent_document_id
    pass through unchanged. Children whose parent cannot be fetched also
    pass through with a DEBUG log."""
    if not results:
        return results
    if self.parent_searcher is None:
        # WARNING once-per-bot
        self._warn_no_parent_searcher_once()
        return results

    # Phase 1 — group, preserve insertion order
    groups: Dict[str, dict] = {}        # parent_id -> {first_index, fallback, best_score}
    pass_through: list = []             # legacy chunks without parent_document_id
    for idx, r in enumerate(results):
        meta = self._meta_of(r)         # works for Document, SearchResult, RerankedDocument
        parent_id = meta.get('parent_document_id')
        if not parent_id:
            pass_through.append((idx, r))
            self.logger.debug(
                "Result without parent_document_id falls through (idx=%d)", idx)
            continue
        score = self._score_of(r)
        if parent_id not in groups:
            groups[parent_id] = {
                'first_index': idx,
                'fallback': r,
                'best_score': score,
            }
        else:
            if score > groups[parent_id]['best_score']:
                groups[parent_id]['best_score'] = score

    # Phase 2 — fetch parents in one round trip
    parent_ids = list(groups.keys())
    fetched = await self.parent_searcher.fetch(parent_ids)

    # Phase 3 — assemble output preserving original order of first-occurrence
    out: list = []
    # Build a reverse map by first_index for ordering
    indexed_groups = sorted(
        groups.items(), key=lambda kv: kv[1]['first_index'])
    legacy_iter = iter(sorted(pass_through, key=lambda t: t[0]))
    legacy_next = next(legacy_iter, None)
    for parent_id, info in indexed_groups:
        # Emit any legacy items that came before this group's first index
        while legacy_next and legacy_next[0] < info['first_index']:
            out.append(legacy_next[1])
            legacy_next = next(legacy_iter, None)
        if parent_id in fetched:
            out.append(self._wrap_parent(fetched[parent_id], info['best_score']))
        else:
            self.logger.debug(
                "Parent %s not fetched; falling back to child", parent_id)
            out.append(info['fallback'])
    # Any remaining legacy entries
    while legacy_next:
        out.append(legacy_next[1])
        legacy_next = next(legacy_iter, None)
    return out
```

`_meta_of`, `_score_of`, `_wrap_parent` are tiny helpers that paper over
the type differences between raw `Document`, `SearchResult`, and the
FEAT-126 `RerankedDocument` (when present). Inspect what
`_build_vector_context` already iterates over and adapt accordingly. Do
NOT add a hard import on FEAT-126 types — duck-type via attribute
checks.

### Composition with FEAT-126 reranker — ORDER MATTERS

In `_build_vector_context`, the call sequence is:

1. `similarity_search` → child candidates.
2. (If reranker configured) reranker re-ranks the children, truncates
   to top-K.
3. (If `expand_to_parent` resolved True) **call `_expand_to_parents` on
   the reranked top-K** — NOT before reranking.

The reranker decides *which* children matter; expansion decides
*which parents to fetch* based on those reranked winners. Inverting the
order would expand to parents first, then rerank parents, which defeats
the precision benefit of child-level scoring (spec §7 Risk #4).

If FEAT-126 has not yet shipped at the time this task is implemented,
just slot the expansion step at the end of the pipeline — the future
reranker will integrate cleanly because `_expand_to_parents` operates
on whatever list it receives.

### One-time WARNING log

```python
def _warn_no_parent_searcher_once(self):
    if not getattr(self, '_warned_no_parent_searcher', False):
        self.logger.warning(
            "expand_to_parent=True but no parent_searcher configured; "
            "returning child results unchanged."
        )
        self._warned_no_parent_searcher = True
```

### `_from_db` exposure (chatbot.py)

Add this near line 236 (next to `context_search_limit`):

```python
self.expand_to_parent = self._from_db(
    bot, 'expand_to_parent', default=getattr(self, 'expand_to_parent', False)
)
```

The `parent_searcher` itself is NOT read from DB in v1. Constructor
injection only.

### Key Constraints

- Async throughout.
- Do NOT mutate the input `results` list — build a new one.
- Preserve type identity where possible: if a `Document` was passed in,
  emit a `Document` for the parent; if a `SearchResult` was passed in,
  emit a `SearchResult` (use the same wrapper class). Inspect what
  `_build_vector_context` already produces.
- Do NOT call `parent_searcher.fetch([])` — guard with
  `if parent_ids: ...`.
- Per-call override `expand_to_parent=False` MUST short-circuit BEFORE
  any parent_searcher access (cheap path for ad-hoc precision queries).

### References in Codebase

- `parrot/bots/abstract.py:1587` — `get_vector_context` body. Insert
  expansion at the appropriate point.
- `parrot/bots/abstract.py:2239` — `_build_vector_context` body. The
  primary expansion site.
- `parrot/bots/chatbot.py:236` — pattern for reading
  `context_search_limit` from DB. Mirror it for `expand_to_parent`.

---

## Acceptance Criteria

- [ ] `AbstractBot(parent_searcher=..., expand_to_parent=True)` stores
      both as attributes; defaults are `None` and `False`.
- [ ] `await bot.get_vector_context(question, expand_to_parent=False)`
      short-circuits expansion even when bot default is True.
- [ ] `_build_vector_context` returns parents (deduped, ordered by best
      child score) when `expand_to_parent` resolves True.
- [ ] Children without `parent_document_id` pass through verbatim
      alongside expanded parents.
- [ ] Children whose parent cannot be fetched fall back to the child
      itself with a single DEBUG log per parent.
- [ ] `expand_to_parent=True` with `parent_searcher=None` logs a single
      WARNING and returns children unchanged.
- [ ] When a mocked reranker is configured, `_expand_to_parents` runs
      AFTER reranking, not before. Verified by ordering test.
- [ ] DB-driven config: `expand_to_parent` from the bot row is honoured
      after `_from_db` initialisation.
- [ ] `bot.ask()` / `bot.conversation()` produce identical output to
      pre-feature when `expand_to_parent=False` (regression snapshot).
- [ ] All unit tests pass: `pytest packages/ai-parrot/tests/bots/test_parent_expansion.py -v`
- [ ] No linting errors on modified files.

---

## Test Specification

```python
# packages/ai-parrot/tests/bots/test_parent_expansion.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from parrot.bots.abstract import AbstractBot
from parrot.stores.parents import AbstractParentSearcher
from parrot.stores.models import Document


@pytest.fixture
def fake_searcher():
    s = MagicMock(spec=AbstractParentSearcher)
    s.fetch = AsyncMock()
    return s


@pytest.fixture
def bot(fake_searcher):
    # Subclass AbstractBot with the minimum to instantiate.
    ...


class TestExpandToParents:
    async def test_default_off_returns_children_unchanged(self, bot, fake_searcher):
        results = [_child("c1", parent="p1", score=0.9)]
        out = await bot._expand_to_parents(results)  # expand_to_parent off
        assert out == results
        fake_searcher.fetch.assert_not_awaited()

    async def test_dedupe_by_parent_id(self, bot_with_expand, fake_searcher):
        fake_searcher.fetch.return_value = {
            "p1": Document(page_content="P1", metadata={"document_id": "p1"}),
            "p2": Document(page_content="P2", metadata={"document_id": "p2"}),
        }
        results = [
            _child("c1", parent="p1", score=0.95),
            _child("c2", parent="p1", score=0.80),
            _child("c3", parent="p2", score=0.70),
            _child("c4", parent="p1", score=0.60),
            _child("c5", parent="p2", score=0.50),
        ]
        out = await bot_with_expand._expand_to_parents(results)
        ids = [d.metadata['document_id'] for d in out]
        assert ids == ['p1', 'p2']           # ordered by best child score

    async def test_per_call_override_off(self, bot_with_expand):
        ctx = await bot_with_expand.get_vector_context(
            "q", expand_to_parent=False)
        # parent_searcher should NOT have been called
        assert bot_with_expand.parent_searcher.fetch.await_count == 0

    async def test_missing_parent_falls_through_to_child(self, bot_with_expand, fake_searcher):
        fake_searcher.fetch.return_value = {}      # nothing found
        results = [_child("c1", parent="p1", score=0.9)]
        out = await bot_with_expand._expand_to_parents(results)
        assert out[0].metadata.get('document_id') == 'c1'  # child preserved

    async def test_no_searcher_warns_once(self, bot_no_searcher, caplog):
        bot_no_searcher.expand_to_parent = True
        results = [_child("c1", parent="p1", score=0.9)] * 3
        await bot_no_searcher._expand_to_parents(results)
        await bot_no_searcher._expand_to_parents(results)
        warnings = [r for r in caplog.records if r.levelname == "WARNING"]
        assert len(warnings) == 1

    async def test_legacy_chunks_without_parent_id_pass_through(
        self, bot_with_expand, fake_searcher
    ):
        fake_searcher.fetch.return_value = {
            "p1": Document(page_content="P1", metadata={"document_id": "p1"}),
        }
        results = [
            _child("c1", parent="p1", score=0.9),
            _child("legacy", parent=None, score=0.8),  # no parent_document_id
        ]
        out = await bot_with_expand._expand_to_parents(results)
        ids = [d.metadata.get('document_id') for d in out]
        assert 'p1' in ids and 'legacy' in ids

    async def test_compose_with_reranker_runs_after(
        self, bot_with_reranker_and_expand, fake_searcher
    ):
        """Reranker reorders children; parent expansion runs on reranker output."""
        # Arrange a reranker that reverses input order
        # Act: call _build_vector_context
        # Assert: parent_searcher.fetch was called with parent_ids in the
        # reranker's order, NOT the similarity_search original order
        ...

    async def test_db_driven_expand_to_parent_flag(self, bot_from_db_with_flag_true):
        """A bot constructed via _from_db with expand_to_parent=True
        in its DB row honours the flag."""
        assert bot_from_db_with_flag_true.expand_to_parent is True
```

(`_child(...)` and the bot fixtures are helpers the implementing agent
should write to fit whatever concrete `AbstractBot` subclass exists in
test fixtures. Keep them minimal.)

---

## Agent Instructions

When you pick up this task:

1. **Confirm dependencies**: TASK-855 AND TASK-856 must be in
   `sdd/tasks/completed/`.
2. **Read the spec** — focus on §2 (Architectural Design),
   §3 (Module 4), §7 Risks #1 & #4, §8 (DB-driven config answer).
3. **Verify the Codebase Contract** — line numbers in `abstract.py` and
   `chatbot.py` may have drifted. Re-locate by symbol.
4. **Decide ahead of time** how `_expand_to_parents` interacts with
   whatever type `_build_vector_context` currently iterates over. Add
   the duck-typed helpers (`_meta_of`, `_score_of`, `_wrap_parent`).
5. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`.
6. **Implement** in this order: attributes → `_expand_to_parents`
   helper → kwarg + call site in `_build_vector_context` → kwarg +
   call site in `get_vector_context` → `_from_db` exposure → tests.
7. **Run the regression test FIRST** — `expand_to_parent=False` MUST
   produce identical output to the pre-feature behaviour.
8. **Verify** the FEAT-126 composition test — even if FEAT-126 has not
   yet shipped, mock a reranker callable to validate ordering.
9. **Move this file** to `sdd/tasks/completed/`.
10. **Update index** → `"done"`.
11. **Fill in the Completion Note**.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**:
