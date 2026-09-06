# TASK-2920: Bookstore — end-to-end integration tests, docs, legacy spec update

**Feature**: FEAT-533 — Bookstore Conceptual Relations
**Spec**: `sdd/specs/wikitoolkit-bookstore-conceptual-relations.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2918, TASK-2919
**Assigned-to**: unassigned

---

## Context

Spec §4 Integration Tests and the documentation acceptance criteria
(§5). The unit suites prove each module; this task proves the whole
funnel on a small synthetic library through the public entry points
(library API, CLI, MCP stdio, exported wiki plane) and writes the user
documentation, including updating the original bookstore spec so the
two documents agree.

---

## Scope

- `tests/knowledge/bookstore/test_integration_graph.py`:
  - fixture `library_five_books(tmp_path, monkeypatch)`: five
    `SAMPLE_MARKDOWN` variants ingested via `Bookstore.add_book` with
    `title/authors/topics` overrides forming two author groups and two
    tradition groups (adapter from `make_adapter()`), under
    `PARROT_LIBRARY_DIR=tmp_path/library`.
  - `test_relate_all_end_to_end_fake_adapter`: `relate_books(None)` →
    deterministic + llm edges + communities persisted; `related_books`
    and `communities()` non-empty; `catalog_search("estoicismo")` hits.
  - `test_cli_relate_related_communities_json`: `CliRunner` over
    `bookstore relate --all`, `related <id> --json`, `communities --json`.
  - `test_mcp_related_books_roundtrip`: spawn `bookstore mcp` (subprocess,
    like the existing `test_mcp_server.py` smoke) with `initialize`,
    `tools/list`, `tools/call bookstore_related_books` → valid JSON-RPC,
    zero non-protocol bytes on stdout.
  - `test_export_wiki_then_wiki_reads_it`: `export_wiki(register=False)`
    → `SQLiteWikiStore(..., read_only=True).dump_pages()/dump_edges()`
    counts match; `wiki/cli.py:_load_graphindex_nodes_edges(store,
    frozenset({"book"}))` returns N nodes / M edges (import from
    `parrot.knowledge.wiki.cli` inside the test only).
  - `test_no_llm_full_path`: same library with `adapter=None` →
    `relate_books` exits with Stage 1 + communities, LLM skipped note;
    MCP read tools still answer.
- Docs: create `docs/bookstore-graph.md` (what relations exist and
  their determinism, the `relate` cost model and judgement log,
  communities and labels, the three new tools + `expand_related`, the
  funnel step 1b, `export-wiki` + namespace, degradation matrix row,
  CLI reference); link it from `docs/bookstore-codex.md` (existing
  bookstore doc — check its name/section list first).
- Update `sdd/specs/bookstore-indexed-library.spec.md`: §3 ficha fields,
  §4 tool table (10 tools), §5 ingestion (`--relate`), §6 degradation
  matrix (relations row), with a one-line pointer to FEAT-533.
- Run the full knowledge test tree and record evidence in
  `artifacts/logs/feat-533-tests.log`.

**NOT in scope**: new features or behaviour changes; if an integration
test exposes a defect, fix it in the owning module **only if trivial**,
otherwise record it in the Completion Note as a follow-up.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/knowledge/bookstore/test_integration_graph.py` | CREATE | end-to-end tests |
| `docs/bookstore-graph.md` | CREATE | user documentation |
| `docs/bookstore-codex.md` | MODIFY | link to the new page |
| `sdd/specs/bookstore-indexed-library.spec.md` | MODIFY | sections 3/4/5/6 |
| `artifacts/logs/feat-533-tests.log` | CREATE | pytest evidence |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.bookstore.library import Bookstore                       # library.py:88
from parrot.knowledge.bookstore.config import resolve_locations                # config.py:78 — honours PARROT_LIBRARY_DIR
from parrot.knowledge.bookstore.cli import bookstore                           # cli.py:92 (click group) — use click.testing.CliRunner
from parrot.knowledge.wiki.store import SQLiteWikiStore                        # store.py:711 (test-only import)
from parrot.knowledge.wiki.cli import _load_graphindex_nodes_edges             # cli.py:900 (test-only import; private helper — acceptable in an integration test)
from tests.knowledge.bookstore.conftest import make_adapter, SAMPLE_MARKDOWN   # conftest.py:31, 18 (or rely on fixtures)
```

### Existing Signatures to Use
```python
# tests/knowledge/bookstore/test_mcp_server.py — existing subprocess smoke test: launches `python -m parrot.knowledge.bookstore.cli mcp` with PARROT_LIBRARY_DIR set, writes JSON-RPC `initialize` + `tools/list` to stdin, asserts every stdout line parses as JSON-RPC
# tests/knowledge/bookstore/test_cli.py — CliRunner usage pattern, `_open_bookstore` anchoring on invocation CWD
# tests/knowledge/bookstore/test_library.py — fixtures `store`, `store_no_llm`, `book_md`, `locations` (lines 1-40)
# bookstore/library.py (after TASK-2916/2917/2919): relate_books(...), related_books(...), communities(), get_community(), export_wiki(output_dir=None, *, scope="project", register=True)
# wiki/cli.py:900 — async def _load_graphindex_nodes_edges(store: BaseWikiStore, graph_kinds: frozenset[str]) -> tuple[list[UniversalNode], list[UniversalEdge]]
# docs/bookstore-codex.md — existing bookstore user doc (verify sections before linking)
# sdd/specs/bookstore-indexed-library.spec.md — §3 ficha, §4 tools (7), §5 ingestion, §6 degradation matrix, §7 acceptance
```

### Does NOT Exist
- ~~`docs/bookstore-graph.md`~~ — created here.
- ~~A public `wikitoolkit` Python API for "load plane by directory"~~ — use `SQLiteWikiStore(path, read_only=True)` directly.
- ~~`bookstore mcp` accepting `tools/call` for write operations~~ — none exist; the roundtrip uses a read tool only.
- ~~`pytest tests/integration/`~~ — bookstore tests live under `packages/ai-parrot/tests/knowledge/bookstore/`.

---

## Implementation Notes

### Pattern to Follow
```python
# integration fixture — ingest through the public API only
@pytest.fixture
async def library_five_books(tmp_path, monkeypatch):
    monkeypatch.setenv("PARROT_LIBRARY_DIR", str(tmp_path / "library"))
    store = Bookstore(resolve_locations(cwd=tmp_path), adapter=make_adapter())
    specs = [("calderon-vida", ["Calderón de la Barca"], ["barroco", "honor"]), ...]
    for stem, authors, topics in specs:
        md = tmp_path / f"{stem}.md"; md.write_text(SAMPLE_MARKDOWN.replace("Synthetic Handbook", stem))
        await store.add_book(md, title=stem, authors=authors, topics=topics)
    return store
```

### Key Constraints
- The fake adapter's `RelationDraft` branch must return ids present in the prompt (TASK-2916 conftest contract) — reuse it, do not fork a second adapter.
- MCP subprocess test must run with `use_llm` disabled (no `PARROT_BOOKSTORE_LLM`) to stay hermetic.
- Docs must state the cost model plainly: N prompts for N books, zero on re-run, labels one per community.
- The legacy spec edit is additive (append/adjust tables), keep its `Status: implemented`.

### References in Codebase
- `packages/ai-parrot/tests/knowledge/bookstore/test_mcp_server.py` — subprocess JSON-RPC pattern
- `docs/bookstore-codex.md` — doc style

---

## Acceptance Criteria

- [ ] All five integration tests pass with the fake adapter and offline
- [ ] `pytest packages/ai-parrot/tests/knowledge/ -q` green (bookstore, pageindex, graphindex) and `tests/knowledge/wiki/ -q` green; log saved to `artifacts/logs/feat-533-tests.log`
- [ ] `docs/bookstore-graph.md` exists and covers relations, `relate` cost model, communities, tools, funnel step 1b, `export-wiki`/namespace, degradation matrix, CLI reference
- [ ] `sdd/specs/bookstore-indexed-library.spec.md` §3/§4/§5/§6 updated and point to FEAT-533
- [ ] `ruff check packages/ai-parrot/src/parrot/knowledge/bookstore/` clean

---

## Test Specification

```python
# tests/knowledge/bookstore/test_integration_graph.py
async def test_relate_all_end_to_end_fake_adapter(library_five_books): ...
def test_cli_relate_related_communities_json(library_five_books, ...): ...
def test_mcp_related_books_roundtrip(library_five_books, ...): ...
async def test_export_wiki_then_wiki_reads_it(library_five_books, tmp_path): ...
async def test_no_llm_full_path(tmp_path, monkeypatch): ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2918 and TASK-2919 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** before writing any code
4. **Update status** in `sdd/tasks/index/wikitoolkit-bookstore-conceptual-relations.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2920-bookstore-graph-integration-tests-and-docs.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
