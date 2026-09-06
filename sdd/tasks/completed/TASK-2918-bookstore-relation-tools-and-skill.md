# TASK-2918: Bookstore — agent tools (`related_books`, `communities`, `get_community`, `expand_related`) + skill funnel

**Feature**: FEAT-533 — Bookstore Conceptual Relations
**Spec**: `sdd/specs/wikitoolkit-bookstore-conceptual-relations.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2917
**Assigned-to**: unassigned

---

## Context

Spec §2 User-Facing Behavior (agent tools), §3 Module 4, goal G5. The
graph is useless to Claude Code until the read-only MCP surface exposes
it and the skill tells the agent when to use it. The tools are thin
wrappers over `Bookstore.related_books/communities/get_community`
(SQL-only, no LLM, no wiki import). The skill text is mirrored in three
places and must stay in sync.

---

## Scope

- `toolkit.py` (`BookstoreToolkit`, `tool_prefix="bookstore"`):
  - `async related_books(book_id: str, rel: Optional[str] = None,
    depth: int = 1, top_k: int = 10) -> list[dict]` — clamps `depth`
    1–2, `top_k` 1–50; docstring explains `origin`/`confidence` and
    tells the agent to cite the origin.
  - `async communities() -> list[dict]` — `BookCommunity.model_dump()`
    minus `inter_relations`, members as briefs (`book_id`, `title`).
  - `async get_community(community_id: str) -> dict` — full row incl.
    `inter_relations`; unknown id → explanatory error dict/raise per the
    existing toolkit convention (check how `get_card` surfaces
    `BookstoreError` today and match it).
  - `async search(..., expand_related: bool = False)` → forwards to
    `Bookstore.search(expand_related=...)`.
- `library.py`: `Bookstore.search(..., expand_related: bool = False)` —
  after computing the shortlist and before the `[:max_books]` cap,
  when `expand_related`, append depth-1 neighbours of the shortlisted
  books (via `related_books`, strongest first, dedupe) — the
  `max_books` cap still applies afterwards.
- `mcp_server.py`: docstring "seven" → "ten" and the degradation
  matrix mention; no wiring change (tools come from `get_tools_sync()`).
- Skill text — **three mirrors, same wording**:
  `.agent/skills/bookstore/SKILL.md`, `.claude/commands/bookstore.md`,
  `packages/ai-parrot/src/parrot/knowledge/wiki/google/bookstore_assets.py::BOOKSTORE_SKILL`:
  add funnel step **1b — expand by relations** (`bookstore_related_books`
  on the best `catalog_search` hit before opening books;
  `bookstore_communities` when the question is thematic/comparative)
  and a **citation rule**: when a relation drives a claim, cite its
  origin (`"the library links these as parallels (LLM-inferred, 0.7)"`
  vs `"same author (deterministic)"`). Update the tool count and the
  CLI list (`bookstore related`, `bookstore communities`, `bookstore
  relate`).
- Tests per the Test Specification, including a mirror-sync test.

**NOT in scope**: `export-wiki` (TASK-2919); any write tool over MCP;
changing `bookstore_search`'s default behaviour.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/bookstore/toolkit.py` | MODIFY | three tools + `expand_related` |
| `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py` | MODIFY | `search(expand_related=)` |
| `packages/ai-parrot/src/parrot/knowledge/bookstore/mcp_server.py` | MODIFY | docstring |
| `.agent/skills/bookstore/SKILL.md` | MODIFY | funnel step 1b + citation rule |
| `.claude/commands/bookstore.md` | MODIFY | same |
| `packages/ai-parrot/src/parrot/knowledge/wiki/google/bookstore_assets.py` | MODIFY | same (`BOOKSTORE_SKILL`) |
| `packages/ai-parrot/tests/knowledge/bookstore/test_toolkit.py` | MODIFY | tool tests |
| `packages/ai-parrot/tests/knowledge/bookstore/test_mcp_server.py` | MODIFY | tools/list count = 10 |
| `packages/ai-parrot/tests/knowledge/bookstore/test_skill_text.py` | CREATE | mirror-sync test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.bookstore.toolkit import BookstoreToolkit            # toolkit.py:26
from parrot.knowledge.bookstore.library import Bookstore, BookstoreError   # library.py:88, 55
from parrot.knowledge.bookstore.mcp_server import create_bookstore_mcp_server   # mcp_server.py:61
from parrot.knowledge.wiki.google.bookstore_assets import BOOKSTORE_SKILL  # bookstore_assets.py:3 (test only — never import from bookstore/ runtime code)
```

### Existing Signatures to Use
```python
# bookstore/toolkit.py
class BookstoreToolkit(AbstractToolkit):                       # line 26
    name = "bookstore"; tool_prefix = "bookstore"              # lines 33-34
    def __init__(self, bookstore: Bookstore, **kwargs) -> None # line 36 — self._bookstore
    async def catalog_search(self, query: str, top_k: int = 8) -> list[dict]   # clamp: max(1, min(top_k, 50)); returns card.brief()
    async def get_card(self, book_id: str) -> dict            # model_dump minus toc/source_sha256 — see how BookstoreError propagates
    async def search(self, query: str, book_ids: Optional[list[str]] = None, max_books: int = 3) -> dict   # clamp 1-10 → self._bookstore.search(...)

# bookstore/library.py
async def search(self, query: str, book_ids: Optional[list[str]] = None, max_books: int = 3, top_k: int = 5) -> dict   # line ~262 — cards = resolve_book(...) or catalog_search(query, top_k=max_books) or list_books(); cards = cards[:max_books]; then LLM scoped walk or per-book BM25
def related_books(self, book_id, rel=None, depth=1, top_k=10, min_confidence=0.0) -> list[dict]   # TASK-2915
def communities(self) -> list[BookCommunity]; def get_community(self, community_id) -> BookCommunity   # TASK-2917

# bookstore/mcp_server.py
def create_bookstore_mcp_server(locations, adapter=None, lightweight_model=None) -> StdioMCPServer   # line 61 — toolkit = BookstoreToolkit(bookstore=store); tools = toolkit.get_tools_sync(); server.register_tools(tools)  (lines ~85-111)

# skill mirrors
.agent/skills/bookstore/SKILL.md            # frontmatter name/description/triggers/allowed-tools; sections: "The research funnel (mandatory order)" (steps 1-4 + cross-book), "Citation format", "Degraded modes", "Managing the library (CLI only)"
.claude/commands/bookstore.md               # 27 lines — slash-command wrapper
wiki/google/bookstore_assets.py             # BOOKSTORE_SKILL = """---...""" (72-line file) — same text for Antigravity installs

# tests/knowledge/bookstore/test_mcp_server.py — existing smoke: initialize + tools/list over stdin; asserts the seven tool names
```

### Does NOT Exist
- ~~`BookstoreToolkit.related_books/communities/get_community`~~, ~~`search(expand_related=)`~~ — created here.
- ~~Automatic relation expansion in `catalog_search`~~ — rejected in brainstorm; only the opt-in flag on `search`.
- ~~A fourth skill mirror~~ — exactly three files carry the skill text; `test_skill_text.py` compares the funnel section across them.
- ~~Write tools (`bookstore_relate` over MCP)~~ — forbidden (spec Non-Goals).

---

## Implementation Notes

### Pattern to Follow
```python
# toolkit.py — same shape as catalog_search
async def related_books(self, book_id: str, rel: Optional[str] = None, depth: int = 1, top_k: int = 10) -> list[dict[str, Any]]:
    """Books related to ``book_id`` through the library graph.

    Each item carries ``rel`` (same_author, shares_topic, same_tradition, same_genre, same_era,
    same_language, influenced_by, responds_to, parallels, contrasts_with, same_community),
    ``origin`` (deterministic | llm | community) and, for LLM relations, ``confidence`` and a
    ``rationale``. Cite the origin when a relation drives a claim. ...
    """
    return self._bookstore.related_books(book_id, rel=rel, depth=max(1, min(depth, 2)), top_k=max(1, min(top_k, 50)))
```

### Key Constraints
- Tool docstrings are the LLM-facing descriptions — write them for the agent, list the rel vocabulary.
- Outputs stay compact (briefs), never full cards or ToCs.
- `expand_related` must never exceed `max_books` and must not trigger any LLM call by itself.
- The mirror-sync test should compare a normalised slice (the funnel section) so frontmatter differences between files do not fail it.

### References in Codebase
- `packages/ai-parrot/src/parrot/knowledge/bookstore/toolkit.py:47-149` — tool style and clamps
- `.agent/skills/bookstore/SKILL.md` — current funnel text

---

## Acceptance Criteria

- [ ] MCP `tools/list` returns exactly 10 `bookstore_*` tools
- [ ] `related_books` clamps `depth` 1–2 and `top_k` 1–50; `get_community` on an unknown id surfaces an explanatory error
- [ ] `search(expand_related=True)` widens the shortlist but never exceeds `max_books` and makes no extra LLM call
- [ ] The three skill mirrors contain identical funnel step 1b + citation rule text (test)
- [ ] `parrot.knowledge.wiki` is not imported by `toolkit.py`/`library.py`/`mcp_server.py` (assert `"parrot.knowledge.wiki" not in sys.modules` after `create_bookstore_mcp_server`)
- [ ] `pytest packages/ai-parrot/tests/knowledge/bookstore/ -q` green; `ruff check` clean

---

## Test Specification

```python
# test_toolkit.py (append)
async def test_toolkit_related_books_clamps(...): ...
async def test_toolkit_communities_and_get_community(...): ...
async def test_toolkit_get_community_unknown(...): ...
async def test_search_expand_related_respects_max_books(...): ...
# test_mcp_server.py
def test_mcp_tools_list_has_ten_tools(...): ...
def test_mcp_server_does_not_import_wiki(...): ...
# test_skill_text.py
def test_skill_mirrors_share_funnel_section(): ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2917 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** before writing any code — `wiki/google/bookstore_assets.py` is under active edit by another feature; rebase onto `dev` first
4. **Update status** in `sdd/tasks/index/wikitoolkit-bookstore-conceptual-relations.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2918-bookstore-relation-tools-and-skill.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-09-06
**Notes**: `BookstoreToolkit`: `related_books`/`communities`/`get_community`
tools added (10 total, `EXPECTED_TOOLS` updated); `search`'s
`expand_related` forwards to `Bookstore.search`, which now has a new
`_expand_with_related` helper (widens the pre-`[:max_books]` shortlist,
no LLM). `mcp_server.py` docstring updated ("seven"→"ten" + degradation
matrix). Skill funnel step 1b + citation rule mirrored verbatim in all
three files; `test_skill_text.py` compares the exact strings (not a
loose "contains funnel" check) across all three so any future drift
fails loudly.
`pytest packages/ai-parrot/tests/knowledge/bookstore/ -q` → 123 passed,
same 3 pre-existing unrelated failures as prior tasks. `ruff check`
clean on every file this task touched.

**Deviations from spec**: none functionally. Two small, deliberately
out-of-scope observations, left untouched:
1. `packages/ai-parrot/src/parrot/knowledge/bookstore/__init__.py`'s
   module docstring still says "seven `bookstore_*` tools" — this task
   only lists `mcp_server.py`'s docstring for the count update, and
   the mismatch is purely cosmetic (no test asserts on it).
2. `.agents/skills/bookstore/SKILL.md` (note: `.agents`, plural) is a
   *different* directory from the task's listed `.agent/skills/bookstore/
   SKILL.md` (singular) — distinct file, different size/content, not
   in this task's file list. Left untouched; flagging in case it turns
   out to be a fourth mirror that should also carry the funnel/citation
   text in a future task.
