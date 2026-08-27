# TASK-2496: `search_articles` typed helper (token-containment guard) + regex-first `as_of` extraction

**Feature**: FEAT-449 — Legal Librarian Answer Layer
**Spec**: `sdd/specs/legal-librarian-answer-layer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2494
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5. Two deterministic building blocks for the retrieval DAG
(TASK-2497): the Python wrapper around the declarative `search_articles`
pattern (mirroring `article_in_force`) with the **token-containment guard** —
the Python-side temporal check that drops a candidate whose lexical match
lives only in a superseded wording — and the regex-first `as_of` extractor
(R9) with a structured-LLM micro-call fallback only when regexes are
ambiguous.

Blocks TASK-2497, TASK-2498 (reuses the guard), TASK-2499.

---

## Scope

- `boe/models.py`: add `class ArticleHit(BaseModel)` with `articulo_key`,
  `norma_ref`, `numero`, `version: ArticleVersion`, `score: float`.
- `boe/queries.py`: add
  `async def search_articles(store, ctx, query, as_of, limit=20) -> list[ArticleHit]`:
  pattern from `ctx.ontology.traversal_patterns["search_articles"]` (loud
  `KeyError` mirroring `article_in_force`), `store.execute_traversal(ctx,
  pattern.query_template, bind_vars={"query": query, "as_of": as_of.isoformat(),
  "limit": limit})` — NO `collection_binds` (view name is literal). Then the
  guard: fold `s → unicodedata.normalize("NFKD", s).encode("ascii","ignore").decode().lower()`;
  query tokens = `re.findall(r"\w{4,}", folded_query)`; keep a hit iff ≥1
  token is a substring of the folded in-force `version.text`; if the query
  yields zero tokens, skip the guard. Expose the fold/tokenize helpers as
  module-level functions (`_fold`, `_query_tokens`, `passes_token_guard`) so
  TASK-2498 can reuse them.
- `librarian/as_of.py`: `async def extract_as_of(query: str, llm_ask) -> date | None`
  plus `class AsOfExtraction(BaseModel): as_of: date | None`. Regexes tried in
  order: ISO `\b(\d{4})-(\d{2})-(\d{2})\b`; numeric ES day-first
  `\b(\d{1,2})/(\d{1,2})/(\d{4})\b`; long ES (case-insensitive)
  `\b(\d{1,2})\s+de\s+(enero|…|diciembre)\s+de\s+(\d{4})\b`. Invalid calendar
  dates (31/02) discarded. Exactly one distinct date → return it, no LLM.
  Zero or >1 → one call `await llm_ask(prompt, structured_output=AsOfExtraction)`
  where `llm_ask` is an injected async callable (so tests never touch a
  client); return `.as_of` (may be `None` — the caller defaults to today).
  Also export a pure `regex_dates(query) -> list[date]` for testability.
- Tests: `test_search_articles_temporal_filter` (fake store returns a
  candidate whose only match is in a superseded version ⇒ dropped for a later
  `as_of`; kept when `as_of` inside its window), `test_search_articles_binds_and_pattern`,
  `test_token_guard_skipped_for_short_queries`, `test_extract_as_of_regex_first`
  (each regex form; accent/case; `llm_ask` must NOT be called),
  `test_extract_as_of_falls_back_to_llm_when_ambiguous` (two dates ⇒ called
  once), `test_invalid_calendar_date_ignored`.

**NOT in scope**: the flow wiring (TASK-2497); the ontology pattern itself
(TASK-2494); any embedding/vector fallback (R14 — forbidden).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/legal/boe/models.py` | MODIFY | `ArticleHit` |
| `packages/ai-parrot-tools/src/parrot_tools/legal/boe/queries.py` | MODIFY | `search_articles` + guard helpers |
| `packages/ai-parrot-tools/src/parrot_tools/legal/boe/__init__.py` | MODIFY | export `search_articles`, `ArticleHit` |
| `packages/ai-parrot-tools/src/parrot_tools/legal/librarian/as_of.py` | CREATE | `extract_as_of`, `AsOfExtraction`, `regex_dates` |
| `packages/ai-parrot-tools/tests/legal/test_search_articles.py` | CREATE | guard + binding tests |
| `packages/ai-parrot-tools/tests/legal/test_as_of.py` | CREATE | extraction tests |
| `packages/ai-parrot-tools/tests/legal/conftest.py` | MODIFY | `FakeGraphStore.execute_traversal` learns the `search_articles` template (return canned hits keyed by query) |

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-08-27 against `dev`.

### Verified Imports
```python
from parrot_tools.legal.boe.models import ArticleVersion                 # boe/models.py:16
from parrot_tools.legal.boe.queries import article_in_force              # boe/queries.py:24
from parrot.knowledge.ontology.graph_store import OntologyGraphStore     # graph_store.py:34
from parrot.knowledge.ontology.schema import TenantContext               # schema.py:406
```

### Existing Signatures to Use
```python
# boe/queries.py:24-80 — THE structural template to mirror
_PATTERN_NAME = "article_in_force"
async def article_in_force(store: OntologyGraphStore, ctx: TenantContext,
                           articulo_key: str, as_of: date) -> ArticleVersion | None:
    try:
        pattern = ctx.ontology.traversal_patterns[_PATTERN_NAME]
    except KeyError as exc:
        raise KeyError("Traversal pattern ... not declared ...") from exc
    rows = await store.execute_traversal(ctx, pattern.query_template,
        bind_vars={"articulo_key": articulo_key, "as_of": as_of.isoformat()},
        collection_binds={"@articulo": "articulo"})
    ...

# graph_store.py:193
async def execute_traversal(self, ctx, aql, bind_vars=None, collection_binds=None) -> list[dict[str, Any]]

# search_articles pattern rows (TASK-2494 template RETURN):
#   {articulo_key, norma_ref, numero, version: {n,text,valid_from,valid_to,...,content_hash,hash_norm_version}, score}

# bots/abstract.py:4202 — the real signature `llm_ask` will be bound to in TASK-2497:
async def ask(..., structured_output: Optional[Union[Type[BaseModel], StructuredOutputConfig]] = None, ...) -> AIMessage
#   result carried on response.structured_output — extract_as_of must accept either a
#   BaseModel or an AIMessage-like object with `.structured_output`; normalise inside.

# tests/legal/conftest.py:133 — FakeGraphStore.execute_traversal currently simulates only
#   the article_in_force AQL; extend it (branch on "legal_articulos_view" in the aql).
```

### Does NOT Exist
- ~~`search_articles` / `ArticleHit` / `librarian/as_of.py`~~ — created here.
- ~~`@@view` collection bind for the view~~ — view name is literal; passing `collection_binds` is wrong.
- ~~A Python re-implementation of version selection~~ — the AQL already selects the in-force version; the guard only checks token containment, it never re-selects versions.
- ~~`dateparser` / `dateutil` dependency~~ — not added; stdlib `re` + `datetime.date` only.
- ~~Vector/embedding fallback when BM25 returns nothing~~ — R14 rejected.

---

## Implementation Notes

### Pattern to Follow
```python
def _fold(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()

def _query_tokens(query: str) -> list[str]:
    return re.findall(r"\w{4,}", _fold(query))

def passes_token_guard(query: str, text: str | None) -> bool:
    tokens = _query_tokens(query)
    if not tokens:
        return True                      # short/stopword-only query: skip the guard
    folded = _fold(text or "")
    return any(t in folded for t in tokens)
```

### Key Constraints
- `search_articles` returns hits in the AQL's BM25 order (do not re-sort).
- `extract_as_of` performs at most ONE `llm_ask` call per invocation.
- Deterministic and unit-tested without any LLM/network.
- Google-style docstrings, strict typing.

### References in Codebase
- `packages/ai-parrot-tools/tests/legal/test_temporal_resolution.py` — test style for pattern wrappers (`test_uses_pattern_from_ontology_not_inline_aql` at :72)
- `packages/ai-parrot-tools/src/parrot_tools/legal/ids.py:19,43,94` — `normalize_boe_id`, `is_valid_boe_id`, `article_key`

---

## Acceptance Criteria

- [ ] `search_articles` reads the pattern from `ctx.ontology` (test asserts the AQL passed to the store contains `legal_articulos_view` and is not inlined in Python)
- [ ] A candidate whose match exists only in a superseded wording is dropped for a later `as_of` and kept for an `as_of` inside its window
- [ ] `extract_as_of("¿qué decía el art. 5 el 3 de marzo de 2019?", llm)` == `date(2019, 3, 3)` and `llm` not called
- [ ] Two distinct dates ⇒ `llm_ask` called exactly once; its `as_of` returned
- [ ] `31/02/2020` is ignored as a non-match
- [ ] All tests pass: `pytest packages/ai-parrot-tools/tests/legal/ -v`
- [ ] `ruff check packages/ai-parrot-tools/src/parrot_tools/legal/`

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/legal/test_as_of.py
from datetime import date
import pytest
from parrot_tools.legal.librarian.as_of import AsOfExtraction, extract_as_of, regex_dates


class Spy:
    def __init__(self, result=None): self.calls = 0; self.result = result
    async def __call__(self, prompt, *, structured_output): self.calls += 1; return AsOfExtraction(as_of=self.result)


@pytest.mark.parametrize("q,expected", [
    ("vigente a 2021-06-01", date(2021, 6, 1)),
    ("el 15/03/2020 qué decía", date(2020, 3, 15)),
    ("a 3 de Marzo de 2019", date(2019, 3, 3)),
])
async def test_extract_as_of_regex_first(q, expected):
    spy = Spy()
    assert await extract_as_of(q, spy) == expected and spy.calls == 0


async def test_falls_back_to_llm_when_ambiguous():
    spy = Spy(result=date(2020, 1, 1))
    assert await extract_as_of("entre 2019-01-01 y 2020-01-01", spy) == date(2020, 1, 1)
    assert spy.calls == 1


def test_invalid_calendar_date_ignored():
    assert regex_dates("31/02/2020") == []
```

```python
# packages/ai-parrot-tools/tests/legal/test_search_articles.py
from parrot_tools.legal.boe.queries import passes_token_guard, search_articles

def test_token_guard():
    assert passes_token_guard("plazo notificación", "El plazo se cuenta desde la notificacion")
    assert not passes_token_guard("plazo notificación", "Texto sin relación")
    assert passes_token_guard("ley", "cualquier texto")     # no tokens ≥4 chars ⇒ skipped

async def test_search_articles_temporal_filter(fake_store, legal_tenant_ctx):
    ...  # seed an articulo with v0 (contains "tres meses", valid_to 2020-01-01) and v1 ("seis meses")
    later = await search_articles(fake_store, legal_tenant_ctx, "tres meses", date(2022, 1, 1))
    assert later == []
    earlier = await search_articles(fake_store, legal_tenant_ctx, "tres meses", date(2019, 1, 1))
    assert earlier and earlier[0].version.n == 0
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** (§3 M5, §7 gotchas — "the view indexes ALL versions")
2. **Check dependencies** — TASK-2494 completed
3. **Verify the Codebase Contract** — re-read `boe/queries.py` and `conftest.py::FakeGraphStore.execute_traversal`
4. **Update status** in `sdd/tasks/index/legal-librarian-answer-layer.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2496-search-articles-and-as-of-extraction.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
