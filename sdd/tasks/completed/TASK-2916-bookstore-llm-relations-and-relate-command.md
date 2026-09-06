# TASK-2916: Bookstore — LLM conceptual relations, judgement log, `bookstore relate`

**Feature**: FEAT-533 — Bookstore Conceptual Relations
**Spec**: `sdd/specs/wikitoolkit-bookstore-conceptual-relations.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2914, TASK-2915
**Assigned-to**: unassigned

---

## Context

Spec §2 Overview step 3 (Stage 2), §3 Module 2 (second half), goal G3.
The non-deterministic layer: one structured LLM prompt per book over a
pre-filtered candidate set, a 0.5 confidence floor, and a judgement log
so a second `relate` never re-asks. This task also lands the batch
orchestrator (`relate_books`, Stages 1–2; Stage 3 is wired by
TASK-2917 behind the `communities` flag) and the CLI entry points.

---

## Scope

- `relations.py`:
  - `_RELATION_PROMPT` (librarian persona; the source book's brief +
    up to 8 candidate briefs with `book_id`; asks for `judgements[]`
    with `rel ∈ {influenced_by, responds_to, parallels, contrasts_with,
    none}`, `confidence` 0–1, one-sentence `rationale`; instruct that
    `influenced_by`/`responds_to` are directed **from the source book**).
  - `candidate_pairs(card, cards, det_relations, fts_hits, judged:
    set[str], cap=8) -> list[BookCard]` — union of Stage-1 neighbours
    and FTS hits, minus self, minus `judged`, stable order (det
    neighbours by weight desc, then FTS order), capped.
  - `async judge_relations(adapter, card, candidates, *, model_name="")
    -> RelationDraft` — `adapter.ask_structured(prompt, RelationDraft)`,
    dict → `model_validate`; drop judgements whose `dst_book_id` is not
    a candidate (hallucinated ids).
  - `llm_relations_from_draft(card, draft, *, now, floor=0.5) ->
    list[BookRelation]` — `origin="llm"`, `confidence`, `rationale`,
    weight `REL_WEIGHTS[rel]`, `rel != "none"`, `confidence >= floor`.
- `Bookstore.relate_books(book_ids=None, *, use_llm=True,
  communities=True, communities_only=False, force=False,
  resolution=1.0) -> RelateSummary`:
  - target = given ids (validated via `resolve_book`) or all visible.
  - Stage 1: `deterministic_relations(all_visible_cards)` filtered to
    edges touching a target → `_write_deterministic`.
  - Stage 2 (when `use_llm and self.has_llm and not communities_only`):
    per target: `judged = judged_pairs(src)` unless `force`;
    `fts = catalog_search(card.summary or " ".join(card.topics), top_k=8)`;
    candidates; if empty → skip; `judge_relations`; `record_judgements`
    (every candidate judged, incl. `none`; model name from
    `getattr(self.adapter, "model", "")`); delete this src's previous
    `origin="llm"` edges for judged pairs only, then `upsert_relations`.
    Per-book `try/except` → `summary.failed[book_id] = str(exc)`.
  - Stage 3: **hook only** — `if communities: await self._relate_stage3(
    resolution)`; implement `_relate_stage3` as a no-op stub returning
    `None` with a `TODO(TASK-2917)` comment and a summary note
    `"communities: not available"`.
  - `RelateSummary` fields (from TASK-2913): `targets`, `deterministic_edges`,
    `llm_prompts`, `llm_edges`, `skipped_llm_reason`, `failed: dict`,
    `communities: Optional[int]`, `notes: list[str]`.
- `add_book(..., relate: bool = False)` → after `catalog.upsert(card)`,
  `await self.relate_books([slug], communities=False)` when `relate`.
- `add_folder(..., relate: bool = False)` → per file `relate=True`
  (Stage 1–2 only), then one `relate_books(None, communities_only=True)`
  at the end when any file succeeded (harmless no-op until TASK-2917).
- CLI: `bookstore relate [BOOK_ID...] [--all] [--no-llm]
  [--communities-only] [--force] [--resolution F] [--llm SPEC]` (require
  `--all` or ≥1 id; prints the summary); `add --relate`,
  `add-folder --relate`.
- `conftest.py::make_adapter._structured`: `RelationDraft` branch
  returning one `parallels` (0.7) and one `none` (0.9) judgement using
  ids passed in the prompt (parse `book_id=` tokens, or accept a
  module-level override hook — keep it simple and deterministic).
- Tests per the Test Specification.

**NOT in scope**: community detection/labelling (TASK-2917); tools;
export.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/bookstore/relations.py` | MODIFY | prompt, candidates, judge, draft→relations |
| `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py` | MODIFY | `relate_books`, `_relate_stage3` stub, `add_book(relate=)`, `add_folder(relate=)` |
| `packages/ai-parrot/src/parrot/knowledge/bookstore/cli.py` | MODIFY | `relate`; `--relate` flags |
| `packages/ai-parrot/tests/knowledge/bookstore/conftest.py` | MODIFY | `RelationDraft` branch |
| `packages/ai-parrot/tests/knowledge/bookstore/test_relations.py` | MODIFY | Stage 2 + orchestrator tests |
| `packages/ai-parrot/tests/knowledge/bookstore/test_cli.py` | MODIFY | `relate` command |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.bookstore.models import BookCard, BookRelation, RelationDraft, RelationJudgement, RelateSummary, REL_WEIGHTS   # TASK-2913
from parrot.knowledge.bookstore.relations import deterministic_relations   # TASK-2915
from parrot.knowledge.bookstore.catalog import CatalogStore                 # catalog.py:85 (+ TASK-2913 CRUD)
from parrot.knowledge.bookstore.library import Bookstore, BookstoreError    # library.py:88, 55
from parrot.knowledge.pageindex.llm_adapter import PageIndexLLMAdapter      # ask_structured at llm_adapter.py:99
```

### Existing Signatures to Use
```python
# bookstore/library.py
class Bookstore:
    adapter: Optional[Any]; @property has_llm -> bool                    # line 125
    def catalog_search(self, query: str, top_k: int = 8) -> list[BookCard]   # line 188 — merged_search
    async def add_book(self, file_path, scope="project", title=None, authors=None, topics=None, force=False) -> tuple[BookCard, str]   # line 343 — ends with catalog.upsert(card); return card, status
    async def add_folder(self, folder, scope="project", recursive=False, dry_run=False, ...)   # line 617 — sequential loop, per-file try/except, summary dict with added/updated/skipped/failed
    async def _draft_card(...)   # line ~420 — the try/except-degrade pattern to copy for Stage 2
    # from TASK-2915: _visible_ids(), _relations_store_for(book_id), _write_deterministic(relations), related_books(...)

# bookstore/carding.py
async def generate_card_fields(adapter, *, filename, doc_description, toc_digest, samples) -> CardDraft   # line 154 — the ask_structured + model_validate pattern

# bookstore/_llm.py / _NullAdapter (library.py:59)
# adapter.ask_structured(prompt, schema) — raises RuntimeError on _NullAdapter; guard with has_llm first
# adapter.model: Optional[str]  (both real PageIndexLLMAdapter and _NullAdapter expose it)

# bookstore/cli.py
@bookstore.command("add") def add(...)   # line 96-150 — options: --scope/--global?, --title, --author (multiple), --topic (multiple), --force, --no-llm, --llm; asyncio.run(store.add_book(...))
@bookstore.command("add-folder") def add_folder(...)   # line 151-240
def _open_bookstore(llm_spec=None, require_exists=False, scope_needed=None, use_llm=True)   # line 31

# tests/knowledge/bookstore/conftest.py
def make_adapter() -> MagicMock   # line 31 — extend `_structured(prompt, schema, **kwargs)` dispatch
```

### Does NOT Exist
- ~~`Bookstore.relate_books`, `_relate_stage3`, `add_book(relate=)`, `add_folder(relate=)`~~ — created here.
- ~~`candidate_pairs`, `judge_relations`, `llm_relations_from_draft`, `_RELATION_PROMPT`~~ — created here.
- ~~A per-pair LLM call~~ — forbidden by design; one prompt per source book.
- ~~Automatic relate inside `add` without `--relate`~~ — must never happen (G3).
- ~~`adapter.ask_structured(..., temperature=)` guarantees~~ — the real adapter accepts `temperature`, `_NullAdapter`/test mocks accept `**kwargs`; do not rely on extra kwargs beyond `(prompt, schema)`.

---

## Implementation Notes

### Pattern to Follow
```python
# library.py — Stage 2 per-book loop (mirror _draft_card's degrade discipline)
for card in targets:
    try:
        judged = set() if force else store.judged_pairs(card.book_id)
        cands = candidate_pairs(card, all_cards, det, self.catalog_search(q, top_k=8), judged)
        if not cands: continue
        draft = await judge_relations(self.adapter, card, cands)
        summary.llm_prompts += 1
        store.record_judgements(card.book_id, draft.judgements, model=getattr(self.adapter, "model", "") or "")
        rels = llm_relations_from_draft(card, draft, now=now)
        ...
    except Exception as exc:  # noqa: BLE001 — never abort the batch
        logger.warning("relate: LLM stage failed for %r: %s", card.book_id, exc)
        summary.failed[card.book_id] = str(exc)
```

### Key Constraints
- Judgement log key is `(src, dst)` directional (spec §7): judging A→B does not mark B→A judged.
- Replacing LLM edges: delete only `(src, dst)` pairs re-judged in this run, so edges judged earlier from the *other* direction survive.
- Candidate briefs in the prompt must include `book_id` verbatim; validate returned ids against the candidate set.
- `--no-llm` or no adapter → `summary.skipped_llm_reason` set, exit 0.
- `relate` must run `Stage 1` over **all visible cards** even when targeting one book (edges are pairwise), but write only edges touching the targets.

### References in Codebase
- `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py:420-445` — `_draft_card` degrade pattern
- `packages/ai-parrot/src/parrot/knowledge/bookstore/carding.py:21-42, 154-187` — prompt + structured call

---

## Acceptance Criteria

- [ ] `relate --all` on N books issues ≤ N relation prompts; second run without `--force` issues 0; `--force` re-asks
- [ ] Confidence < 0.5 or `rel="none"` → logged in `relation_judgements`, absent from `book_relations`
- [ ] Hallucinated `dst_book_id` in the draft is dropped
- [ ] Adapter exception on one book → that book in `failed`, its deterministic edges intact, batch continues
- [ ] No LLM → Stage 1 only, `skipped_llm_reason` set, exit 0
- [ ] `add --relate` relates only the new book; plain `add` makes zero relation prompts
- [ ] `pytest packages/ai-parrot/tests/knowledge/bookstore/ -q` green; `ruff check` clean

---

## Test Specification

```python
# test_relations.py (append)
def test_candidate_pairs_prefilter_and_cap(): ...
def test_llm_relations_from_draft_floor_and_none(): ...
def test_llm_relations_from_draft_drops_unknown_ids(): ...
async def test_judge_relations_one_prompt_per_book(store, ...): ...
async def test_relate_skips_judged_pairs_unless_force(store, ...): ...
async def test_relate_no_llm_runs_stage1_only(store_no_llm, ...): ...
async def test_relate_llm_failure_keeps_deterministic(store, ...): ...
async def test_add_relate_flag_scopes_to_new_book(store, ...): ...
async def test_add_without_relate_makes_no_relation_prompt(store, ...): ...
# test_cli.py
def test_relate_cli_requires_target(...): ...
def test_relate_cli_all_prints_summary(...): ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2914 and TASK-2915 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** before writing any code
4. **Update status** in `sdd/tasks/index/wikitoolkit-bookstore-conceptual-relations.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2916-bookstore-llm-relations-and-relate-command.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-09-06
**Notes**: `relations.py` Stage 2: `_RELATION_PROMPT`, `candidate_pairs`
(det-neighbours-by-weight then FTS, dedup, cap), `judge_relations`
(hallucinated `dst_book_id` filtering), `llm_relations_from_draft`
(0.5 floor, `rel != "none"`). `Bookstore.relate_books` orchestrates
Stage 1 (always, filtered to edges touching targets) + Stage 2 (per
target, `try/except` → `summary.failed`) + Stage 3 hook
(`_relate_stage3`, no-op, `TODO(TASK-2917)`). `add_book(relate=)` /
`add_folder(relate=)` wired; `add`/`add-folder` CLI gained `--relate`;
new `bookstore relate` command. `conftest.py::make_adapter._structured`
gained a `RelationDraft` branch parsing `book_id=` tokens from the
candidates section of the prompt (one `parallels` 0.7 + one `none` 0.9,
deterministic and order-based).
`pytest packages/ai-parrot/tests/knowledge/bookstore/ -q` → 105 passed,
same 3 pre-existing unrelated failures as prior tasks. `ruff check`
clean on every file this task touched (the 1 remaining `F401` on
`cli.py`'s `sys` import is the same pre-existing issue noted in
TASK-2914/2915, still untouched).

**Deviations from spec**: Touched two files NOT in this task's own
`Files to Create/Modify` list — both required for the task to be
implementable at all, both documented in the commit message and here:
1. `models.py` — `RelateSummary`'s field list. TASK-2913 first defined
   it with placeholder fields (`related`/`failed`/`skipped`/`llm_used`/
   `communities_computed`/`notes`) and *explicitly flagged them for
   re-verification* by this task, since the spec's Data Models block
   never actually lists `RelateSummary`'s fields. This task's own
   Codebase Contract specifies a *different*, concrete field list
   (`targets`/`deterministic_edges`/`llm_prompts`/`llm_edges`/
   `skipped_llm_reason`/`failed: dict`/`communities: Optional[int]`/
   `notes`) — replaced the placeholder with it, since without this the
   task's Scope (`relate_books -> RelateSummary`) and CLI summary
   printer are not implementable. No tests referenced the old field
   names (checked before changing).
2. `catalog.py` — added `CatalogStore.delete_relation_pair(src, dst,
   *, origin=None)`. The Key Constraints section requires "delete only
   (src, dst) pairs re-judged in this run, so edges judged earlier
   from the *other* direction survive" — not expressible with the
   existing `delete_relations(book_id=None, origin=None)`, whose
   `book_id` filter matches EITHER endpoint against every OTHER edge
   too (would also delete edges judged from the other book's
   perspective). Added as a narrow, additive CRUD method mirroring the
   TASK-2913 pattern, not a redesign.
