"""Unit tests for the FEAT-393 (Module 14, TASK-2008) migration artifacts.

`packages/parrot-formdesigner/migrations/` is a plain directory of SQL +
standalone Python scripts — NOT a Python package — so
`006_backfill_element_uids.py` is loaded via
`importlib.util.spec_from_file_location`, mirroring
`tests/unit/test_migrations_form_uid.py`'s pattern for FEAT-389's
`003_migrate_form_data.py`.

No real PostgreSQL is required — `backfill_element_uids()` and
`scan_legacy_blob_refs()` are exercised against in-memory asyncpg-like
stub pools; `migrate_schema_document()` and the blob-ref helpers are pure
functions tested directly.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

MIGRATIONS_DIR = Path(__file__).parents[3] / "migrations"


def _load_migration_006():
    """Load 006_backfill_element_uids.py as a module via its file path."""
    module_path = MIGRATIONS_DIR / "006_backfill_element_uids.py"
    spec = importlib.util.spec_from_file_location("migrate_element_uids_006", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["migrate_element_uids_006"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def migration_006():
    return _load_migration_006()


# ---------------------------------------------------------------------------
# Fixtures — raw (pre-migration) schema_json documents
# ---------------------------------------------------------------------------


@pytest.fixture
def legacy_schema_json() -> dict:
    """A pre-FEAT-393 document: no *_uid keys anywhere, and a rule
    reference authored by field_id (depends_on)."""
    return {
        "form_id": "legacy-form",
        "title": "Legacy Form",
        "sections": [
            {
                "section_id": "s1",
                "fields": [
                    {
                        "field_id": "country",
                        "field_type": "select",
                        "label": "Country",
                    },
                    {
                        "field_id": "state",
                        "field_type": "text",
                        "label": "State",
                        "depends_on": {
                            "conditions": [
                                {
                                    "field_id": "country",
                                    "operator": "eq",
                                    "value": "US",
                                }
                            ],
                            "logic": "and",
                            "effect": "show",
                        },
                    },
                ],
            }
        ],
    }


@pytest.fixture
def migrated_schema_json(migration_006, legacy_schema_json: dict) -> dict:
    """A document that has already been through migrate_schema_document()."""
    result = migration_006.migrate_schema_document(legacy_schema_json)
    assert result.migrated_json is not None
    return result.migrated_json


@pytest.fixture
def duplicate_field_id_json() -> dict:
    """A document with the same field_id repeated across the form — must
    be rejected by FormSchema._validate_unique_identity (FEAT-393, Module 2)
    and therefore skipped by the migration (never written)."""
    return {
        "form_id": "dup-form",
        "title": "Duplicate Form",
        "sections": [
            {
                "section_id": "s1",
                "fields": [
                    {"field_id": "q1", "field_type": "text", "label": "Q1"},
                    {"field_id": "q1", "field_type": "text", "label": "Q1 again"},
                ],
            }
        ],
    }


# ---------------------------------------------------------------------------
# 004_form_uid_uuid_type.sql / 005_question_bank_question_id.sql — content
# ---------------------------------------------------------------------------


def test_migrations_directory_exists() -> None:
    assert MIGRATIONS_DIR.is_dir()


def test_004_form_uid_uuid_type_sql_is_idempotent_and_scoped() -> None:
    sql = (MIGRATIONS_DIR / "004_form_uid_uuid_type.sql").read_text()
    assert "form_schemas" in sql and "form_data" in sql
    assert "ALTER COLUMN form_uid TYPE UUID USING form_uid::uuid" in sql
    # Guarded on current data_type, scoped to the CURRENT schema (same
    # cross-schema bug class as FEAT-389's 001 — see its own regression
    # test) so re-running is a no-op and one tenant's already-migrated
    # table never masks another's.
    assert sql.count("data_type <> 'uuid'") == 2
    assert sql.count("table_schema = current_schema()") == 2


def test_005_question_bank_question_id_sql_is_idempotent() -> None:
    sql = (MIGRATIONS_DIR / "005_question_bank_question_id.sql").read_text()
    assert "ALTER TABLE field_bank RENAME COLUMN field_id TO question_id" in sql
    assert "RENAME CONSTRAINT field_bank_field_id_tenant_key TO field_bank_question_id_tenant_key" in sql
    # Guarded: only rename the column if the OLD name exists AND the NEW
    # one doesn't (safe against a partial/interrupted prior run).
    assert "column_name = 'field_id'" in sql
    assert "column_name = 'question_id'" in sql
    assert "pg_constraint" in sql


def test_006_backfill_element_uids_exists(migration_006) -> None:
    assert migration_006 is not None


# ---------------------------------------------------------------------------
# migrate_schema_document() — pure, in-memory document migration
# ---------------------------------------------------------------------------


def test_backfill_injects_all_uid_levels(migration_006, legacy_schema_json: dict) -> None:
    """Every tree level (section, field) gets a freshly-minted UID."""
    result = migration_006.migrate_schema_document(legacy_schema_json)

    assert result.skipped_reason is None
    assert result.changed is True

    section = result.migrated_json["sections"][0]
    assert section.get("section_uid")

    fields_by_id = {f["field_id"]: f for f in section["fields"]}
    for field_id, field_doc in fields_by_id.items():
        assert field_doc.get("field_uid"), field_id


def test_backfill_rewrites_rule_refs(migration_006, legacy_schema_json: dict) -> None:
    """The depends_on condition's authored field_id is resolved to the
    referenced field's field_uid."""
    result = migration_006.migrate_schema_document(legacy_schema_json)

    fields_by_id = {
        f["field_id"]: f for f in result.migrated_json["sections"][0]["fields"]
    }
    country_uid = fields_by_id["country"]["field_uid"]
    state_condition = fields_by_id["state"]["depends_on"]["conditions"][0]

    assert state_condition["field_id"] == "country"  # informational, untouched
    assert state_condition["field_uid"] == country_uid


def test_backfill_idempotent(migration_006, migrated_schema_json: dict) -> None:
    """Re-migrating an already-migrated document produces byte-identical
    output — no field is re-minted, no rule reference is re-written."""
    result = migration_006.migrate_schema_document(migrated_schema_json)

    assert result.skipped_reason is None
    assert result.changed is False
    assert result.migrated_json == migrated_schema_json


def test_backfill_skips_and_reports_duplicates(
    migration_006, duplicate_field_id_json: dict
) -> None:
    """A duplicate field_id anywhere in the form is skipped and reported —
    the document is never migrated or written."""
    result = migration_006.migrate_schema_document(duplicate_field_id_json)

    assert result.migrated_json is None
    assert result.skipped_reason == "duplicate_field_id"
    assert result.duplicate_field_ids == ["q1"]


# ---------------------------------------------------------------------------
# Legacy blob_ref detection (report only — never rewritten)
# ---------------------------------------------------------------------------


def test_report_lists_legacy_blob_refs(migration_006) -> None:
    """Legacy-pattern blob refs ({form_id}/{field_id}/{blob_id}) are found;
    new-pattern refs ({form_uid}/{field_uid}/{blob_id}) are not."""
    submission_data = {
        "photo": "s3://bucket/my-form/photo/abc123",
        "nested": {
            "doc": "gs://bucket/other-form/upload/xyz789",
        },
        "signed_uid": (
            "s3://bucket/550e8400-e29b-41d4-a716-446655440000/"
            "6ba7b810-9dad-11d1-80b4-00c04fd430c8/abc123"
        ),
        "not_a_ref": "just a normal string value",
    }

    found = migration_006.find_legacy_blob_refs(submission_data)

    assert "s3://bucket/my-form/photo/abc123" in found
    assert "gs://bucket/other-form/upload/xyz789" in found
    assert not any("550e8400" in ref for ref in found)
    assert len(found) == 2


def test_is_legacy_blob_ref_new_pattern_not_legacy(migration_006) -> None:
    new_ref = (
        "file://550e8400-e29b-41d4-a716-446655440000/"
        "6ba7b810-9dad-11d1-80b4-00c04fd430c8/blob-id"
    )
    assert migration_006.is_legacy_blob_ref(new_ref) is False


def test_is_legacy_blob_ref_ignores_non_blob_strings(migration_006) -> None:
    assert migration_006.is_legacy_blob_ref("hello world") is False


# ---------------------------------------------------------------------------
# backfill_element_uids() / scan_legacy_blob_refs() — DB-backed (stub pool)
# ---------------------------------------------------------------------------


class _StubConn:
    """asyncpg connection stub for both batched queries in 006.

    Models real Postgres semantics closely enough to avoid the class of
    infinite-loop bug FEAT-389's 003 test suite specifically guards
    against: `fetch()` re-evaluates the keyset cursor (`id > $last_id`) on
    every call, and rows are keyed by `row["id"]` — the cursor always
    advances regardless of whether a row was migrated, skipped, or
    unchanged.
    """

    def __init__(self, form_schemas_rows=None, form_data_rows=None) -> None:
        # id -> schema_json dict
        self._schemas: dict[str, dict] = dict(form_schemas_rows or {})
        # id -> data dict
        self._data: dict[str, dict] = dict(form_data_rows or {})
        self.executed: list[tuple[str, tuple]] = []

    async def fetch(self, sql: str, *args):
        if len(args) == 1:
            (limit,) = args
            last_id = None
        else:
            last_id, limit = args

        if "form_data" in sql:
            source = self._data
            value_key = "data"
        else:
            source = self._schemas
            value_key = "schema_json"

        candidates = sorted(
            row_id for row_id in source if last_id is None or row_id > last_id
        )
        page = candidates[:limit]
        return [{"id": row_id, value_key: source[row_id]} for row_id in page]

    async def execute(self, sql: str, schema_json: str, row_id: str) -> str:
        import json

        self.executed.append((sql, (schema_json, row_id)))
        self._schemas[row_id] = json.loads(schema_json)
        return "UPDATE 1"


class _StubPool:
    def __init__(self, conn: _StubConn) -> None:
        self._conn = conn

    def acquire(self):
        conn = self._conn

        class _Ctx:
            async def __aenter__(self_inner):
                return conn

            async def __aexit__(self_inner, *args):
                return False

        return _Ctx()


@pytest.mark.asyncio
async def test_backfill_element_uids_migrates_and_writes_back(
    migration_006, legacy_schema_json: dict
) -> None:
    conn = _StubConn(form_schemas_rows={"row-1": legacy_schema_json})
    pool = _StubPool(conn)

    report = await migration_006.backfill_element_uids(pool, schema="navigator")

    assert report.migrated == 1
    assert report.skipped_duplicates == {}
    assert len(conn.executed) == 1
    assert "field_uid" in conn._schemas["row-1"]["sections"][0]["fields"][0]


@pytest.mark.asyncio
async def test_backfill_element_uids_dry_run_writes_nothing(
    migration_006, legacy_schema_json: dict
) -> None:
    conn = _StubConn(form_schemas_rows={"row-1": legacy_schema_json})
    pool = _StubPool(conn)

    report = await migration_006.backfill_element_uids(
        pool, schema="navigator", dry_run=True
    )

    assert report.migrated == 1
    assert report.dry_run is True
    assert conn.executed == []


@pytest.mark.asyncio
async def test_backfill_element_uids_reports_duplicates_and_skips_write(
    migration_006, duplicate_field_id_json: dict
) -> None:
    conn = _StubConn(form_schemas_rows={"row-dup": duplicate_field_id_json})
    pool = _StubPool(conn)

    report = await migration_006.backfill_element_uids(pool, schema="navigator")

    assert report.migrated == 0
    assert report.skipped_duplicates == {"row-dup": ["q1"]}
    assert conn.executed == []


@pytest.mark.asyncio
async def test_backfill_element_uids_already_migrated_is_noop(
    migration_006, migrated_schema_json: dict
) -> None:
    """An already-migrated row produces zero writes (idempotent DB flow)."""
    conn = _StubConn(form_schemas_rows={"row-1": migrated_schema_json})
    pool = _StubPool(conn)

    report = await migration_006.backfill_element_uids(pool, schema="navigator")

    assert report.migrated == 0
    assert conn.executed == []


@pytest.mark.asyncio
async def test_scan_legacy_blob_refs_finds_legacy_pattern(migration_006) -> None:
    conn = _StubConn(
        form_data_rows={
            "sub-1": {"photo": "s3://bucket/my-form/photo/abc123"},
            "sub-2": {
                "doc": (
                    "s3://bucket/550e8400-e29b-41d4-a716-446655440000/"
                    "6ba7b810-9dad-11d1-80b4-00c04fd430c8/abc123"
                )
            },
        }
    )
    pool = _StubPool(conn)

    refs = await migration_006.scan_legacy_blob_refs(pool, schema="navigator")

    assert refs == ["s3://bucket/my-form/photo/abc123"]


def test_migration_report_summary_lists_skipped_and_blob_refs(migration_006) -> None:
    report = migration_006.BackfillReport(
        migrated=2,
        skipped_duplicates={"row-1": ["q1"]},
        legacy_blob_refs=["s3://bucket/my-form/photo/abc123"],
    )
    text = report.summary()
    assert "Migrated: 2" in text
    assert "row-1" in text and "q1" in text
    assert "s3://bucket/my-form/photo/abc123" in text


def test_arg_parser_requires_dsn_and_schema(migration_006) -> None:
    parser = migration_006._build_arg_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([])


@pytest.mark.asyncio
async def test_main_handles_unreachable_dsn_gracefully(migration_006) -> None:
    """main() with an unparsable DSN exits 1 instead of raising/hanging."""
    exit_code = await migration_006._async_main(
        ["--dsn", "not-a-valid-dsn", "--schema", "navigator", "--dry-run"]
    )
    assert exit_code == 1
