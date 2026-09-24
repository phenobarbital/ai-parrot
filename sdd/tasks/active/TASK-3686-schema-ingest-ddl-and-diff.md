# TASK-3686: `SchemaPlaneService.ingest_ddl` (live-wins merge rule) and `diff`

**Feature**: FEAT-600 — SQL Schema Plane
**Spec**: `sdd/specs/sql-schema-plane.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3684, TASK-3685
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3 (service half). Applies the brainstorm's merge rule: live is authoritative for facts; a DDL record creates a page only when no live page exists for that table id (`source="ddl"`); `defined_in` edges are always added; divergence is reported by `diff`, never resolved by timestamp.

---

## Scope

- Extend `schema/service.py` with `ingest_ddl(paths, *, origin, dialect, changed_only=False) -> SyncReport` and `diff(origin, *, live=None) -> list[dict]`.
- Write `test_ingest_and_diff.py`.

**NOT in scope**: CLI verbs and `--ledger` filing (TASK-3687); DDL parsing itself (TASK-3685).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/schema/service.py` | MODIFY | add ingest_ddl + diff |
| `packages/ai-parrot/tests/knowledge/wiki/schema/test_ingest_and_diff.py` | CREATE | tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED references (HEAD `0384596cf`, 2026-09-24). Use them VERBATIM. Anything not listed
> here must be verified with `grep`/`read` before use.

### Verified Imports
```python
from parrot.knowledge.wiki.schema.producers.ddl import fold_ddl     # TASK-3685
from parrot.knowledge.wiki.schema.service import SchemaPlaneService   # TASK-3684 (this task extends it)
from parrot.knowledge.wiki.schema.models import SyncReport, TableRecord  # TASK-3680
from parrot.knowledge.wiki.schema.render import render_page            # TASK-3681
```

### Existing Signatures to Use
```python
# TASK-3684 packages/ai-parrot/src/parrot/knowledge/wiki/schema/service.py
class SchemaPlaneService:
    async def sync(self, origin, *, tables=None, changed_only=False, dsn_resolver=None, toolkit=None) -> SyncReport
    async def get_table(self, origin, schema, table) -> Optional[TableMetadata]
    @property store -> SchemaStore   # TASK-3682: upsert_pages, upsert_columns, add_edges, get_page(:565), page_hashes(:837)
# store pages carry frontmatter JSON in body with key "source" ∈ information_schema | pg_catalog | ddl (TASK-3681 render_page)
```

### Does NOT Exist
- ~~a `merge`/`conflict` helper in the store~~ — the rule is implemented here, in the service
- ~~timestamp-based merging~~ — explicitly rejected (brainstorm); do not compare `introspected_at` to decide facts
- ~~ledger filing inside the service~~ — `diff --ledger` is a CLI concern (TASK-3687)

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/schema/service.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/schema/test_ingest_and_diff.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#BaseWikiStore.get_page",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#BaseWikiStore.add_edges"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
`sync` in TASK-3684 for report bucketing; `structural/service.py:431 _ensure_fresh` for hash-based drift.

### Key Constraints
- A live page (frontmatter `source != 'ddl'`) is never overwritten by `ingest_ddl` — only `defined_in` edges are added (AC5).
- `parse_errors` propagate into `SyncReport.parse_errors`; the call never fails as a whole.
- `diff` output rows: `{table_id, field, live, ddl}`; identical → `[]`.

### References in Codebase
- sdd/proposals/schema-plane.brainstorm.md — Open Questions (merge rule)
- sdd/specs/sql-schema-plane.spec.md §3 Module 3

---

## Implementation Blueprint

> Executor-ready starting point derived from spec §3 Interface Skeletons; anchors re-verified at HEAD
> `0384596cf`. Complete every `# FILL IN:` marker; never change a signature, class name or path fixed here.

### Steps (in order)
1. Add `ingest_ddl` after `sync` in `service.py` — why: same file, same report shape, serialized after TASK-3684 by the graph.
2. For each DDL record: if a live page exists → add only `defined_in` edges; else upsert page+columns+edges — why: merge rule.
3. Add `diff` comparing column name/type/nullable and PK/FK sets — why: divergence is reported, not resolved.
4. Tests: live-wins, ddl-fills-gap, parse errors reported, diff rows.

### `packages/ai-parrot/src/parrot/knowledge/wiki/schema/service.py` (MODIFY)
```python
# occurrences: 1 (verified after TASK-3684: grep -c '    async def lookup(self, ref: str)' packages/ai-parrot/src/parrot/knowledge/wiki/schema/service.py)
# BEFORE — insert above `    async def lookup(self, ref: str)` (i.e. right after `sync` ends)
    async def ingest_ddl(self, paths: list[Path], *, origin: str, dialect: str, changed_only: bool = False,
                         root: Optional[Path] = None) -> SyncReport:
        """Fold .sql files into the plane. Merge rule (decided): live facts win; DDL only fills tables without a live page
        (source="ddl") and always contributes `defined_in` edges; divergence is left to `diff`."""
        from parrot.knowledge.wiki.schema.producers.ddl import fold_ddl  # TASK-3685 (deferred: keeps service import-light)

        base = root or self.shared_root or Path.cwd()
        records, parse_errors = fold_ddl(paths, origin=origin, dialect=dialect, root=base)
        report = SyncReport(parse_errors=parse_errors)
        for rec in records:
            tid = table_concept_id(origin, rec.metadata.schema, rec.metadata.tablename)
            page, cols, edges = render_page(rec)
            existing = await self._store.get_page(tid, include_body=True)  # verified: store.py:565
            if existing is not None and _page_source(existing) != "ddl":
                await self._store.add_edges([(s, d, r) for s, d, r, _ in edges if r == "defined_in"])
                report.unchanged.append(tid)
                continue
            if changed_only and existing is not None and existing.get("content_hash") == rec.content_hash:
                report.unchanged.append(tid)
                continue
            await self._store.upsert_pages([page]); await self._store.upsert_columns(cols); await self._store.add_edges([e[:3] for e in edges])
            (report.updated if existing else report.created).append(tid)
        return report

    async def diff(self, origin: str, *, live: Optional[list[TableRecord]] = None) -> list[dict[str, Any]]:
        """Per-table differences between live facts and DDL records for one origin: rows {table_id, field, live, ddl}."""
        # FILL IN: `live` defaults to records rebuilt from stored live pages via get_table; DDL side = fold_ddl over the origin's
        #   cfg.ddl_paths; compare column name/type/nullable, primary_keys set, foreign_keys set — bounded by "report, never resolve"
        raise NotImplementedError


def _page_source(page: dict[str, Any]) -> str:
    """Read the `source` frontmatter key from a stored table page (render_page stores frontmatter JSON in body)."""
    # FILL IN: parse the frontmatter block of page["body"]; return "unknown" when absent — bounded by TASK-3681's body layout
    raise NotImplementedError
```
**Why**: Implements the decided merge rule at the only write site that can see both producers. The deferred import keeps `service.py` free of sqlglot at import time (circular-import guard, spec §7).

### FILL IN checklist
- [ ] `diff` implementation — report only
- [ ] `_page_source` frontmatter parse — TASK-3681 layout
- [ ] tests: live page untouched but gains `defined_in`; DDL-only table created with source ddl; parse error surfaces; diff rows / empty

---

## Acceptance Criteria

- [ ] live page present → `ingest_ddl` adds only a `defined_in` edge, page body unchanged (AC5)
- [ ] no live page → page created with frontmatter `source == 'ddl'`
- [ ] `parse_errors` non-empty when a statement fails; call returns normally (AC4)
- [ ] `diff` returns a row for a column type mismatch and `[]` when identical
- [ ] ruff/black clean

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/schema/test_ingest_and_diff.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/wiki/schema/test_ingest_and_diff.py
import pytest
from parrot.knowledge.wiki.schema.service import SchemaPlaneService
from parrot.knowledge.wiki.schema.models import SchemaPlaneConfig

@pytest.fixture
def svc(plane_dir): return SchemaPlaneService.from_dir(plane_dir, config=SchemaPlaneConfig(), read_only=False)

async def test_ddl_fills_gap(svc, tmp_path):
    f = tmp_path / "001.sql"; f.write_text("CREATE TABLE public.users (id int PRIMARY KEY, name text);")
    rep = await svc.ingest_ddl([f], origin="pg", dialect="postgres", root=tmp_path)
    assert rep.created == ["table:pg/public.users"]
    page = await svc.store.get_page("table:pg/public.users")
    assert '"source": "ddl"' in page["body"]

async def test_live_wins(svc, tmp_path, sales_metadata):
    await svc.put_table("pg", "postgres", sales_metadata)           # live page (source information_schema)
    f = tmp_path / "001.sql"; f.write_text("CREATE TABLE epson.sales (id int);")
    rep = await svc.ingest_ddl([f], origin="pg", dialect="postgres", root=tmp_path)
    assert rep.unchanged == ["table:pg/epson.sales"]
    rels = await svc.store.neighbors("table:pg/epson.sales", rel="defined_in")
    assert rels
```

---

## Agent Instructions

1. Read the spec (`sdd/specs/sql-schema-plane.spec.md`) §2, §3 module for this task, §6 Codebase Contract, §7.
2. Check dependencies — `TASK-3684, TASK-3685` must be in `sdd/tasks/completed/`.
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
