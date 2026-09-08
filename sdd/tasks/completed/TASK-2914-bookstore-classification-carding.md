# TASK-2914: Bookstore — classification at carding (genre / traditions / period)

**Feature**: FEAT-533 — Bookstore Conceptual Relations
**Spec**: `sdd/specs/wikitoolkit-bookstore-conceptual-relations.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2913
**Assigned-to**: unassigned

---

## Context

Spec §2 Overview step 1 and §3 Module 1 (carding half), goal G1. The
carding LLM call already runs at ingest; extending its prompt fills the
new classification fields at zero extra cost. The deterministic
fallback leaves them empty. The CLI must show them and `refresh_card`
must carry them so `bookstore card --refresh` backfills old libraries.

---

## Scope

- `carding.py`: extend `_CARD_PROMPT` rules with `genre` (list the
  allowed values verbatim from `Genre`), `traditions` (2–5 short
  schools/traditions/movements the work belongs to, in the book's
  language or its usual scholarly name), `period` (short label). Add a
  `{genres}` format key to `_CARD_PROMPT`, filled from `Genre.__args__`
  in `generate_card_fields`. `fallback_card_fields` unchanged (defaults
  apply).
- `library.py`: `add_book` passes `draft.genre/traditions/period` into
  `BookCard`; `refresh_card` carries the three fields (`draft.x or
  card.x` pattern) and **preserves** `community_id`/`community_label`.
- `cli.py`: `_echo_card` prints genre / traditions / period / community
  when present; `list` shows a genre column; `show --json` includes them
  (comes for free from `model_dump`).
- `toolkit.py`: no code change needed (`get_card` uses `model_dump`,
  `brief()` updated in TASK-2913) — add a test asserting the fields
  surface through `bookstore_get_card` and `bookstore_catalog_search`.
- `conftest.py::make_adapter._structured`: `CardDraft` branch returns
  `genre="essay"`, `traditions=["Estoicismo"]`, `period="Imperio romano"`.
- Tests per the Test Specification.

**NOT in scope**: relation computation; any new table; `bookstore
relate`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/bookstore/carding.py` | MODIFY | prompt |
| `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py` | MODIFY | `add_book` card build, `refresh_card` |
| `packages/ai-parrot/src/parrot/knowledge/bookstore/cli.py` | MODIFY | `_echo_card`, `list` |
| `packages/ai-parrot/tests/knowledge/bookstore/conftest.py` | MODIFY | adapter returns classification |
| `packages/ai-parrot/tests/knowledge/bookstore/test_library.py` | MODIFY | ingest + refresh tests |
| `packages/ai-parrot/tests/knowledge/bookstore/test_cli.py` | MODIFY | show/list output |
| `packages/ai-parrot/tests/knowledge/bookstore/test_toolkit.py` | MODIFY | fields surface via tools |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.bookstore.carding import generate_card_fields, fallback_card_fields, derive_toc, sample_sections, slugify   # carding.py:154, 138, 83, 189, 44
from parrot.knowledge.bookstore.models import CardDraft, BookCard, Genre   # models.py:34, 64; Genre added by TASK-2913
from parrot.knowledge.bookstore.library import Bookstore, BookstoreError   # library.py:88, 55
```

### Existing Signatures to Use
```python
# bookstore/carding.py
_CARD_PROMPT = """You are a librarian ... Rules: - `title` ... - `summary`: ONE paragraph ..."""   # line 21; .format(filename=, doc_description=, toc_digest=, samples=)  (line 178)
async def generate_card_fields(adapter, *, filename, doc_description, toc_digest, samples) -> CardDraft   # line 154 — draft = await adapter.ask_structured(prompt, CardDraft); dict → CardDraft.model_validate
def fallback_card_fields(file_path: Path, toc_entries: list[TocEntry]) -> CardDraft   # line 138 — title from stem, topics from depth-1 titles

# bookstore/library.py
class Bookstore:
    async def add_book(self, file_path, scope="project", title=None, authors=None, topics=None, force=False) -> tuple[BookCard, str]   # line 343
        # ... draft = await self._draft_card(...)   (line ~381)
        # card = BookCard(book_id=slug, title=title or draft.title, authors=..., year=draft.year, language=draft.language, topics=..., summary=draft.summary, ...)   (lines ~396-415)
        # catalog.upsert(card)
    async def _draft_card(self, path, tree_name, scope, doc_description, toc_digest, toc_entries) -> CardDraft   # line ~420 — fallback when no LLM or on exception
    async def refresh_card(self, book_id: str) -> BookCard   # line 675 — updated = card.model_copy(update={title, authors, year, language, topics, summary, toc_digest, toc, card_origin}); catalog.upsert(updated)

# bookstore/cli.py
def _echo_card(card: Any) -> None   # line 69
@bookstore.command("list") def list_cmd(as_json: bool)   # line 241-243
@bookstore.command("show") def show(book_id, as_json)    # line 257-260
@bookstore.command("card") def card_cmd(book_id, refresh, llm)   # line 334-342

# tests/knowledge/bookstore/conftest.py
def make_adapter() -> MagicMock   # line 31 — _structured(prompt, schema, **kwargs): if schema is CardDraft: return CardDraft(title="Synthetic Handbook", authors=["Ada Example"], year=2024, language="en", topics=[...], summary=...)
# tests/knowledge/bookstore/test_library.py — fixtures `store`, `store_no_llm`, `book_md`, `locations`; tests test_add_book_markdown_with_llm (42), test_add_book_no_llm_fallback_card (68), test_add_book_manual_overrides (77)
```

### Does NOT Exist
- ~~`{genres}` key in `_CARD_PROMPT`~~ — add it (and pass it in `generate_card_fields`).
- ~~`refresh_card` handling of community fields~~ — today it copies a fixed set; the new fields must be added explicitly and community fields must survive the `model_copy`.
- ~~`CardDraft.genre` etc. before TASK-2913~~ — verify TASK-2913 is completed.
- ~~A `--genre` CLI override on `add`~~ — not in scope (only title/author/topic overrides exist).

---

## Implementation Notes

### Pattern to Follow
```python
# carding.py — prompt rules addition (keep the existing rules verbatim)
- `genre`: one of {genres}.
- `traditions`: 2-5 schools, traditions or movements this work belongs to (e.g. "estoicismo", "confucianismo", "siglo de oro"); empty if unclear.
- `period`: a short period label (e.g. "Imperio romano", "1600s"); null if unknown.
```

### Key Constraints
- `refresh_card` must not clear `community_id`/`community_label` — they are not carding outputs.
- No-LLM path stays deterministic: `fallback_card_fields` returns defaults; `card_origin="fallback"` unchanged.
- `_echo_card` output must stay stable for existing CLI tests (append lines, do not reorder).

### References in Codebase
- `packages/ai-parrot/src/parrot/knowledge/bookstore/carding.py:21-42` — prompt
- `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py:343-460, 675-702`

---

## Acceptance Criteria

- [ ] `_CARD_PROMPT` lists every `Genre` value and asks for traditions/period
- [ ] `add_book` with the fake adapter persists `genre="essay"`, `traditions=["estoicismo"]` (slugified), `period="Imperio romano"`
- [ ] `add_book` without LLM persists defaults (`other`, `[]`, `None`)
- [ ] `refresh_card` updates classification and preserves community fields
- [ ] `bookstore show` prints the fields; `bookstore_get_card` / `catalog_search` briefs include them
- [ ] `pytest packages/ai-parrot/tests/knowledge/bookstore/ -q` green; `ruff check` clean

---

## Test Specification

```python
# test_library.py (append)
async def test_add_book_persists_classification(store, book_md): ...
async def test_add_book_no_llm_classification_defaults(store_no_llm, book_md): ...
async def test_refresh_card_carries_classification_and_keeps_community(store, book_md): ...
# test_cli.py (append)
def test_show_prints_classification(...): ...
# test_toolkit.py (append)
async def test_get_card_and_briefs_include_classification(...): ...
# tests for carding
def test_card_prompt_requests_classification(): assert "genre" in _CARD_PROMPT and "traditions" in _CARD_PROMPT
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2913 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** before writing any code
4. **Update status** in `sdd/tasks/index/wikitoolkit-bookstore-conceptual-relations.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2914-bookstore-classification-carding.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-09-06
**Notes**: `_CARD_PROMPT` gained genre/traditions/period rules plus a
`{genres}` key filled from `get_args(Genre)` in `generate_card_fields`.
`Bookstore.add_book`'s `BookCard(...)` construction now passes
`draft.genre/traditions/period`; `refresh_card` carries them via the
`draft.x or card.x` pattern (as specified) and never touches
`community_id`/`community_label`. `_echo_card` appends a `class` line
(genre/traditions/period, only non-default parts) and a `community`
line. `conftest.py::make_adapter._structured`'s `CardDraft` branch now
returns `genre="essay"`, `traditions=["Estoicismo"]`,
`period="Imperio romano"`.
`pytest packages/ai-parrot/tests/knowledge/bookstore/ -q` → 83 passed,
3 pre-existing unrelated failures (same ones as TASK-2913, reproduced
identically against unmodified files). `ruff check` clean on every
file this task touched; 2 unrelated pre-existing `F401` warnings
(`carding.py: Optional`, `cli.py: sys`) verified present at HEAD before
this task's changes — left alone (no scope creep).

**Deviations from spec**: `test_card_prompt_requests_classification`
is in the Test Specification but not listed in this task's own
`Files to Create/Modify` (no `test_carding.py` exists; the file that
happens to hold `carding.py`'s other tests, `test_models.py`, is also
not in this task's file list — a small spec gap). Placed the test in
`test_library.py` (already in scope) rather than touching an
out-of-scope file, with a note in the test docstring explaining why.
