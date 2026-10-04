# TASK-3681: Page renderer: content_hash, sqlglot DDL, table/source/schema pages + edges

**Feature**: FEAT-600 — SQL Schema Plane
**Spec**: `sdd/specs/sql-schema-plane.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3680
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1 (part 2): `render.py` turns a `TableRecord` into one `WikiPageRecord`, its `columns` rows and its edges. OKF principle: JSON is authoritative, text is a deterministic projection. The DDL is rendered per dialect through sqlglot so it is byte-stable.

---

## Scope

- Create `schema/render.py` with `VOLATILE_FIELDS`, `content_hash`, `render_ddl`, `render_page`, `render_source_page`, `render_schema_page` (spec M1 skeleton).
- FK column pair goes into `ColumnRecord.fk_target`; the edge is plain `(src, dst, "references", "extracted")` (brainstorm decision).
- Write `test_render.py`.

**NOT in scope**: Persisting anything (TASK-3682), reading a database (TASK-3683), parsing DDL (TASK-3685).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/schema/render.py` | CREATE | renderer |
| `packages/ai-parrot/tests/knowledge/wiki/schema/test_render.py` | CREATE | tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED references (HEAD `0384596cf`, 2026-09-24). Use them VERBATIM. Anything not listed
> here must be verified with `grep`/`read` before use.

### Verified Imports
```python
from parrot.knowledge.wiki.schema.models import TableRecord, ColumnRecord, SchemaSourceConfig   # TASK-3680: packages/ai-parrot/src/parrot/knowledge/wiki/schema/models.py
from parrot.knowledge.wiki.schema.ids import table_concept_id, schema_concept_id, source_concept_id, parse_table_id  # TASK-3680: schema/ids.py
from parrot.knowledge.wiki.store import WikiPageRecord            # verified: packages/ai-parrot/src/parrot/knowledge/wiki/store.py:409
from parrot.bots.database.models import TableMetadata, Completeness  # verified: packages/ai-parrot/src/parrot/bots/database/models.py:131, :97
import sqlglot
from sqlglot import exp                                            # verified: pyproject.toml:182 sqlglot>=20.0; installed 30.18.0; exp.Create/ColumnDef/Schema/DataType exist
from parrot.bots.database.toolkits.sql import _SQLGLOT_DIALECT_MAP  # verified: packages/ai-parrot/src/parrot/bots/database/toolkits/sql.py:45
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/store.py:409
class WikiPageRecord(BaseModel): concept_id, node_id=None, title="", category="concept", summary="", body="", source_id=None,
                                 token_count=0, origin="ingest", asserted_by=None, updated_at=None, content_hash=None
# packages/ai-parrot/src/parrot/bots/database/models.py:131 — TableMetadata.columns: List[Dict[str, Any]] (keys used here: name, type, nullable, default, comment);
#   primary_keys: List[str]; foreign_keys: List[Dict] (keys: column, ref_schema, ref_table, ref_column); row_count :142; loaded_at; source :155
# edges accepted by BaseWikiStore.add_edges (store.py:1593): (src, dst, rel) or (src, dst, rel, provenance)
```

### Does NOT Exist
- ~~`_internal.generate_create_table_statement(TableMetadata)`~~ — it takes YAML text (`_internal.py:278`); do not call it
- ~~an `attrs` payload on edges~~ — edges are `(src, dst, rel, provenance)` only (store.py:112-120)
- ~~`TableMetadata.origin`~~ — origin/dialect come from `TableRecord`

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/schema/render.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/schema/test_render.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#WikiPageRecord",
    "sym:packages/ai-parrot/src/parrot/bots/database/models.py#TableMetadata",
    "sym:packages/ai-parrot/src/parrot/bots/database/toolkits/sql.py#_SQLGLOT_DIALECT_MAP"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
`symbols.py:190 symbol_to_page_fields` — record → page-field projection.

### Key Constraints
- `content_hash` must be stable across renders and ignore `VOLATILE_FIELDS` exactly as listed.
- Never put a DSN or credential in a page (G7); `render_source_page` writes `dsn_env` NAME only.
- Body sections in this order: frontmatter, `## DDL`, `## Columns`, `## Relations`.

### References in Codebase
- packages/ai-parrot/src/parrot/knowledge/wiki/symbols.py:190 — page-field projection
- sdd/specs/sql-schema-plane.spec.md §2 Page shape

---

## Implementation Blueprint

> Executor-ready starting point derived from spec §3 Interface Skeletons; anchors re-verified at HEAD
> `0384596cf`. Complete every `# FILL IN:` marker; never change a signature, class name or path fixed here.

### Steps (in order)
1. Write `render.py` from the block — why: fixes the page shape every consumer (tools, CLI, tests) reads.
2. Implement `render_ddl` with `exp.Create(this=exp.Schema(this=exp.to_table(...), expressions=[exp.ColumnDef(...)]))` — why: sqlglot gives per-dialect DDL for free and byte-stable output.
3. Write tests: hash stability, per-dialect DDL, edges/columns.

### `packages/ai-parrot/src/parrot/knowledge/wiki/schema/render.py` (CREATE)
```python
"""Deterministic projection of a TableRecord into a wiki page, column rows and edges (FEAT-600 M1)."""
from __future__ import annotations

import dataclasses
import hashlib
import json
from typing import Any

from sqlglot import exp

from parrot.bots.database.models import TableMetadata  # verified: bots/database/models.py:131
from parrot.bots.database.toolkits.sql import _SQLGLOT_DIALECT_MAP  # verified: toolkits/sql.py:45
from parrot.knowledge.wiki.schema.ids import schema_concept_id, source_concept_id, table_concept_id
from parrot.knowledge.wiki.schema.models import ColumnRecord, SchemaSourceConfig, TableRecord
from parrot.knowledge.wiki.store import WikiPageRecord  # verified: store.py:409

VOLATILE_FIELDS: tuple[str, ...] = ("row_count", "last_accessed", "access_frequency", "avg_query_time", "loaded_at")
Edge = tuple[str, str, str, str]


def content_hash(metadata: TableMetadata) -> str:
    """sha1 of the sorted-key JSON of ``asdict(metadata)`` minus VOLATILE_FIELDS."""
    data = {k: v for k, v in dataclasses.asdict(metadata).items() if k not in VOLATILE_FIELDS}
    return hashlib.sha1(json.dumps(data, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def render_ddl(record: TableRecord) -> str:
    """Canonical CREATE TABLE via sqlglot for ``record.dialect`` (falls back to generic SQL for unknown dialects)."""
    meta = record.metadata
    dialect = _SQLGLOT_DIALECT_MAP.get(record.dialect, record.dialect)
    cols = [
        exp.ColumnDef(this=exp.to_identifier(c["name"]), kind=exp.DataType.build(str(c.get("type", "TEXT")), dialect=dialect))
        for c in meta.columns
    ]
    # FILL IN: NOT NULL / DEFAULT / PRIMARY KEY constraints from c["nullable"], c.get("default"), meta.primary_keys — bounded by byte-stability (same input → same text)
    create = exp.Create(this=exp.Schema(this=exp.to_table(f"{meta.schema}.{meta.tablename}"), expressions=cols), kind="TABLE")
    return create.sql(dialect=dialect, pretty=True)


def render_page(record: TableRecord) -> tuple[WikiPageRecord, list[ColumnRecord], list[Edge]]:
    """Return (page, columns, edges). Edge rels: contains / references / depends_on / defined_in."""
    meta = record.metadata
    table_id = table_concept_id(record.origin, meta.schema, meta.tablename)
    fk_by_col = {fk["column"]: fk for fk in meta.foreign_keys if "column" in fk}
    columns = [
        ColumnRecord(
            table_id=table_id, ordinal=i, name=c["name"], data_type=str(c.get("type", "")), nullable=bool(c.get("nullable", True)),
            default=c.get("default"), comment=c.get("comment"), is_primary_key=c["name"] in meta.primary_keys,
            fk_target=(table_concept_id(record.origin, fk_by_col[c["name"]]["ref_schema"], fk_by_col[c["name"]]["ref_table"])
                       + "." + fk_by_col[c["name"]]["ref_column"]) if c["name"] in fk_by_col else None,
        )
        for i, c in enumerate(meta.columns)
    ]
    edges: list[Edge] = [(schema_concept_id(record.origin, meta.schema), table_id, "contains", "extracted")]
    edges += [(table_id, col.fk_target.rsplit(".", 1)[0], "references", "extracted") for col in columns if col.fk_target]
    edges += [(table_id, f, "defined_in", "extracted") for f in record.defined_in]
    frontmatter: dict[str, Any] = {
        "origin": record.origin, "dialect": record.dialect, "schema": meta.schema, "table": meta.tablename,
        "table_type": meta.table_type, "completeness": int(meta.completeness), "source": meta.source,
        "introspected_at": record.introspected_at, "content_hash": record.content_hash, "row_count": meta.row_count,
    }
    # FILL IN: body = frontmatter block + "## DDL" (render_ddl) + "## Columns" table + "## Relations" list — bounded by the section order in spec §2
    body = json.dumps(frontmatter, sort_keys=True)
    page = WikiPageRecord(
        concept_id=table_id, title=f"{meta.schema}.{meta.tablename}", category="table", summary=meta.comment or "",
        body=body, source_id=f"schema:{record.origin}", origin="ingest", content_hash=record.content_hash,
    )
    return page, columns, edges


def render_source_page(cfg: SchemaSourceConfig) -> WikiPageRecord:
    """``source:<alias>`` page — alias, dialect, schemas and the dsn_env NAME only (never a DSN value)."""
    body = json.dumps({"alias": cfg.alias, "dialect": cfg.dialect, "allowed_schemas": cfg.allowed_schemas, "dsn_env": cfg.dsn_env}, sort_keys=True)
    return WikiPageRecord(concept_id=source_concept_id(cfg.alias), title=cfg.alias, category="source", body=body,
                          source_id=f"schema:{cfg.alias}", origin="ingest")


def render_schema_page(origin: str, schema: str, table_ids: list[str]) -> WikiPageRecord:
    """``schema:<origin>/<schema>`` page listing its tables."""
    return WikiPageRecord(concept_id=schema_concept_id(origin, schema), title=f"{origin}/{schema}", category="schema",
                          body="\n".join(f"- {t}" for t in sorted(table_ids)), source_id=f"schema:{origin}", origin="ingest")
```
**Why**: Implements the spec §2 page shape and the two brainstorm decisions: FK column pair lives in `ColumnRecord.fk_target`, the edge stays plain `references`; `source:` pages carry only the env NAME (G7).

### FILL IN checklist
- [ ] `render_ddl` constraints (NOT NULL/DEFAULT/PK) — bounded by byte-stability
- [ ] `render_page` body sections — bounded by spec §2 order (frontmatter, DDL, Columns, Relations)
- [ ] tests: hash ignores volatile fields; postgres vs bigquery DDL differ; two renders identical; edges/columns for `sales_metadata`

---

## Acceptance Criteria

- [ ] `content_hash` unchanged when `row_count`/`loaded_at` change; changed when a column type changes
- [ ] `render_ddl` byte-identical across two calls; differs between `postgres` and `bigquery`
- [ ] `render_page(sales)` yields `contains` + `references` edges, `fk_target == 'table:<o>/epson.stores.id'`, `source_id == 'schema:<o>'`
- [ ] no DSN string appears in any rendered page
- [ ] ruff/black clean

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/schema/test_render.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/wiki/schema/test_render.py
from parrot.knowledge.wiki.schema.models import TableRecord
from parrot.knowledge.wiki.schema.render import content_hash, render_ddl, render_page

def _rec(meta, dialect="bigquery"):
    return TableRecord(origin=dialect, dialect=dialect, metadata=meta, content_hash=content_hash(meta), introspected_at="2026-09-24T00:00:00+00:00")

def test_hash_ignores_volatile(sales_metadata):
    h = content_hash(sales_metadata); sales_metadata.row_count = 999
    assert content_hash(sales_metadata) == h

def test_ddl_stable_and_dialect_specific(sales_metadata):
    a = render_ddl(_rec(sales_metadata)); assert a == render_ddl(_rec(sales_metadata))
    assert a != render_ddl(_rec(sales_metadata, "postgres"))

def test_page_edges_and_fk_target(sales_metadata):
    page, cols, edges = render_page(_rec(sales_metadata))
    assert page.concept_id == "table:bigquery/epson.sales" and page.source_id == "schema:bigquery"
    assert next(c for c in cols if c.name == "store_id").fk_target == "table:bigquery/epson.stores.id"
    assert ("table:bigquery/epson.sales", "table:bigquery/epson.stores", "references", "extracted") in edges
```

---

## Agent Instructions

1. Read the spec (`sdd/specs/sql-schema-plane.spec.md`) §2, §3 module for this task, §6 Codebase Contract, §7.
2. Check dependencies — `TASK-3680` must be in `sdd/tasks/completed/`.
3. Verify the Codebase Contract above (`grep`/`read`) before writing code; re-run `grep -c` on every MODIFY anchor.
4. Implement from the Blueprint; complete every `# FILL IN:`; run the Validation Commands
   (inside a worktree: `PYTHONPATH=packages/ai-parrot/src pytest …`), then `ruff check` + `black --check` on touched files.
5. Commit ONLY the files listed above. Move this file to `sdd/tasks/completed/`, update the per-spec index, fill the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker orchestrator (seat: gpt-5.6-terra, backend: codex, attempt_uid f9578e506bd34fffad42fa5901e538f3)
**Date**: 2026-09-24
**Notes**: Implementation commit `1b773c152` + engine lint-autofix commit `b2b501ccb` (merge `25c7ec2ff`). Created `schema/render.py` (`VOLATILE_FIELDS`, `content_hash`, `render_ddl`, `render_page`, `render_source_page`, `render_schema_page`) and `test_render.py`. Engine-side merge fidelity check passed (`unexpected_files: []`).
**Merge validation**: merge-tier (root scope) 4 failed, 1132 passed, 7 skipped, 20 warnings in 66.23s — same 4 pre-existing/environmental failures as prior chunks (see `issue:33fe54e65d2d`), unrelated to this task's files. Reviewed via `coder-review:ff60f805b62324ce6a18fab6`, zero fix commits needed.

**Deviations from spec**: none
