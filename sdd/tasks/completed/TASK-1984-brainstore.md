# TASK-1984: BrainStore — Lean Wiki Writer/Reader

**Feature**: FEAT-390 — Dream Cycle — Episodic→Wiki Brain Consolidation
**Spec**: `sdd/specs/dream-cycle-brain-consolidation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1983
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2. The dream cycle must write distilled knowledge into the
agent's brain wiki and the retrieval path must read it back — WITHOUT
constructing the full `LLMWikiToolkit` (which requires PageIndex/GraphIndex/OKF
toolkits, `toolkit.py:76`). `BrainStore` is a lean wrapper over the SQLite
wiki retrieval plane (`create_wiki_store`) that reproduces
`LLMWikiToolkit.remember()` semantics byte-for-byte, so the brain `wiki.db`
stays fully interoperable with `LLMWikiToolkit` and the `wikitoolkit` CLI.

---

## Scope

- Implement `parrot/memory/dream/brain.py` with class `BrainStore`:
  - `__init__(self, storage_dir: Path, wiki_name: str, asserted_by: str = "agent")`
    — creates/opens the store via `create_wiki_store(storage_dir, wiki_name=..., backend="sqlite")`.
  - `async remember(text, title=None, category="note", related_pages=None) -> dict`
    — MUST replicate `LLMWikiToolkit.remember()` (`toolkit.py:660-725`):
    deterministic `page_id = "mem-" + sha1(f"{title}::{category}").hexdigest()[:12]`,
    title defaults to first line of text truncated to 80 chars,
    `WikiPageRecord(concept_id=page_id, node_id=page_id, title=title,
    category=category, summary=text[:300], body=text,
    token_count=estimate_tokens(text), origin="memory",
    asserted_by=self.asserted_by)`, `upsert_pages([record])`, edges
    `(page_id, related, "references", "asserted")`; returns
    `{page_id, title, category, status: "created"|"updated"}`.
  - `async search(query, top_k=5, max_tokens=600) -> str` — `search_fts`
    (plus `search_vector` merge when embeddings exist), packed under the
    token budget via `pack_results`; returns `""` on no results or error
    (log WARNING — never raise).
  - `async copy_page_to(page_id, other: BrainStore) -> str` — reads the page
    (`get_page(..., include_body=True)`) and upserts it into `other`
    preserving title/category/body and original `asserted_by` attribution;
    returns the page_id in the destination.
- Write unit tests in `tests/memory/dream/test_brain.py`, including an
  interop test proving the page-id scheme matches `LLMWikiToolkit.remember()`.

**NOT in scope**: runner/scheduler logic, unified-layer retrieval wiring
(TASK-1988), episodic backends, bookkeeper logging (LLMWikiToolkit-only).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/memory/dream/brain.py` | CREATE | `BrainStore` |
| `packages/ai-parrot/src/parrot/memory/dream/__init__.py` | MODIFY | Export `BrainStore` |
| `tests/memory/dream/test_brain.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Lazy PEP 562 exports — verified: packages/ai-parrot/src/parrot/knowledge/wiki/__init__.py
from parrot.knowledge.wiki import create_wiki_store, WikiPageRecord, pack_results
# estimate_tokens is NOT in the package __init__ exports — import from the module:
from parrot.knowledge.wiki.store import estimate_tokens
# verified: packages/ai-parrot/src/parrot/knowledge/wiki/store.py:142
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/store.py
class BaseWikiStore(ABC):                                          # :268
    async def upsert_pages(self, pages: list[WikiPageRecord]) -> int  # :287
    async def add_edges(self, edges: list[tuple]) -> int              # :290
    async def get_page(self, concept_id, include_body=False)          # :310
    async def search_fts(...)                                         # :323
    async def search_vector(...)                                      # :328
class SQLiteWikiStore(BaseWikiStore):                              # :420
    def __init__(self, db_path: str | Path, wiki_name: str = "")      # :435
class WikiPageRecord(BaseModel):                                   # :194
    # fields used by remember() (verified at toolkit.py:697-707):
    # concept_id, node_id, title, category, summary, body, token_count,
    # origin, asserted_by
    # READ store.py:194-225 before use to confirm the full field list.

# Reference semantics — packages/ai-parrot/src/parrot/knowledge/wiki/toolkit.py:660
async def remember(self, wiki_name, text, title=None, category="note",
                   related_pages=None) -> dict:
    title = (title or text.strip().splitlines()[0][:80]).strip()
    page_id = "mem-" + hashlib.sha1(f"{title}::{category}".encode()).hexdigest()[:12]
    existing = await self._store.get_page(page_id, include_body=False)
    # ... WikiPageRecord(origin="memory", asserted_by=f"agent:{self.agent_id}") ...
    # edges: [(page_id, str(rp), "references", "asserted") for rp in related_pages]
    # returns {"page_id", "title", "category", "status": "updated"|"created"}
```

Check `create_wiki_store` factory signature in
`packages/ai-parrot/src/parrot/knowledge/wiki/store.py` (used at
`toolkit.py:105-109` as `create_wiki_store(config.storage_dir,
wiki_name=config.wiki_name, backend=config.storage_backend)`).

Check `pack_results` signature in
`packages/ai-parrot/src/parrot/knowledge/wiki/context.py` before use.

### Does NOT Exist
- ~~`LLMWikiToolkit` lightweight constructor~~ — requires pageindex/graphindex/okf
  toolkits (`toolkit.py:76`); do NOT instantiate it here — that's why BrainStore exists
- ~~`WikiPageRecord.metadata`~~ — unverified field; do not set page-level metadata
- ~~`BrainStore` bookkeeper/audit log~~ — `WikiBookkeeper` logging is
  LLMWikiToolkit's job; BrainStore does NOT log to the wiki bookkeeper
- ~~`estimate_tokens` in `parrot.knowledge.wiki` package exports~~ — import
  from `parrot.knowledge.wiki.store`

---

## Implementation Notes

### Pattern to Follow
Mirror `LLMWikiToolkit.remember()` at `toolkit.py:660-725` exactly for the
write path. For `search()`, follow how `WikiCombinedSearch`/CLI pack FTS
results with `pack_results` under a token budget (see
`parrot/knowledge/wiki/context.py`).

### Key Constraints
- Async throughout; `self.logger = logging.getLogger(__name__)`.
- `search()` degrades: any exception → log WARNING, return `""`.
- Import-light: importing `parrot.memory.dream.brain` must NOT pull the agent
  framework (the wiki package's lazy exports guarantee this — keep it so).
- `storage_dir` is created if missing (`mkdir(parents=True, exist_ok=True)`).

### References in Codebase
- `packages/ai-parrot/src/parrot/knowledge/wiki/toolkit.py:660` — remember() semantics
- `packages/ai-parrot/src/parrot/knowledge/wiki/store.py` — store plane
- `packages/ai-parrot/src/parrot/knowledge/wiki/context.py` — pack_results

---

## Acceptance Criteria

- [ ] `BrainStore.remember()` page ids are byte-identical to
      `LLMWikiToolkit.remember()` for the same (title, category)
- [ ] Same title+category twice → one page, second call returns `status="updated"`
- [ ] `search()` returns packed text for FTS hits; `""` when empty; never raises
- [ ] `copy_page_to()` moves a page across stores preserving attribution
- [ ] The produced `wiki.db` is readable by `SQLiteWikiStore` directly (interop test)
- [ ] All tests pass: `pytest tests/memory/dream/test_brain.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/memory/dream/`

---

## Test Specification

```python
# tests/memory/dream/test_brain.py
import hashlib
import pytest
from parrot.memory.dream import BrainStore


@pytest.fixture
def brain(tmp_path):
    return BrainStore(tmp_path / "brain", wiki_name="brain-test-agent",
                      asserted_by="agent:test-agent")


class TestBrainStore:
    async def test_remember_idempotent(self, brain):
        r1 = await brain.remember("Always check X before Y", title="Check X",
                                  category="lesson")
        r2 = await brain.remember("Always check X before Y (v2)",
                                  title="Check X", category="lesson")
        assert r1["page_id"] == r2["page_id"]
        assert r1["status"] == "created" and r2["status"] == "updated"

    async def test_page_id_matches_llmwikitoolkit_scheme(self, brain):
        r = await brain.remember("body", title="T", category="lesson")
        expected = "mem-" + hashlib.sha1("T::lesson".encode()).hexdigest()[:12]
        assert r["page_id"] == expected

    async def test_search_fts(self, brain):
        await brain.remember("PgVector JSONB merge needs || operator",
                             title="JSONB merge", category="lesson")
        out = await brain.search("JSONB merge")
        assert "JSONB" in out

    async def test_search_empty(self, brain):
        assert await brain.search("nothing here") == ""

    async def test_copy_page_to(self, brain, tmp_path):
        org = BrainStore(tmp_path / "org", wiki_name="org-test")
        r = await brain.remember("shared insight", title="Insight",
                                 category="concept")
        pid = await brain.copy_page_to(r["page_id"], org)
        assert pid == r["page_id"]
        assert "shared insight" in await org.search("shared insight")
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-1983 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** before writing ANY code — especially
   `WikiPageRecord`'s full field list (store.py:194) and `create_wiki_store` /
   `pack_results` signatures
4. **Update status** in `sdd/tasks/index/dream-cycle-brain-consolidation.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1984-brainstore.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-30
**Notes**: Implemented `BrainStore` in `parrot/memory/dream/brain.py`,
replicating `LLMWikiToolkit.remember()` page-id/record semantics
byte-for-byte (verified against `toolkit.py:660-725` before writing code).
`search()` uses `search_fts` + `pack_results` and degrades to `""` on any
exception or empty result set (never raises). `copy_page_to()` reads the
full page via `get_page(include_body=True)` and upserts it into the
destination store's `_store`, preserving `asserted_by`. 8 unit tests pass
(idempotency, page-id scheme match, FTS search, empty search, copy
+ attribution preservation, missing-page copy, and a direct
`SQLiteWikiStore` interop read of the produced `wiki.db`). `ruff check`
clean (2 auto-fixes applied: unnecessary UTF-8 encode args, quoted forward
self-reference type annotation resolved by `from __future__ import
annotations`).

**Deviations from spec**: The scope note says `search()` should do
"`search_fts` (plus `search_vector` merge when embeddings exist)". The
`BrainStore.__init__` signature specified in the spec/task
(`storage_dir, wiki_name, asserted_by`) does not accept an embedding
provider, and `search_vector` requires a pre-computed query embedding
vector — there is no verified, in-scope way to produce one here (that
wiring is TASK-1988's job, per the task's own "NOT in scope" list:
"unified-layer retrieval wiring (TASK-1988)"). Implemented FTS-only
search for this task; TASK-1988 can extend `search()` (or call
`search_vector` separately) once an embedding path is wired in. All
listed acceptance criteria for this task (idempotent remember, matching
page-id scheme, FTS search, empty-search degrade, copy_page_to,
`wiki.db` interop) are met.
