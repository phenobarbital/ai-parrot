# TASK-3685: DDL producer: statement splitting and sqlglot folding of `.sql` files into TableRecords

**Feature**: FEAT-600 — SQL Schema Plane
**Spec**: `sdd/specs/sql-schema-plane.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3680, TASK-3681
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3 (producer half). The offline path for coders: fold `.sql` migrations into the same `TableRecord`s the live producer emits, with `source="ddl"` and `defined_in` edges to the `file:` pages `repo_scan` already creates for `.sql` (file_suffixes.py:38). The FEAT-600 probe (finding F025) showed `sqlglot.parse` aborts a WHOLE file on one `ParseError` (6/32 in-repo files) and that inline `PRIMARY KEY` is a column constraint, not `exp.PrimaryKey` — both are handled here.

---

## Scope

- Create `schema/producers/ddl.py` — `split_statements`, `fold_ddl` per the spec M3 skeleton (Create TABLE/VIEW, ColumnDef + column constraints, PrimaryKey, ForeignKey, Alter ADD/DROP COLUMN + ADD CONSTRAINT, Command fallbacks skipped).
- Write `test_ddl_producer.py` including the in-repo corpus fixture `DDL_CORPUS` (6 tables / 70 columns / 3 FKs).

**NOT in scope**: Writing to the plane and the live/DDL merge rule (TASK-3686); CLI (TASK-3687); view `depends_on` extraction beyond best-effort `exp.Table` collection.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/schema/producers/ddl.py` | CREATE | DDL fold |
| `packages/ai-parrot/tests/knowledge/wiki/schema/test_ddl_producer.py` | CREATE | tests incl. corpus |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED references (HEAD `0384596cf`, 2026-09-24). Use them VERBATIM. Anything not listed
> here must be verified with `grep`/`read` before use.

### Verified Imports
```python
import sqlglot
from sqlglot import exp                                           # verified: installed 30.18.0; exp.Create, ColumnDef, PrimaryKey, ForeignKey, Alter, PrimaryKeyColumnConstraint, NotNullColumnConstraint, DefaultColumnConstraint, Reference, AlterColumn, Command, Schema, ColumnConstraint all exist
from sqlglot.errors import ParseError
from parrot.knowledge.wiki.repo_scan import file_concept_id      # verified: packages/ai-parrot/src/parrot/knowledge/wiki/repo_scan.py:263  def file_concept_id(rel_path: str) -> str
from parrot.bots.database.toolkits.sql import _SQLGLOT_DIALECT_MAP  # verified: toolkits/sql.py:45
from parrot.bots.database.models import TableMetadata, Completeness  # verified: bots/database/models.py:131, :97 (MetadataSource "ddl" added by TASK-3680)
from parrot.knowledge.wiki.schema.models import TableRecord       # TASK-3680
from parrot.knowledge.wiki.schema.render import content_hash      # TASK-3681
```

### Existing Signatures to Use
```python
# sqlglot 30.18.0 (probe F025): sqlglot.parse(text, read=dialect) -> list[Expression|None]; raises ParseError for the WHOLE text on the first bad statement
#   exp.Create.args: this (exp.Schema | exp.Table), kind ("TABLE"/"VIEW"/…), expression (view SELECT)
#   exp.Schema.args: this (exp.Table), expressions (ColumnDef | PrimaryKey | ForeignKey | …)
#   exp.ColumnDef.args: this (Identifier), kind (DataType), constraints (list[ColumnConstraint] whose .kind is PrimaryKeyColumnConstraint / NotNullColumnConstraint / DefaultColumnConstraint / Reference)
#   exp.ForeignKey.args: expressions (columns), reference (exp.Reference → .this is exp.Schema(this=Table, expressions=[cols]))
#   exp.Alter.args: this (Table), actions (list — ColumnDef for ADD COLUMN, exp.Drop for DROP COLUMN, AlterColumn, constraints)
# packages/ai-parrot/src/parrot/bots/database/models.py:131 TableMetadata(schema, tablename, table_type, full_name, comment=None, columns=[], primary_keys=[], foreign_keys=[], indexes=[], ..., completeness=FULL, source="unknown")
#   columns dicts use keys name/type/nullable/default/comment; foreign_keys dicts use column/ref_schema/ref_table/ref_column (same shape TASK-3681 reads)
```

### Does NOT Exist
- ~~`file_concept_id` in `symbols.py`~~ — it lives in `repo_scan.py:263`
- ~~any existing sqlglot DDL folding in the repo~~ — `exp.Create` appears once, in `security/query_validator.py:246`, as a *forbidden* statement type; nothing to reuse
- ~~`exp.PrimaryKey` for inline `id SERIAL PRIMARY KEY`~~ — that is a `PrimaryKeyColumnConstraint` inside `ColumnDef.args['constraints']`
- ~~a manifest/order file~~ — v1 folds in file-name (lexical) order only

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/schema/producers/ddl.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/schema/test_ddl_producer.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/repo_scan.py#file_concept_id",
    "sym:packages/ai-parrot/src/parrot/bots/database/models.py#TableMetadata",
    "sym:packages/ai-parrot/src/parrot/bots/database/toolkits/sql.py#_SQLGLOT_DIALECT_MAP"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
`security/query_validator.py` for how the repo walks sqlglot expressions (`find_all`); `producers/live.py` (TASK-3683) for the (records, errors) return shape.

### Key Constraints
- Per-statement `try/except ParseError`: a bad statement is recorded in `parse_errors[f'{file}#{n}']` and the rest of the file is still folded (AC4).
- `Command` fallbacks (PL/pgSQL, `DO $$`, `CREATE DATABASE`) are skipped silently.
- Records carry `source="ddl"`, `completeness=FULL`, `defined_in=[file_concept_id(rel_path)]`.
- Files folded in sorted path order; `ALTER` applies to the table already folded, or is recorded as an error when the table is unknown.

### References in Codebase
- packages/ai-parrot/src/parrot/security/query_validator.py:240-260 — sqlglot walk style
- sdd/state/FEAT-600/findings/F025-ddl-parse-probe.md — corpus numbers and gotchas
- packages/ai-parrot/src/parrot/tools/working_memory/task_memory/migrations/001_task_memory.sql — 6T/70c/4pk/3fk fixture

---

## Implementation Blueprint

> Executor-ready starting point derived from spec §3 Interface Skeletons; anchors re-verified at HEAD
> `0384596cf`. Complete every `# FILL IN:` marker; never change a signature, class name or path fixed here.

### Steps (in order)
1. Implement `split_statements` with `sqlglot.tokens.Tokenizer` positions or a `$$`-aware `;` scanner — why: one `ParseError` must not lose the file (F025: 6/32 files).
2. Implement `_fold_create` handling both table-level `exp.PrimaryKey`/`exp.ForeignKey` and column-level constraints — why: 4 PK for 20 tables in the probe means inline PKs were missed.
3. Implement `_fold_alter` for ADD/DROP COLUMN and ADD CONSTRAINT in file order — why: migrations are incremental.
4. Build `TableRecord(source='ddl')` with `defined_in=[file_concept_id(rel)]` — why: the `defined_in` edge is the coder's entry point from a `file:` page.
5. Tests: inline PK, alter sequence, bad statement isolation, corpus counts.

### `packages/ai-parrot/src/parrot/knowledge/wiki/schema/producers/ddl.py` (CREATE)
```python
"""DDL producer — fold .sql files into TableRecords with sqlglot, no database needed (FEAT-600 M3)."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

from parrot.bots.database.models import Completeness, TableMetadata  # verified: bots/database/models.py:97, :131
from parrot.bots.database.toolkits.sql import _SQLGLOT_DIALECT_MAP  # verified: toolkits/sql.py:45
from parrot.knowledge.wiki.repo_scan import file_concept_id  # verified: repo_scan.py:263
from parrot.knowledge.wiki.schema.models import TableRecord
from parrot.knowledge.wiki.schema.render import content_hash

logger = logging.getLogger(__name__)


def split_statements(sql_text: str) -> list[str]:
    """Split on ``;`` outside quotes and ``$$ … $$`` bodies so one ParseError never loses a whole file (F025)."""
    # FILL IN: linear scan tracking single/double quotes and $$ blocks; drop blank/comment-only chunks — bounded by "a statement boundary is never inside a string or a dollar-quoted body"
    raise NotImplementedError


def _table_key(table: exp.Table, default_schema: str) -> tuple[str, str]:
    return (table.db or default_schema, table.name)


def _fold_create(stmt: exp.Create, default_schema: str) -> TableMetadata | None:
    """exp.Create(kind=TABLE|VIEW) → TableMetadata; None for other kinds (INDEX, FUNCTION, …)."""
    kind = str(stmt.args.get("kind") or "").upper()
    if kind not in {"TABLE", "VIEW"}:
        return None
    schema_node = stmt.this
    table = schema_node.this if isinstance(schema_node, exp.Schema) else schema_node
    schema, name = _table_key(table, default_schema)
    meta = TableMetadata(schema=schema, tablename=name, table_type="BASE TABLE" if kind == "TABLE" else "VIEW",
                         full_name=f"{schema}.{name}", completeness=Completeness.FULL, source="ddl")
    for node in (schema_node.expressions if isinstance(schema_node, exp.Schema) else []):
        if isinstance(node, exp.ColumnDef):
            _add_column(meta, node)
        elif isinstance(node, exp.PrimaryKey):
            meta.primary_keys.extend(c.name for c in node.expressions)
        elif isinstance(node, exp.ForeignKey):
            _add_fk(meta, node, default_schema)
    # FILL IN: for VIEW, collect referenced exp.Table names from stmt.args["expression"].find_all(exp.Table) into meta.indexes? NO — put them in
    #   a `depends_on` list on the returned record via meta.comment-free side channel: return (meta, deps) — bounded by "best-effort, provenance extracted"
    return meta


def _add_column(meta: TableMetadata, col: exp.ColumnDef) -> None:
    """ColumnDef (+ inline constraints) → meta.columns / primary_keys / foreign_keys."""
    constraints = [c.kind for c in (col.args.get("constraints") or [])]
    entry = {"name": col.name, "type": col.args["kind"].sql() if col.args.get("kind") else "", "nullable": True, "default": None, "comment": None}
    for c in constraints:
        if isinstance(c, exp.PrimaryKeyColumnConstraint):
            meta.primary_keys.append(col.name); entry["nullable"] = False
        elif isinstance(c, exp.NotNullColumnConstraint):
            entry["nullable"] = False
        elif isinstance(c, exp.DefaultColumnConstraint):
            entry["default"] = c.this.sql()
        elif isinstance(c, exp.Reference):
            # FILL IN: inline REFERENCES other(col) → meta.foreign_keys dict — bounded by the foreign_keys key shape (column/ref_schema/ref_table/ref_column)
            pass
    meta.columns.append(entry)


def _add_fk(meta: TableMetadata, fk: exp.ForeignKey, default_schema: str) -> None:
    ref = fk.args.get("reference")
    target = ref.this if ref is not None else None  # exp.Schema(this=Table, expressions=[cols])
    if target is None:
        return
    rschema, rtable = _table_key(target.this, default_schema)
    for col, rcol in zip(fk.expressions, target.expressions, strict=False):
        meta.foreign_keys.append({"column": col.name, "ref_schema": rschema, "ref_table": rtable, "ref_column": rcol.name})


def fold_ddl(files: list[Path], *, origin: str, dialect: str, root: Path, default_schema: str = "public",
             ) -> tuple[list[TableRecord], dict[str, str]]:
    """Fold ``files`` (sorted) into TableRecords(source="ddl"); returns (records, parse_errors). Never raises for a bad file."""
    read = _SQLGLOT_DIALECT_MAP.get(dialect, dialect)
    tables: dict[tuple[str, str], TableMetadata] = {}
    defined_in: dict[tuple[str, str], list[str]] = {}
    errors: dict[str, str] = {}
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for path in sorted(files):
        rel = str(path.relative_to(root)) if path.is_absolute() else str(path)
        text = path.read_text(encoding="utf-8", errors="replace")
        for n, chunk in enumerate(split_statements(text)):
            try:
                stmt = sqlglot.parse_one(chunk, read=read)
            except ParseError as exc:
                errors[f"{rel}#{n}"] = str(exc).splitlines()[0][:200]
                continue
            if isinstance(stmt, exp.Command) or stmt is None:
                continue  # PL/pgSQL bodies, DO $$, CREATE DATABASE — skipped by design
            if isinstance(stmt, exp.Create):
                meta = _fold_create(stmt, default_schema)
                if meta is not None:
                    tables[(meta.schema, meta.tablename)] = meta
                    defined_in.setdefault((meta.schema, meta.tablename), []).append(file_concept_id(rel))
            elif isinstance(stmt, exp.Alter):
                # FILL IN: apply ADD COLUMN (ColumnDef) / DROP COLUMN (exp.Drop) / ADD CONSTRAINT (PrimaryKey|ForeignKey) to tables[key];
                #   unknown table → errors[f"{rel}#{n}"] = "ALTER of unknown table" — bounded by lexical file order
                pass
    records = [TableRecord(origin=origin, dialect=dialect, metadata=m, content_hash=content_hash(m), introspected_at=now,
                           defined_in=sorted(set(defined_in.get(k, [])))) for k, m in tables.items()]
    return records, errors
```
**Why**: Statement isolation and column-constraint folding are the two fixes the FEAT-600 probe demanded (F025). Records are indistinguishable from live ones except `source="ddl"`, so the renderer/store need no special case.

### FILL IN checklist
- [ ] `split_statements` scanner — quotes and `$$` bodies
- [ ] `_fold_create` VIEW dependencies — best effort
- [ ] `_add_column` inline REFERENCES
- [ ] `fold_ddl` ALTER handling — lexical order; unknown table → error
- [ ] tests: inline PK → `primary_keys==['id']`; ALTER ADD COLUMN folded; one bad statement keeps the file's other tables; corpus → 6 tables / 70 columns / 3 FKs

---

## Acceptance Criteria

- [ ] `fold_ddl([DDL_CORPUS])` → 6 tables, 70 columns, 3 FKs, PKs on every table that declares one inline
- [ ] a file with one unparseable statement still yields its other `CREATE TABLE`s and one `parse_errors` entry keyed `<file>#<n>` (AC4)
- [ ] records have `source == 'ddl'`, `completeness == FULL`, `defined_in == ['file:<rel>']`
- [ ] ruff/black clean

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/schema/test_ddl_producer.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/wiki/schema/test_ddl_producer.py
from pathlib import Path
from parrot.knowledge.wiki.schema.producers.ddl import fold_ddl, split_statements
from .conftest import DDL_CORPUS

def test_split_isolates_dollar_bodies():
    parts = split_statements("CREATE TABLE a(id int); CREATE FUNCTION f() RETURNS trigger AS $$ BEGIN x; END $$ LANGUAGE plpgsql; CREATE TABLE b(id int);")
    assert len(parts) == 3

def test_inline_primary_key(tmp_path):
    f = tmp_path / "001.sql"; f.write_text("CREATE TABLE t (id SERIAL PRIMARY KEY, name TEXT NOT NULL);")
    recs, errs = fold_ddl([f], origin="o", dialect="postgres", root=tmp_path)
    assert recs[0].metadata.primary_keys == ["id"] and errs == {}

def test_bad_statement_isolated(tmp_path):
    f = tmp_path / "002.sql"; f.write_text("CREATE TABLE ok(id int); THIS IS NOT SQL {{; CREATE TABLE ok2(id int);")
    recs, errs = fold_ddl([f], origin="o", dialect="postgres", root=tmp_path)
    assert {r.metadata.tablename for r in recs} == {"ok", "ok2"} and len(errs) == 1

def test_corpus_counts():
    recs, _ = fold_ddl([DDL_CORPUS], origin="taskmem", dialect="postgres", root=Path("."))
    assert len(recs) == 6 and sum(len(r.metadata.columns) for r in recs) == 70 and sum(len(r.metadata.foreign_keys) for r in recs) == 3
```

---

## Agent Instructions

1. Read the spec (`sdd/specs/sql-schema-plane.spec.md`) §2, §3 module for this task, §6 Codebase Contract, §7.
2. Check dependencies — `TASK-3680, TASK-3681` must be in `sdd/tasks/completed/`.
3. Verify the Codebase Contract above (`grep`/`read`) before writing code; re-run `grep -c` on every MODIFY anchor.
4. Implement from the Blueprint; complete every `# FILL IN:`; run the Validation Commands
   (inside a worktree: `PYTHONPATH=packages/ai-parrot/src pytest …`), then `ruff check` + `black --check` on touched files.
5. Commit ONLY the files listed above. Move this file to `sdd/tasks/completed/`, update the per-spec index, fill the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker orchestrator (seat: gpt-5.6-luna, backend: codex, attempt_uid 5e8d6fdc3a5f477498a02f3a7b718fcd)
**Date**: 2026-09-24
**Notes**: Implementation commit `6f08ea151` + engine lint-autofix commit `635962183` (merge `32317b732`). DDL producer: statement splitting and sqlglot folding of `.sql` files into TableRecords. Engine-side merge fidelity check passed (`unexpected_files: []`).
**Merge validation**: merge-tier (root scope) 4 failed, 1132 passed, 7 skipped, 20 warnings in 68.45s — same 4 pre-existing/environmental failures as prior chunks (see `issue:33fe54e65d2d`), unrelated to this task's files. Reviewed via `coder-review:e1f8d029a5016bdb6d45d288`, zero fix commits needed.

**Deviations from spec**: none
