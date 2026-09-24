# TASK-3694: `DevLoopWikiSearch`: fold `table:` pages into the research context (best-effort)

**Feature**: FEAT-600 — SQL Schema Plane
**Spec**: `sdd/specs/sql-schema-plane.spec.md`
**Status**: pending
**Priority**: low
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 7. Mirrors `_get_ledger_context` (wiki_search.py:158): a best-effort, token-budgeted `## Related Tables` block appended when the federated store has `table` pages matching the query. Absent plane ⇒ output unchanged.

---

## Scope

- Add `_get_schema_context(query, max_tokens) -> Optional[str]` next to `_get_ledger_context` and fold its result into `build_research_context` after the ledger fold (anchor :140).
- Write `test_wiki_search_schema.py`.

**NOT in scope**: Anything in `knowledge/wiki/schema/`; mounting (TASK-3690).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/wiki_search.py` | MODIFY | schema context fold |
| `packages/ai-parrot/tests/flows/dev_loop/test_wiki_search_schema.py` | CREATE | tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED references (HEAD `0384596cf`, 2026-09-24). Use them VERBATIM. Anything not listed
> here must be verified with `grep`/`read` before use.

### Verified Imports
```python
from parrot.flows.dev_loop.wiki_search import DevLoopWikiSearch     # verified: packages/ai-parrot/src/parrot/flows/dev_loop/wiki_search.py:33 (__init__(*, store, wiki_name, shared_root=None))
from parrot.knowledge.wiki.store import SQLiteWikiStore, WikiPageRecord  # verified: store.py:855, :409 (tests seed a category="table" page)
from parrot.knowledge.wiki.context import truncate_to_tokens             # verified: imported at structural/tools.py:18
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/wiki_search.py
class DevLoopWikiSearch:
    def __init__(self, *, store: object, wiki_name: str, shared_root: Optional[Path] = None)     # :33 (self._store, self._wiki_name, self.logger)
    async def build_research_context(self, query, budget_tokens=_DEFAULT_BUDGET_TOKENS) -> Optional[str]   # :101
            ledger_context = await self._get_ledger_context(query, budget_tokens // 2)              # :140 ← anchor
            if wiki_context and ledger_context: return f"{wiki_context}\n\n## Related Issues\n{ledger_context}"  # :143-150 combine block
    async def _get_ledger_context(self, query: str, max_tokens: int) -> Optional[str]              # :158 (pattern)
# packages/ai-parrot/src/parrot/knowledge/wiki/store.py:576 BaseWikiStore.search_fts(query, category=None, limit=10) -> list[dict] (rows: concept_id, title, summary, …)
```

### Does NOT Exist
- ~~`DevLoopWikiSearch._get_schema_context`~~ — new
- ~~a `wiki_schema_*` call from the dev loop~~ — the dev loop reads the federated store directly, like it does for ledger pages

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/wiki_search.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/test_wiki_search_schema.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/wiki_search.py#DevLoopWikiSearch.build_research_context",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/wiki_search.py#DevLoopWikiSearch._get_ledger_context",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#BaseWikiStore.search_fts"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
wiki_search.py:158-200 `_get_ledger_context` — try/except, None on empty, truncate to budget.

### Key Constraints
- Best-effort: any exception → `None` + warning; never changes the return when no table pages match.
- Budget: `budget_tokens // 4` for the schema block.

### References in Codebase
- packages/ai-parrot/src/parrot/flows/dev_loop/wiki_search.py:101-200
- tests/knowledge/wiki/test_devloop_ledger_context.py — test style

---

## Implementation Blueprint

> Executor-ready starting point derived from spec §3 Interface Skeletons; anchors re-verified at HEAD
> `0384596cf`. Complete every `# FILL IN:` marker; never change a signature, class name or path fixed here.

### Steps (in order)
1. Add `_get_schema_context` — why: same best-effort contract as the ledger fold.
2. Fold after :140 and extend the combine block — why: `## Related Tables` must appear even when the wiki/ledger contexts are empty.
3. Tests: absent → unchanged; seeded `table` page → block present.

### `packages/ai-parrot/src/parrot/flows/dev_loop/wiki_search.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '            ledger_context = await self._get_ledger_context(query, budget_tokens // 2)' packages/ai-parrot/src/parrot/flows/dev_loop/wiki_search.py) → wiki_search.py:140
# AFTER — insert below:
            schema_context = await self._get_schema_context(query, budget_tokens // 4)  # FEAT-600, best-effort
# then in the combine block (:143-150): FILL IN — append f"\n\n## Related Tables\n{schema_context}" to whatever is returned when schema_context is truthy;
#   return the schema block alone when both wiki_context and ledger_context are None — bounded by "absent plane ⇒ output unchanged"

# NEW METHOD — place right after _get_ledger_context (:158+):
    async def _get_schema_context(self, query: str, max_tokens: int) -> Optional[str]:
        """Related `table:` pages from the schema plane (FEAT-600), best-effort; None when none match or on error."""
        try:
            rows = await self._store.search_fts(query, category="table", limit=8)  # verified: store.py:576
        except Exception as exc:  # noqa: BLE001
            self.logger.debug("schema context skipped: %s", exc)
            return None
        if not rows:
            return None
        from parrot.knowledge.wiki.context import truncate_to_tokens

        lines = [f"- {r['concept_id']} — {r.get('summary') or r.get('title', '')}" for r in rows]
        return truncate_to_tokens("\n".join(lines), max_tokens)
```
**Why**: Same shape as the ledger fold (TASK-3238 precedent) so the dev loop degrades gracefully without a plane.

### FILL IN checklist
- [ ] combine-block wiring for `## Related Tables`
- [ ] tests: no table pages → identical output; seeded table page → block contains the id

---

## Acceptance Criteria

- [ ] without table pages `build_research_context` output is unchanged
- [ ] with a seeded `category='table'` page matching the query the output contains `## Related Tables` and the page id
- [ ] `tests/knowledge/wiki/test_devloop_ledger_context.py` green
- [ ] ruff/black clean

---

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/test_wiki_search_schema.py -q`
- `pytest tests/knowledge/wiki/test_devloop_ledger_context.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/test_wiki_search_schema.py
from parrot.flows.dev_loop.wiki_search import DevLoopWikiSearch
from parrot.knowledge.wiki.store import SQLiteWikiStore, WikiPageRecord

async def test_related_tables_block(tmp_path):
    store = SQLiteWikiStore(tmp_path / "w.db", wiki_name="w")
    await store.upsert_pages([WikiPageRecord(concept_id="table:bigquery/epson.sales", title="epson.sales", category="table", summary="Daily sales", body="sales store_id")])
    ctx = await DevLoopWikiSearch(store=store, wiki_name="w").build_research_context("epson sales table", budget_tokens=800)
    assert ctx and "## Related Tables" in ctx and "table:bigquery/epson.sales" in ctx
```

---

## Agent Instructions

1. Read the spec (`sdd/specs/sql-schema-plane.spec.md`) §2, §3 module for this task, §6 Codebase Contract, §7.
2. Check dependencies — `none` must be in `sdd/tasks/completed/`.
3. Verify the Codebase Contract above (`grep`/`read`) before writing code; re-run `grep -c` on every MODIFY anchor.
4. Implement from the Blueprint; complete every `# FILL IN:`; run the Validation Commands
   (inside a worktree: `PYTHONPATH=packages/ai-parrot/src pytest …`), then `ruff check` + `black --check` on touched files.
5. Commit ONLY the files listed above. Move this file to `sdd/tasks/completed/`, update the per-spec index, fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
