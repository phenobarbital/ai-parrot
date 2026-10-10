# TASK-4230: Migrations 009 (form_data SQL + per-form sink tables) and 010 (inventory/orphans/downgrade) + README

**Feature**: FEAT-649 — Audio Form Interaction Workflow
**Spec**: `sdd/specs/audio-form-interaction-workflow.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 12 / AC18. Spoken answers are persisted as a `VoiceEvidenceEnvelope`
(`{"answer": …, "blob_ref": …, …}`) inside `form_data.data[field_id]` and inside
per-form sink columns (FEAT-457 `postgres_table` persistence). Existing installs hold
**legacy voice answers as plain strings** (FEAT-488 `answer_envelope="voice"` fields that
were stored flat) and per-form sink columns typed `TEXT`. This task ships the standalone,
idempotent migration scripts that (a) normalise legacy strings to envelopes in
`form_data`, (b) add the `fd_unwrap_voice(jsonb)` SQL function and `form_data_scalar`
view, (c) convert envelope-capable per-form sink columns to `JSONB`, and (d) report the
envelope inventory and orphan `blob_ref`s with a reversible `--downgrade`.

These are **files only** — no test runs them against a shared database (spec §Worktree
Strategy: "migrations are files only, never executed by tests against a shared DB").

---

## Scope

- Create `009_voice_envelope_form_data.sql`: `CREATE OR REPLACE FUNCTION fd_unwrap_voice(jsonb) RETURNS jsonb`,
  `CREATE OR REPLACE VIEW form_data_scalar`, and an idempotent `UPDATE form_data` that rewrites legacy string
  values of `answer_envelope="voice"` fields to `{"answer": <s>, "blob_ref": null}`.
- Create `009_voice_envelope_sink_tables.py` (asyncpg CLI, `003_migrate_form_data.py` pattern): for every
  `form_schemas` row whose `schema_json.persistence.data.type == "postgres_table"`, `ALTER TABLE … ALTER COLUMN
  <col> TYPE JSONB USING jsonb_build_object('answer', <col>)` for each envelope-capable column still typed
  text; flags `--dsn --schema --batch-size --dry-run`.
- Create `010_voice_envelope_report.py`: `--dsn --schema --blob-url [--apply --downgrade]` — envelope
  inventory per form/field, orphan `blob_ref`s (blob missing in storage), and a reversible downgrade
  (envelope → `answer` scalar; JSONB → TEXT) that only writes with `--apply`.
- Append a "FEAT-649 — voice answer envelopes (009/010)" section to `migrations/README.md`
  (execution order, maintenance window, `--dry-run` first, downgrade).
- Write `test_voice_envelope_migrations.py`: SQL text checks + pure-function tests + stub-pool runs.

**NOT in scope**: sink DDL / mapper changes for new tables (TASK-4229); the envelope models and
`is_voice_envelope`/`unwrap_voice` helpers (TASK-4210); running any migration against a real DB;
CSV/GSheet sink sidecars (rejected by the owner).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/migrations/009_voice_envelope_form_data.sql` | CREATE | `fd_unwrap_voice`, `form_data_scalar`, idempotent legacy normalisation |
| `packages/parrot-formdesigner/migrations/009_voice_envelope_sink_tables.py` | CREATE | per-form sink column TEXT → JSONB (asyncpg CLI) |
| `packages/parrot-formdesigner/migrations/010_voice_envelope_report.py` | CREATE | inventory, orphan blob_refs, reversible downgrade |
| `packages/parrot-formdesigner/migrations/README.md` | MODIFY | new FEAT-649 section at the end |
| `packages/parrot-formdesigner/tests/formdesigner/test_voice_envelope_migrations.py` | CREATE | unit tests (no DB) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.services._identifiers import qualified_table, validate_identifier   # services/_identifiers.py:43, :23 (used by 003_migrate_form_data.py:40-43)
from parrot_formdesigner.core.schema import FormSchema                                        # core/schema.py:401
from parrot_formdesigner.core.types import FieldType                                          # core/types.py:16
from parrot_formdesigner.services.sinks.mapper import column_names_for, field_types_for       # services/sinks/mapper.py:234, :254
# optional — guarded exactly like 003_migrate_form_data.py:35-38
try:
    import asyncpg
except ImportError:
    asyncpg = None
```

Provided by dependency tasks: none (this task is standalone; it must NOT import `is_voice_envelope` /
`unwrap_voice` from TASK-4210 — re-implement the minimal shape check locally so the script runs on an
install that has not deployed FEAT-649 code yet).

### Existing Signatures to Use
```python
# packages/parrot-formdesigner/migrations/003_migrate_form_data.py  — the CLI pattern to copy
DEFAULT_BATCH_SIZE = 1000                                   # :45
@dataclass
class MigrationReport:  backfilled: int; orphaned: list[str]; dry_run: bool; def summary(self) -> str   # :48-74
async def backfill_form_uid(pool: asyncpg.Pool, *, schema: str, batch_size: int, dry_run: bool) -> MigrationReport   # :77
def _build_arg_parser() -> argparse.ArgumentParser          # :180 (--dsn required, --schema required, --batch-size, --dry-run)
async def _async_main(argv: list[str] | None = None) -> int # :209 (asyncpg None → exit 1; create_pool; finally pool.close())
def main(argv: list[str] | None = None) -> int              # :239 → asyncio.run(_async_main(argv))

# services/_identifiers.py
def validate_identifier(value: str, *, kind: str = "identifier") -> str   # :23 ; regex ^[A-Za-z_][A-Za-z0-9_]{0,62}$ :20
def qualified_table(schema: str, table: str) -> str                       # :43 → '"schema"."table"'

# core/persistence.py
class PostgresTableTarget(BaseModel):  type: Literal["postgres_table"]; connection: str; schema_name: str; table: str   # :80-97
class FormPersistenceConfig(BaseModel): data: SubmissionTarget; definition: DefinitionTarget | None    # :226-240

# core/schema.py
class FormField: answer_envelope: Literal["voice"] | None = None          # :143
class FormSchema: persistence: FormPersistenceConfig | None = None        # :473

# services/sinks/mapper.py
def column_names_for(form: FormSchema) -> list[str]                       # :234 (canonical per-form column traversal)
def field_types_for(form: FormSchema) -> dict[str, FieldType]             # :254

# services/submissions.py — generic table
DEFAULT_TABLE = "form_data"                                               # :32 ; data JSONB NOT NULL :194
# services/storage.py — form_schemas.schema_json JSONB                    # :167
```

Test pattern (verified): `packages/parrot-formdesigner/tests/unit/migrations/test_dedupe_field_ids.py:29-36`
loads a migration with `importlib.util.spec_from_file_location` (the `migrations/` dir is not a package)
and runs it against an in-memory asyncpg-like stub pool.

### Does NOT Exist
- ~~`009_*`, `010_*`~~ migration files; ~~`fd_unwrap_voice`~~; ~~`form_data_scalar`~~ — all created here.
- ~~`src/parrot_formdesigner/migrations/`~~ — migrations live at the package root `packages/parrot-formdesigner/migrations/`.
- ~~A migration framework / schema-version table~~ (README: "There is no migration framework").
- ~~`fakeredis`~~ / ~~a test Postgres~~ — tests must not require a database.
- ~~`asyncpg` in the test env guaranteed~~ — pure functions must be importable with `asyncpg = None`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/parrot-formdesigner/migrations/009_voice_envelope_form_data.sql", "action": "CREATE"},
    {"path": "packages/parrot-formdesigner/migrations/009_voice_envelope_sink_tables.py", "action": "CREATE"},
    {"path": "packages/parrot-formdesigner/migrations/010_voice_envelope_report.py", "action": "CREATE"},
    {"path": "packages/parrot-formdesigner/migrations/README.md", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/formdesigner/test_voice_envelope_migrations.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/_identifiers.py#qualified_table",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/_identifiers.py#validate_identifier",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/sinks/mapper.py#column_names_for",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/sinks/mapper.py#field_types_for",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py#FormSchema"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
Copy the structure of `migrations/003_migrate_form_data.py` verbatim: module docstring with
Prerequisites / Usage / Exit codes, `@dataclass` report with `summary()`, one `async def` doing the work
against an `asyncpg.Pool`, `_build_arg_parser()`, `_async_main()`, `main()`. `print()` is acceptable
**only** at the CLI boundary, exactly like 003 (these are operator scripts, not library code).

### Key Constraints
- **Idempotent**: every statement safe to re-run. SQL: `CREATE OR REPLACE`, and the `UPDATE` only touches
  values where `jsonb_typeof(value) = 'string'`. 009 sink script: skip columns whose
  `information_schema.columns.data_type` is already `jsonb`.
- **Identifier safety**: every schema/table/column name goes through `validate_identifier` /
  `qualified_table` before interpolation — never interpolate raw `schema_json` strings.
- **Envelope-capable column rule** (must match TASK-4229's DDL rule): a column is envelope-capable when its
  field has `answer_envelope == "voice"`, OR the form has an enabled `voice` block (`schema_json.voice.enabled`
  is not `false`) and the field type is not in `{hidden, file, image, image_dropzone, multi_upload, signature,
  signature_pad, credit_card, password, array}`. Read `schema_json` as a dict — do NOT require
  `FormSchema.voice` to exist (the script must also run before FEAT-649 code is deployed).
- `--downgrade` is destructive for evidence (drops `blob_ref`/confidence) — it requires `--apply` to write and
  prints the count of envelopes that would lose a `blob_ref`.
- No `requests`/`httpx`: orphan detection uses `--blob-url` only as a filesystem path / `file://` root in v1;
  any other scheme reports "orphan check skipped (unsupported blob url)" — FILL IN bounded below.

### References in Codebase
- `packages/parrot-formdesigner/migrations/003_migrate_form_data.py` — CLI + report pattern
- `packages/parrot-formdesigner/migrations/007_dedupe_duplicate_field_ids.py` — report-by-default + `--apply`
- `packages/parrot-formdesigner/tests/unit/migrations/test_dedupe_field_ids.py` — stub pool test pattern

---

## Implementation Blueprint

### Steps (in order)
1. Write the SQL file — *why*: `fd_unwrap_voice` and the view are needed by data operators regardless of sink usage.
2. Write `009_voice_envelope_sink_tables.py` with pure helpers (`envelope_columns(schema_json)`, `alter_sql(...)`) first — *why*: pure helpers are unit-testable without asyncpg.
3. Write `010_voice_envelope_report.py` — *why*: operators need an inventory before and a reversible path after 009.
4. Append the README section — *why*: operators run these manually, in order, per schema.
5. Write the tests (loader via `importlib`, stub pool) and run them.

### `packages/parrot-formdesigner/migrations/009_voice_envelope_form_data.sql` (CREATE)
```sql
-- Migration 009 (FEAT-649): voice answer envelopes in form_data.
-- Run once per physical schema:  psql "$DSN" -c "SET search_path TO navigator;" -f 009_voice_envelope_form_data.sql
-- Idempotent: CREATE OR REPLACE + string-only UPDATE guard.

CREATE OR REPLACE FUNCTION fd_unwrap_voice(doc jsonb) RETURNS jsonb
LANGUAGE sql IMMUTABLE AS $$
    SELECT COALESCE(
        jsonb_object_agg(
            kv.key,
            CASE
                WHEN jsonb_typeof(kv.value) = 'object'
                     AND kv.value ? 'answer'
                     AND (kv.value->>'source' = 'speech' OR kv.value ? 'blob_ref')
                THEN kv.value->'answer'
                ELSE kv.value
            END
        ),
        '{}'::jsonb
    )
    FROM jsonb_each(COALESCE(doc, '{}'::jsonb)) AS kv
$$;

CREATE OR REPLACE VIEW form_data_scalar AS
    SELECT fd.*, fd_unwrap_voice(fd.data) AS data_scalar
    FROM form_data AS fd;

-- Legacy normalisation: string values on answer_envelope="voice" fields → {"answer": s, "blob_ref": null}.
-- FILL IN: the UPDATE … FROM form_schemas JOIN that finds voice field_ids in schema_json (walk
--   sections[].fields[] and subsections' fields[]; GROUP children) and rewrites ONLY values where
--   jsonb_typeof(data->field_id) = 'string' — bounded by AC18 (idempotent, re-run is a no-op) and by
--   the join key form_data.form_uid = form_schemas.form_uid (001-004 already applied).
```
**Why this shape**: the function mirrors `is_voice_envelope()` (spec M1: `answer` key present and
`source == "speech"` or `blob_ref`) so SQL readers and Python readers agree; the view is additive and never
mutates data.

### `packages/parrot-formdesigner/migrations/009_voice_envelope_sink_tables.py` (CREATE)
```python
#!/usr/bin/env python3
"""Migration 009 (FEAT-649): per-form sink columns TEXT → JSONB for voice answer envelopes.

For every ``form_schemas`` row whose ``persistence.data.type == "postgres_table"``, converts each
envelope-capable column still typed text to ``JSONB USING jsonb_build_object('answer', col)``.

Idempotent: columns already typed ``jsonb`` are skipped. Run in a maintenance window, ``--dry-run`` first.

Usage:
    python migrations/009_voice_envelope_sink_tables.py --dsn postgresql://... \\
        --schema navigator [--batch-size 1000] [--dry-run]

Exit codes:
    0 - success (including a successful --dry-run)
    1 - connection or query failure
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass, field
from typing import Any

try:
    import asyncpg
except ImportError:  # pragma: no cover - exercised only when asyncpg is absent
    asyncpg = None  # type: ignore[assignment]

from parrot_formdesigner.services._identifiers import qualified_table, validate_identifier

DEFAULT_BATCH_SIZE = 1000
_NON_VOICE_TYPES = frozenset(
    {"hidden", "file", "image", "image_dropzone", "multi_upload", "signature", "signature_pad", "credit_card", "password", "array"}
)


@dataclass
class SinkMigrationReport:
    """Summary of a sink-table conversion run."""

    altered: list[str] = field(default_factory=list)   # "schema.table.column"
    skipped: list[str] = field(default_factory=list)   # already jsonb / missing column
    dry_run: bool = False

    def summary(self) -> str:
        """Return a human-readable summary."""
        # FILL IN: same shape as 003's MigrationReport.summary — bounded by the dataclass fields above.
        raise NotImplementedError


def envelope_columns(schema_json: dict[str, Any]) -> list[str]:
    """Return the envelope-capable column names of one form's ``schema_json`` (pure)."""
    # FILL IN: walk sections → fields/subsections (GROUP children flattened with "__" like
    #   services/sinks/mapper.py:_walk_tabular); apply the envelope-capable rule from Key Constraints
    #   — bounded by consistency with TASK-4229's _ddl_type_for(voice=True).
    raise NotImplementedError


def alter_sql(schema_name: str, table: str, column: str) -> str:
    """Return the ``ALTER COLUMN … TYPE JSONB`` statement for one column (identifiers validated)."""
    qt = qualified_table(schema_name, table)
    col = validate_identifier(column, kind="column")
    return f'ALTER TABLE {qt} ALTER COLUMN "{col}" TYPE JSONB USING jsonb_build_object(\'answer\', "{col}")'


async def migrate_sink_tables(pool: Any, *, schema: str, batch_size: int, dry_run: bool) -> SinkMigrationReport:
    """Convert envelope-capable sink columns for every postgres_table form in ``schema``."""
    report = SinkMigrationReport(dry_run=dry_run)
    # FILL IN: page form_schemas (keyset on id, batch_size) reading schema_json; for postgres_table targets
    #   query information_schema.columns for (schema_name, table); ALTER only text-typed envelope columns,
    #   one transaction per table — bounded by AC18 (idempotent, --dry-run writes nothing).
    return report


# FILL IN: _build_arg_parser / _async_main / main — copy 003_migrate_form_data.py:180-252 verbatim,
#   swapping backfill_form_uid → migrate_sink_tables and the description string.
```
**Why**: pure helpers (`envelope_columns`, `alter_sql`) carry the decisions and are unit-tested; the async
runner is thin. `jsonb_build_object('answer', col)` is the owner-decided conversion (spec §8).

### `packages/parrot-formdesigner/migrations/010_voice_envelope_report.py` (CREATE)
```python
#!/usr/bin/env python3
"""Migration 010 (FEAT-649): voice envelope inventory, orphan blob_refs, reversible downgrade.

Reports by default; writes only with ``--apply`` (``--downgrade --apply`` reverts envelopes to their
``answer`` scalar and JSONB sink columns back to TEXT).

Usage:
    python migrations/010_voice_envelope_report.py --dsn "$DSN" --schema navigator [--blob-url file:///var/blobs]
    python migrations/010_voice_envelope_report.py --dsn "$DSN" --schema navigator --downgrade --apply
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import asyncpg
except ImportError:  # pragma: no cover
    asyncpg = None  # type: ignore[assignment]

from parrot_formdesigner.services._identifiers import qualified_table, validate_identifier


def is_envelope(value: Any) -> bool:
    """Local mirror of core.voice_answer.is_voice_envelope (kept standalone on purpose)."""
    return isinstance(value, dict) and "answer" in value and (value.get("source") == "speech" or "blob_ref" in value)


@dataclass
class EnvelopeReport:
    """Inventory + orphan + downgrade summary."""

    envelopes_by_field: dict[str, int] = field(default_factory=dict)   # "form_uid/field_id" → count
    orphan_blob_refs: list[str] = field(default_factory=list)
    downgraded: int = 0
    lost_blob_refs: int = 0
    orphan_check: str = "skipped"
    applied: bool = False

    def summary(self) -> str:
        """Return a human-readable summary."""
        # FILL IN: list counts + orphans + downgrade numbers — bounded by AC18 ("reports envelopes and orphan blob_refs").
        raise NotImplementedError


def blob_exists(blob_url: str | None, blob_ref: str) -> bool | None:
    """True/False for a ``file://``/path root; None when the URL scheme is unsupported (check skipped)."""
    # FILL IN: resolve file:// or bare path roots with pathlib; any other scheme → None — bounded by
    #   "no requests/httpx" (codebase-conventions) and by the blob key layout {prefix}{form_uid}/{field_uid}/{blob_id}
    #   (services/blob_storage.py:241-242).
    raise NotImplementedError


async def run_report(pool: Any, *, schema: str, blob_url: str | None, downgrade: bool, apply: bool) -> EnvelopeReport:
    """Scan form_data.data for envelopes; optionally downgrade (only when apply=True)."""
    # FILL IN: scan with keyset pagination; downgrade data[field] := data->field->'answer' for envelopes and
    #   ALTER sink JSONB voice columns back to TEXT USING (col->>'answer') — bounded by --apply gating.
    raise NotImplementedError
```
**Why**: 010 is the safety net for 009 (reversibility, AC18); it never writes without `--apply`, matching
007's report-by-default posture.

### `packages/parrot-formdesigner/migrations/README.md` (MODIFY)
```markdown
# occurrences: 1 (verified: grep -c '# parrot-formdesigner migrations (FEAT-389)' packages/parrot-formdesigner/migrations/README.md)
# APPEND at end of file (after the "## Orphans" section, last line verified: README.md:152)

## FEAT-649 — voice answer envelopes (009 / 010)

Spoken answers are stored as `{"answer": …, "blob_ref": …, "source": "speech", …}` envelopes.
Run per physical schema, in a maintenance window, AFTER deploying FEAT-649:

1. `010_voice_envelope_report.py --dsn "$DSN" --schema navigator` — inventory before.
2. `psql "$DSN" -c "SET search_path TO navigator;" -f 009_voice_envelope_form_data.sql`
3. `009_voice_envelope_sink_tables.py --dsn "$DSN" --schema navigator --dry-run`, then without `--dry-run`.
4. `010_voice_envelope_report.py … --blob-url file:///…` — inventory + orphan blob_refs after.

Rollback: `010_voice_envelope_report.py … --downgrade --apply` (drops envelope evidence; prints how many
`blob_ref`s are lost). CSV / Google Sheets sinks receive the envelope as a JSON string (like ARRAY today).
```

### FILL IN checklist
- [ ] `009_voice_envelope_form_data.sql` — legacy-normalisation UPDATE; bounded by AC18 idempotency + form_uid join.
- [ ] `009_voice_envelope_sink_tables.py::SinkMigrationReport.summary` — 003 shape.
- [ ] `009_voice_envelope_sink_tables.py::envelope_columns` — rule shared with TASK-4229.
- [ ] `009_voice_envelope_sink_tables.py::migrate_sink_tables` — keyset paging, skip jsonb columns, dry-run.
- [ ] `009_voice_envelope_sink_tables.py` CLI — copy of 003 `:180-252`.
- [ ] `010_voice_envelope_report.py::EnvelopeReport.summary`, `blob_exists`, `run_report`, CLI (`--dsn --schema --blob-url --apply --downgrade`).

---

## Acceptance Criteria

- [ ] AC18 (files): 009 SQL defines `fd_unwrap_voice` and `form_data_scalar`; its UPDATE only touches string values (idempotent).
- [ ] AC18: `009_voice_envelope_sink_tables.py` supports `--dry-run`, skips already-`jsonb` columns, validates every identifier.
- [ ] AC18: `010_voice_envelope_report.py` reports envelopes and orphan `blob_ref`s and supports `--downgrade` (writes only with `--apply`).
- [ ] README documents order, maintenance window, dry-run and rollback.
- [ ] No DB needed for tests; scripts import cleanly with `asyncpg` absent.
- [ ] `ruff check packages/parrot-formdesigner/migrations/009_voice_envelope_sink_tables.py packages/parrot-formdesigner/migrations/010_voice_envelope_report.py` passes.

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/formdesigner/test_voice_envelope_migrations.py -q`

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/formdesigner/test_voice_envelope_migrations.py
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

MIGRATIONS_DIR = Path(__file__).parents[2] / "migrations"


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, MIGRATIONS_DIR / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def m009():
    return _load("voice_envelope_sink_009", "009_voice_envelope_sink_tables.py")


@pytest.fixture(scope="module")
def m010():
    return _load("voice_envelope_report_010", "010_voice_envelope_report.py")


def test_migration_009_sql_defines_function_view_and_guarded_update():
    sql = (MIGRATIONS_DIR / "009_voice_envelope_form_data.sql").read_text()
    assert "CREATE OR REPLACE FUNCTION fd_unwrap_voice" in sql
    assert "CREATE OR REPLACE VIEW form_data_scalar" in sql
    assert re.search(r"jsonb_typeof\([^)]*\)\s*=\s*'string'", sql)   # idempotency guard


def test_envelope_columns_voice_and_voice_block(m009): ...      # answer_envelope="voice" column; voice.enabled form; excluded types absent


def test_alter_sql_rejects_bad_identifiers(m009):
    with pytest.raises(ValueError):
        m009.alter_sql("navigator", "t; DROP", "c")


async def test_sink_migration_dry_run_writes_nothing(m009): ...  # stub pool records execute() calls; dry_run → no ALTER


async def test_sink_migration_skips_jsonb_columns(m009): ...    # information_schema stub says jsonb → skipped, not altered


def test_report_is_envelope_shape(m010):
    assert m010.is_envelope({"answer": "x", "blob_ref": None})
    assert not m010.is_envelope({"answer": "x"})
    assert not m010.is_envelope("x")


async def test_downgrade_requires_apply(m010): ...              # downgrade=True, apply=False → downgraded counted, no UPDATE executed
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug audio-form-interaction-workflow --feature-id FEAT-649`)
2. **Read the spec** at the path listed above for full context (§3 Module 12, §5 AC18, §7 Known Risks "Migration 009").
3. **Check dependencies** — none.
4. **Verify the Codebase Contract** — before writing ANY code; update it first if anything moved.
5. **Update status** in `sdd/tasks/index/audio-form-interaction-workflow.json` → `"in-progress"` (set `started_at`) and commit only that index file.
6. **Implement** — start from the Implementation Blueprint blocks, complete every `# FILL IN:` marker, never change a signature or path the blueprint fixes.
7. **Verify** all acceptance criteria — run the Validation Commands with `PYTHONPATH=packages/parrot-formdesigner/src`.
8. **Commit the code** — stage only the files this task lists.
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4230 audio-form-interaction-workflow verified`.
10. **Fill in the Completion Note** below, then commit the staged SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
