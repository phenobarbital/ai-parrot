# TASK-3680: Schema plane foundation: records, id grammar, project config, `ddl` source

**Feature**: FEAT-600 — SQL Schema Plane
**Spec**: `sdd/specs/sql-schema-plane.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1 (part 1). Every other module imports the records, the id helpers and the config block defined here. The `MetadataSource` literal gains `"ddl"` so the DDL producer can tag records. The package `__init__.py` uses a lazy `__getattr__` so later tasks never edit it (avoids file overlap).

---

## Scope

- Create `knowledge/wiki/schema/models.py` — `SchemaSourceConfig`, `SchemaPlaneConfig`, `ColumnRecord`, `TableRecord`, `LookupResult`, `SyncReport` exactly as spec §2 Data Models (plus `ddl_paths: list[str] = []` on `SchemaSourceConfig`, spec M4 note).
- Create `knowledge/wiki/schema/ids.py` — `KINDS`, `source_concept_id`, `schema_concept_id`, `table_concept_id`, `parse_table_id`, `normalize_ref`.
- Create `knowledge/wiki/schema/__init__.py` with a lazy `__getattr__` export map covering ALL public names of the package (including names created by later tasks), and the empty `schema/producers/__init__.py` package marker so TASK-3683/3685 never both create it.
- Modify `project.py`: add `schema: SchemaPlaneConfig` after `decisions` and `schema_path(root)` after `ledger_path`.
- Modify `bots/database/models.py`: add `"ddl"` to `MetadataSource`.
- Create test package `tests/knowledge/wiki/schema/` with `__init__.py`, `conftest.py` (shared fixtures) and tests for ids/config.

**NOT in scope**: render.py, store.py, service, producers, tools, CLI (TASK-3681…3690). Do not add any wiki import to bots/database.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/schema/__init__.py` | CREATE | lazy export map for the whole package |
| `packages/ai-parrot/src/parrot/knowledge/wiki/schema/models.py` | CREATE | Pydantic records + config |
| `packages/ai-parrot/src/parrot/knowledge/wiki/schema/ids.py` | CREATE | id grammar + normalize_ref |
| `packages/ai-parrot/src/parrot/knowledge/wiki/schema/producers/__init__.py` | CREATE | producers package marker (empty docstring module) |
| `packages/ai-parrot/src/parrot/knowledge/wiki/project.py` | MODIFY | `schema:` field + `schema_path()` |
| `packages/ai-parrot/src/parrot/bots/database/models.py` | MODIFY | `MetadataSource` += "ddl" |
| `packages/ai-parrot/tests/knowledge/wiki/schema/__init__.py` | CREATE | test package |
| `packages/ai-parrot/tests/knowledge/wiki/schema/conftest.py` | CREATE | shared fixtures: plane_dir, sales_metadata, DDL_CORPUS |
| `packages/ai-parrot/tests/knowledge/wiki/schema/test_ids.py` | CREATE | id grammar tests |
| `packages/ai-parrot/tests/knowledge/wiki/schema/test_models_config.py` | CREATE | config/records tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED references (HEAD `0384596cf`, 2026-09-24). Use them VERBATIM. Anything not listed
> here must be verified with `grep`/`read` before use.

### Verified Imports
```python
from pydantic import BaseModel, Field
from parrot.bots.database.models import TableMetadata, Completeness, MetadataSource   # verified: packages/ai-parrot/src/parrot/bots/database/models.py:131, :97, :108
from parrot.knowledge.wiki.decisions.models import DecisionConfig                    # verified: project.py:28 (import precedent for a sub-config)
from parrot.knowledge.wiki.project import WikiProjectConfig, PARROT_DIR               # verified: project.py:381, :42
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/project.py
class WikiProjectConfig(BaseModel):                       # :381
    decisions: DecisionConfig = Field(default_factory=DecisionConfig, description=(...))   # :478-485  ← insert `schema:` after this block
    def ledger_path(self, root: Path) -> Path: return root / PARROT_DIR / "ledger"          # :520-530  ← insert schema_path after
    def storage_path(self, root: Path) -> Path                                              # :532
# packages/ai-parrot/src/parrot/bots/database/models.py
MetadataSource = Literal["frontend", "information_schema", "pg_catalog", "unknown"]        # :108
@dataclass class TableMetadata: schema, tablename, table_type, full_name, comment, columns, primary_keys, foreign_keys :140,
    indexes, row_count :142, sample_data :143, ..., completeness=FULL :153, loaded_at, source: MetadataSource="unknown" :155
class Completeness(IntEnum): NAME_ONLY=1; WITH_COLUMNS=2; FULL=3                            # :97
# packages/ai-parrot/src/parrot/bots/database/toolkits/sql.py
_SQLGLOT_DIALECT_MAP: Dict[str, str]  # :45-59 keys: postgresql, postgres, bigquery, mysql, mariadb, sqlite, mssql, sqlserver, oracle, clickhouse, duckdb, redshift, snowflake
```

### Does NOT Exist
- ~~`parrot.knowledge.wiki.schema`~~ — nothing exists yet; this task creates the package
- ~~`TableMetadata.origin` / `.dialect`~~ — never add them; `TableRecord` carries origin/dialect
- ~~`DecisionConfig` defined in `project.py`~~ — it lives in `decisions/models.py:62` and is imported at project.py:28; mirror that (import `SchemaPlaneConfig` from `schema.models`, which must import nothing from `store`/`sqlglot`)
- ~~`WikiProjectConfig.schema_path`~~ — does not exist yet (this task adds it, mirroring `ledger_path`)

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/schema/__init__.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/schema/models.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/schema/ids.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/schema/producers/__init__.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/project.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/bots/database/models.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/schema/__init__.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/schema/conftest.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/schema/test_ids.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/schema/test_models_config.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#WikiProjectConfig",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#WikiProjectConfig.ledger_path",
    "sym:packages/ai-parrot/src/parrot/bots/database/models.py#TableMetadata",
    "sym:packages/ai-parrot/src/parrot/bots/database/models.py#Completeness"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
`decisions/models.py::DecisionConfig` (sub-config imported into `project.py:28`) and `symbols.py:141-190` (`sym_concept_id`/`parse_sym_id` id helpers).

### Key Constraints
- `schema/models.py` imports only pydantic + `parrot.bots.database.models` (circular-import trap, spec §7).
- Pydantic v2, Google docstrings, strict typing, 120 cols.
- `normalize_ref` never guesses: ambiguous `schema.table` returns the candidate list.
- `MetadataSource` change is additive; existing tests in `tests/bots/database/test_models.py` must stay green.

### References in Codebase
- packages/ai-parrot/src/parrot/knowledge/wiki/symbols.py:141-190 — id helper style
- packages/ai-parrot/src/parrot/knowledge/wiki/decisions/models.py:62 — sub-config precedent
- packages/ai-parrot/src/parrot/knowledge/wiki/project.py:478, :520 — insertion anchors

---

## Implementation Blueprint

> Executor-ready starting point derived from spec §3 Interface Skeletons; anchors re-verified at HEAD
> `0384596cf`. Complete every `# FILL IN:` marker; never change a signature, class name or path fixed here.

### Steps (in order)
1. Create `schema/models.py` from the block below — why: it is the contract every module imports; keep it dependency-free.
2. Create `schema/ids.py` — why: kind-first ids are the routing invariant (spec §2, brainstorm decision).
3. Create `schema/__init__.py` with the lazy export map — why: later tasks must not edit this file (file-overlap rule).
4. Insert `schema:` field and `schema_path()` into `project.py` at the verified anchors — why: mirrors `decisions`/`ledger_path`.
5. Add `"ddl"` to `MetadataSource` — why: the DDL producer must tag its records (AC13).
6. Write conftest + tests; run the Validation Commands.

### `packages/ai-parrot/src/parrot/knowledge/wiki/schema/models.py` (CREATE)
```python
"""Schema-plane records and configuration (FEAT-600 M1). Import-light on purpose: pydantic + bots.database.models only."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from parrot.bots.database.models import TableMetadata  # verified: bots/database/models.py:131


class SchemaSourceConfig(BaseModel):
    """One declared SQL source. Never holds a DSN — only the env-var NAME (spec G7)."""

    alias: str = Field(..., description="Origin alias; defaults to the dialect at add-source time")
    dialect: str = Field(..., description="Key of _SQLGLOT_DIALECT_MAP (toolkits/sql.py:45)")
    dsn_env: str = Field(..., description="Environment variable NAME holding the DSN")
    allowed_schemas: list[str] = Field(default_factory=lambda: ["public"])
    tables: list[str] | None = Field(default=None, description='Optional "schema.table" allowlist')
    include_samples: list[str] = Field(default_factory=list, description="Per-table sample_data allowlist")
    ddl_paths: list[str] = Field(default_factory=list, description="Repo-relative .sql paths/globs for ingest-ddl --changed")


class SchemaPlaneConfig(BaseModel):
    """`schema:` block of .parrot/wiki.json (mirrors DecisionConfig on WikiProjectConfig)."""

    enabled: bool = True
    sources: dict[str, SchemaSourceConfig] = Field(default_factory=dict)
    stale_after_days: dict[int, int] = Field(default_factory=lambda: {1: 30, 2: 14, 3: 7})


class ColumnRecord(BaseModel):
    """Row of the `columns` side table."""

    table_id: str
    ordinal: int
    name: str
    data_type: str
    nullable: bool = True
    default: str | None = None
    comment: str | None = None
    is_primary_key: bool = False
    fk_target: str | None = Field(default=None, description='"table:<origin>/<schema>.<table>.<column>"')


class TableRecord(BaseModel):
    """TableMetadata plus the plane-only identity fields."""

    model_config = ConfigDict(arbitrary_types_allowed=True)
    origin: str
    dialect: str
    metadata: TableMetadata
    content_hash: str
    introspected_at: str = Field(..., description="ISO-8601 UTC")
    defined_in: list[str] = Field(default_factory=list, description="file:<rel_path> ids")


class LookupResult(BaseModel):
    """Payload of wiki_schema_lookup / `schema lookup`."""

    page_id: str
    frontmatter: dict[str, Any]
    ddl: str
    columns: list[ColumnRecord]
    relations: list[dict[str, Any]]
    annotations: list[dict[str, Any]]
    age_days: float
    stale: bool


class SyncReport(BaseModel):
    """Result of sync / ingest_ddl."""

    created: list[str] = Field(default_factory=list)
    updated: list[str] = Field(default_factory=list)
    unchanged: list[str] = Field(default_factory=list)
    removed: list[str] = Field(default_factory=list)
    failed: dict[str, str] = Field(default_factory=dict)
    parse_errors: dict[str, str] = Field(default_factory=dict)
```
**Why**: Spec §2 Data Models verbatim plus `ddl_paths` (M4). `TableRecord.metadata` is the canonical bots/database dataclass, hence `arbitrary_types_allowed`. No import of store/sqlglot here — project.py imports this module.

### `packages/ai-parrot/src/parrot/knowledge/wiki/schema/ids.py` (CREATE)
```python
"""Kind-first id grammar for the schema plane: table:<origin>/<schema>.<table> (FEAT-600 M1)."""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from parrot.knowledge.wiki.schema.models import SchemaSourceConfig

KINDS: tuple[str, ...] = ("source", "schema", "table")
_TABLE_RE = re.compile(r"^table:(?P<origin>[^/]+)/(?P<schema>[^.]+)\.(?P<table>.+)$")
_BARE_RE = re.compile(r"^(?P<origin>[A-Za-z0-9_-]+):(?P<schema>[^.]+)\.(?P<table>.+)$")
_SCHEMA_TABLE_RE = re.compile(r"^(?P<schema>[^.:/]+)\.(?P<table>[^.:/]+)$")


def source_concept_id(origin: str) -> str:
    """Return ``source:<origin>``."""
    return f"source:{origin}"


def schema_concept_id(origin: str, schema: str) -> str:
    """Return ``schema:<origin>/<schema>``."""
    return f"schema:{origin}/{schema}"


def table_concept_id(origin: str, schema: str, table: str) -> str:
    """Return ``table:<origin>/<schema>.<table>``; dialect case is preserved, nothing is lower-cased."""
    return f"table:{origin}/{schema}.{table}"


def parse_table_id(concept_id: str) -> tuple[str, str, str]:
    """Return ``(origin, schema, table)``; raise ``ValueError`` for any other kind or malformed id."""
    m = _TABLE_RE.match(concept_id)
    if m is None:
        raise ValueError(f"not a table id: {concept_id!r}")
    return m["origin"], m["schema"], m["table"]


def normalize_ref(ref: str, *, sources: dict[str, "SchemaSourceConfig"] | None = None) -> str | list[str]:
    """Accept ``table:o/s.t``, bare ``o:s.t`` or ``s.t``; return the table id, or the candidate ids when ``s.t``
    is ambiguous across ``sources`` (never guesses). Returns ``[]`` when ``s.t`` matches no declared source."""
    if _TABLE_RE.match(ref):
        return ref
    bare = _BARE_RE.match(ref)
    if bare and not ref.startswith(tuple(k + ":" for k in KINDS)):
        return table_concept_id(bare["origin"], bare["schema"], bare["table"])
    st = _SCHEMA_TABLE_RE.match(ref)
    if st is None:
        raise ValueError(f"unrecognised table reference: {ref!r}")
    candidates = [
        table_concept_id(alias, st["schema"], st["table"])
        for alias, cfg in (sources or {}).items()
        if st["schema"] in cfg.allowed_schemas
    ]
    # FILL IN: when exactly one candidate, return it as a str; otherwise return the list — bounded by AC3 (never guess)
    return candidates
```
**Why**: Kind must lead the id because `FederatedWikiStore._route_bare_overlay_id` routes by kind prefix (federation.py:917). The owner's `origin:object` form is accepted on input only.

### `packages/ai-parrot/src/parrot/knowledge/wiki/schema/__init__.py` (CREATE)
```python
"""Schema plane — SQL data-model knowledge as a wikitoolkit overlay plane (FEAT-600).

Lazy exports so later tasks add modules without editing this file."""
from __future__ import annotations

import importlib
from typing import Any

_EXPORTS: dict[str, str] = {
    # models / ids (TASK-3680)
    "SchemaSourceConfig": "models", "SchemaPlaneConfig": "models", "ColumnRecord": "models", "TableRecord": "models",
    "LookupResult": "models", "SyncReport": "models",
    "KINDS": "ids", "source_concept_id": "ids", "schema_concept_id": "ids", "table_concept_id": "ids",
    "parse_table_id": "ids", "normalize_ref": "ids",
    # render (TASK-3681) · store (TASK-3682) · service (TASK-3684) · tools/toolkit (TASK-3689)
    "content_hash": "render", "render_ddl": "render", "render_page": "render",
    "render_source_page": "render", "render_schema_page": "render",
    "SchemaStore": "store",
    "SchemaPlaneService": "service", "SchemaPlaneReader": "service",
    "create_schema_tools": "tools", "SchemaPlaneToolkit": "toolkit",
}
__all__ = sorted(_EXPORTS)


def __getattr__(name: str) -> Any:
    """Resolve a public name from its submodule on first access."""
    try:
        module = importlib.import_module(f"{__name__}.{_EXPORTS[name]}")
    except KeyError as exc:
        raise AttributeError(name) from exc
    return getattr(module, name)
```
**Why**: Only this task touches `__init__.py`; the lazy map lists names from later tasks so `from parrot.knowledge.wiki.schema import SchemaStore` works once TASK-3682 lands, without a second edit.

### `packages/ai-parrot/src/parrot/knowledge/wiki/project.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    decisions: DecisionConfig = Field(' packages/ai-parrot/src/parrot/knowledge/wiki/project.py) → project.py:478
# AFTER — insert below the closing `)` of the `decisions: DecisionConfig = Field(...)` block (ends :485)
    schema: SchemaPlaneConfig = Field(
        default_factory=SchemaPlaneConfig,
        description="SQL schema plane settings (FEAT-600): declared sources (env NAMES only), staleness policy.",
    )
# top of file, next to `from parrot.knowledge.wiki.decisions.models import DecisionConfig` (:28):
from parrot.knowledge.wiki.schema.models import SchemaPlaneConfig

# occurrences: 1 (verified: grep -c '    def ledger_path(self, root: Path) -> Path:' …/project.py) → project.py:520
# AFTER — insert below the `return root / PARROT_DIR / "ledger"` line that closes ledger_path (:530)
    def schema_path(self, root: Path) -> Path:
        """Directory of the shared SQL schema plane (``.parrot/schema``, FEAT-600).

        Args:
            root: Shared root (main checkout) — see ``find_shared_root``.

        Returns:
            ``<root>/.parrot/schema``.
        """
        return root / PARROT_DIR / "schema"
```
**Why**: Same shape as `decisions`/`ledger_path`. `schema.models` has no store/sqlglot import, so no circular import (FEAT-578 trap, `c85837ae4`).

### `packages/ai-parrot/src/parrot/bots/database/models.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'MetadataSource = Literal["frontend", "information_schema", "pg_catalog", "unknown"]' …/bots/database/models.py) → :108
# REPLACE the line with:
MetadataSource = Literal["frontend", "information_schema", "pg_catalog", "ddl", "unknown"]
```
**Why**: Additive literal widening (AC13); `TableMetadata(source="ddl")` must validate.

### `packages/ai-parrot/tests/knowledge/wiki/schema/conftest.py` (CREATE)
```python
"""Shared fixtures for FEAT-600 schema-plane tests."""
from __future__ import annotations

from pathlib import Path

import pytest

from parrot.bots.database.models import Completeness, TableMetadata  # verified: bots/database/models.py:97, :131

DDL_CORPUS = Path("packages/ai-parrot/src/parrot/tools/working_memory/task_memory/migrations/001_task_memory.sql")


@pytest.fixture
def plane_dir(tmp_path: Path) -> Path:
    """Throwaway `.parrot/schema` directory."""
    return tmp_path / ".parrot" / "schema"


@pytest.fixture
def sales_metadata() -> TableMetadata:
    """epson.sales with store_id FK → epson.stores(id); FULL, information_schema."""
    return TableMetadata(
        schema="epson", tablename="sales", table_type="BASE TABLE", full_name="epson.sales", comment="Daily sales",
        columns=[
            {"name": "id", "type": "INT64", "nullable": False},
            {"name": "store_id", "type": "INT64", "nullable": False, "comment": "T-ROC store id"},
            {"name": "amount", "type": "NUMERIC", "nullable": True},
        ],
        primary_keys=["id"],
        foreign_keys=[{"column": "store_id", "ref_schema": "epson", "ref_table": "stores", "ref_column": "id"}],
        completeness=Completeness.FULL, source="information_schema",
    )
```
**Why**: Fixture names are referenced by TASK-3681…3696 tests; do not rename. Only this task edits conftest.py.

### FILL IN checklist
- [ ] `ids.py::normalize_ref` — single-candidate collapse to `str`; bounded by AC3 (never guess)
- [ ] `test_ids.py` — round-trip, bare form, ambiguous form, malformed → `ValueError`
- [ ] `test_models_config.py` — `WikiProjectConfig().schema.enabled is True`; `schema_path(root) == root/.parrot/schema`; a `wiki.json` without `schema` still loads; `TableMetadata(source="ddl")` validates

---

## Acceptance Criteria

- [ ] `parse_table_id(table_concept_id(o,s,t)) == (o,s,t)`; other kinds raise `ValueError`
- [ ] `normalize_ref` handles the three forms; ambiguous `s.t` returns a list (AC3)
- [ ] `WikiProjectConfig` gains `schema` (default enabled) and `schema_path`; existing project tests stay green
- [ ] `MetadataSource` accepts `"ddl"` (AC13); `pytest packages/ai-parrot/tests/bots/database/test_models.py -q` green
- [ ] `python -c "import parrot.knowledge.wiki.project"` succeeds (no circular import)
- [ ] `ruff check` + `black --check` clean on touched files

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/schema/test_ids.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/schema/test_models_config.py -q`
- `pytest packages/ai-parrot/tests/bots/database/test_models.py -q`
- `pytest tests/knowledge/wiki/test_project_shared_root.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/wiki/schema/test_ids.py
import pytest
from parrot.knowledge.wiki.schema.ids import normalize_ref, parse_table_id, table_concept_id
from parrot.knowledge.wiki.schema.models import SchemaSourceConfig

def test_roundtrip():
    tid = table_concept_id("bigquery", "epson", "sales")
    assert tid == "table:bigquery/epson.sales"
    assert parse_table_id(tid) == ("bigquery", "epson", "sales")

def test_other_kind_raises():
    with pytest.raises(ValueError):
        parse_table_id("schema:bigquery/epson")

def test_normalize_bare_form():
    assert normalize_ref("bigquery:epson.sales") == "table:bigquery/epson.sales"

def test_normalize_ambiguous_returns_candidates():
    srcs = {"a": SchemaSourceConfig(alias="a", dialect="postgres", dsn_env="A", allowed_schemas=["public"]),
            "b": SchemaSourceConfig(alias="b", dialect="postgres", dsn_env="B", allowed_schemas=["public"])}
    out = normalize_ref("public.users", sources=srcs)
    assert isinstance(out, list) and len(out) == 2   # FILL IN: single-candidate case → str
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

**Completed by**: sdd-worker orchestrator (seat: gpt-5.6-terra, backend: codex, attempt_uid 52e92c89743a49858c0b4acbe2dd3402)
**Notes**: Implementation commit `784ac5ee2` + engine lint-autofix commit `27c9e8289` (merge `9cf7f3c6b`). Created `schema/models.py`, `schema/ids.py`, `schema/producers/__init__.py`, `schema/__init__.py` (lazy `__getattr__`), the `tests/knowledge/wiki/schema/` package, added `schema: SchemaPlaneConfig` + `schema_path()` to `project.py`, and `"ddl"` to `MetadataSource`. Engine-side merge fidelity check passed (`unexpected_files: []`).

- Task: TASK-3680
- Feature: sql-schema-plane
- Implementation SHA: 784ac5ee2 (+ lint-autofix 27c9e8289)
- Closed at (UTC): 2026-09-24T21:58:59+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| merge_validation | merge-tier (root scope) 4 failed, 1132 passed, 7 skipped, 20 warnings in 66.36s — all 4 failures confirmed pre-existing on origin/dev / known worktree environment limitation, unrelated to this task (see issue:33fe54e65d2d) |
| review_feedback_id | coder-review:fe5418549d936fb9cf76badf |
| seat_summary | Seat: gpt-5.6-terra · Backend: codex · Model: gpt-5.6-terra · Attempts: 1 · Duration: 191.72s · Tokens: n/a |
