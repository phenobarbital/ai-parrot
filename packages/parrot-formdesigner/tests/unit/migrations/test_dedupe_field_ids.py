"""Unit tests for migration 007 (duplicate `field_id` repair).

`packages/parrot-formdesigner/migrations/` is a plain directory of SQL +
standalone Python scripts — NOT a Python package — so
`007_dedupe_duplicate_field_ids.py` is loaded via
`importlib.util.spec_from_file_location`, mirroring
`test_feat393_migrations.py`'s pattern for 006.

No real PostgreSQL is required: `repair_duplicate_field_ids()` runs against
an in-memory asyncpg-like stub pool, and the document-level functions are
pure and tested directly.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from parrot_formdesigner.core.schema import FormSchema

MIGRATIONS_DIR = Path(__file__).parents[3] / "migrations"


def _load_migration_007():
    """Load 007_dedupe_duplicate_field_ids.py as a module via its file path."""
    module_path = MIGRATIONS_DIR / "007_dedupe_duplicate_field_ids.py"
    spec = importlib.util.spec_from_file_location("dedupe_field_ids_007", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["dedupe_field_ids_007"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def migration_007():
    return _load_migration_007()


def _field(field_id: str, **extra) -> dict:
    return {"field_id": field_id, "field_type": "text", "label": field_id, **extra}


@pytest.fixture
def cross_section_duplicate_json() -> dict:
    """The production shape: one column repeated across two SECTIONS.

    This is `db-form-10-69` (Epson Visit Form), where the networkninja
    source repeats help-note columns 8984/8985/8986 as a header in blocks
    27 and 28 — one block per FormSection. Legal before TASK-1996, because
    the only uniqueness check then was per-section and on the edit path
    (`api/operations.py::_check_unique_field_id`).
    """
    return {
        "form_id": "db-form-10-69",
        "title": "Epson Visit Form",
        "sections": [
            {"section_id": "section_27", "fields": [_field("field_8984"), _field("field_9050")]},
            {"section_id": "section_28", "fields": [_field("field_8984"), _field("field_9100")]},
        ],
    }


# ---------------------------------------------------------------------------
# walk_field_dicts() — must agree with core.schema.walk_fields()
# ---------------------------------------------------------------------------


def test_walk_field_dicts_matches_the_model_traversal_order(migration_007) -> None:
    """Raw-JSON traversal order must equal the model's `walk_fields()`.

    If the two disagreed, 007 would rename a different occurrence than the
    one `_validate_unique_identity` counted as the duplicate.
    """
    doc = {
        "form_id": "nested",
        "title": "Nested",
        "sections": [
            {
                "section_id": "s1",
                "fields": [
                    _field("group", field_type="group", children=[_field("child_a"), _field("child_b")]),
                    {"subsection_id": "sub1", "title": "Sub", "fields": [_field("in_sub")]},
                    _field("arr", field_type="array", item_template=_field("tmpl")),
                ],
            }
        ],
    }
    raw_order = [f["field_id"] for s in doc["sections"] for f in migration_007.walk_field_dicts(s["fields"])]
    model_order = [f.field_id for f in FormSchema.model_validate(doc).iter_fields_recursive()]

    assert raw_order == model_order


# ---------------------------------------------------------------------------
# dedupe_field_ids()
# ---------------------------------------------------------------------------


def test_first_occurrence_keeps_its_field_id(migration_007, cross_section_duplicate_json: dict) -> None:
    renames = migration_007.dedupe_field_ids(cross_section_duplicate_json)

    assert renames == [("field_8984", "field_8984__2")]
    first, second = cross_section_duplicate_json["sections"]
    assert [f["field_id"] for f in first["fields"]] == ["field_8984", "field_9050"]
    assert [f["field_id"] for f in second["fields"]] == ["field_8984__2", "field_9100"]


def test_three_way_duplicate_numbers_sequentially(migration_007) -> None:
    doc = {
        "form_id": "f",
        "title": "F",
        "sections": [{"section_id": "s", "fields": [_field("dup"), _field("dup"), _field("dup")]}],
    }
    renames = migration_007.dedupe_field_ids(doc)

    assert renames == [("dup", "dup__2"), ("dup", "dup__3")]
    assert [f["field_id"] for f in doc["sections"][0]["fields"]] == ["dup", "dup__2", "dup__3"]


def test_rename_never_collides_with_an_existing_field_id(migration_007) -> None:
    """A `dup__2` already in the document must not be overwritten.

    Guards re-running the migration and hand-authored forms alike: the
    suffix search skips every name already present anywhere in the tree,
    not just the ones seen so far in traversal order.
    """
    doc = {
        "form_id": "f",
        "title": "F",
        "sections": [{"section_id": "s", "fields": [_field("dup"), _field("dup"), _field("dup__2")]}],
    }
    renames = migration_007.dedupe_field_ids(doc)

    assert renames == [("dup", "dup__3")]
    assert [f["field_id"] for f in doc["sections"][0]["fields"]] == ["dup", "dup__3", "dup__2"]


def test_rename_never_collides_with_a_metadata_key(migration_007) -> None:
    """`_validate_metadata` rejects a metadata key equal to a `field_id`.

    Renaming onto one would convert a repairable row into an unrepairable
    one, so metadata keys are reserved alongside the tree's field_ids.
    """
    doc = {
        "form_id": "f",
        "title": "F",
        "sections": [{"section_id": "s", "fields": [_field("dup"), _field("dup")]}],
        "metadata": [{"key": "dup__2", "source": "constant"}],
    }
    renames = migration_007.dedupe_field_ids(doc)

    assert renames == [("dup", "dup__3")]
    FormSchema.model_validate(doc)


def test_duplicates_nested_in_group_children_are_renamed(migration_007) -> None:
    """The validator walks GROUP children, so the repair must too."""
    doc = {
        "form_id": "f",
        "title": "F",
        "sections": [
            {
                "section_id": "s",
                "fields": [
                    _field("dup"),
                    _field("g", field_type="group", children=[_field("dup")]),
                ],
            }
        ],
    }
    renames = migration_007.dedupe_field_ids(doc)

    assert renames == [("dup", "dup__2")]
    assert doc["sections"][0]["fields"][1]["children"][0]["field_id"] == "dup__2"
    FormSchema.model_validate(doc)


def test_a_clean_document_is_left_untouched(migration_007) -> None:
    doc = {
        "form_id": "f",
        "title": "F",
        "sections": [{"section_id": "s", "fields": [_field("a"), _field("b")]}],
    }
    before = json.dumps(doc, sort_keys=True)

    assert migration_007.dedupe_field_ids(doc) == []
    assert json.dumps(doc, sort_keys=True) == before


# ---------------------------------------------------------------------------
# repair_schema_document()
# ---------------------------------------------------------------------------


def test_repair_makes_the_document_loadable(migration_007, cross_section_duplicate_json: dict) -> None:
    """The whole point: after repair, `FormSchema.model_validate` succeeds."""
    with pytest.raises(Exception, match="Duplicate field_id"):
        FormSchema.model_validate(cross_section_duplicate_json)

    result = migration_007.repair_schema_document(cross_section_duplicate_json)

    assert result.skipped_reason is None
    assert result.repaired_json is not None
    FormSchema.model_validate(result.repaired_json)


def test_repair_persists_element_uids(migration_007, cross_section_duplicate_json: dict) -> None:
    """006 never reached this row, so 007 must finish its UID backfill.

    Without persisted UIDs the model re-mints them from
    `default_factory=uuid.uuid4` on every load, which destabilizes blob
    object keys (`{form_uid}/{field_uid}/{blob_id}`) and partial-save keys.
    """
    repaired = migration_007.repair_schema_document(cross_section_duplicate_json).repaired_json

    for section in repaired["sections"]:
        assert "section_uid" in section
        for field_dict in section["fields"]:
            assert "field_uid" in field_dict

    first = [f.field_uid for f in FormSchema.model_validate(repaired).iter_fields_recursive()]
    second = [f.field_uid for f in FormSchema.model_validate(repaired).iter_fields_recursive()]
    assert first == second, "UIDs must now be stable across loads"


def test_repair_does_not_mutate_its_input(migration_007, cross_section_duplicate_json: dict) -> None:
    before = json.dumps(cross_section_duplicate_json, sort_keys=True)
    migration_007.repair_schema_document(cross_section_duplicate_json)
    assert json.dumps(cross_section_duplicate_json, sort_keys=True) == before


def test_rule_references_still_resolve_to_the_first_occurrence(migration_007) -> None:
    """A rule authored against the duplicated name must not be re-pointed.

    Before the repair every lookup was first-match, so the condition
    addressed the FIRST occurrence. That one keeps its `field_id`, so the
    resolved `field_uid` must be the first occurrence's.
    """
    doc = {
        "form_id": "f",
        "title": "F",
        "sections": [
            {
                "section_id": "s1",
                "fields": [
                    _field("country"),
                    _field(
                        "state",
                        depends_on={
                            "conditions": [{"field_id": "country", "operator": "eq", "value": "US"}],
                            "logic": "and",
                            "effect": "show",
                        },
                    ),
                ],
            },
            {"section_id": "s2", "fields": [_field("country")]},
        ],
    }
    repaired = migration_007.repair_schema_document(doc).repaired_json
    form = FormSchema.model_validate(repaired)

    by_id = {f.field_id: f for f in form.iter_fields_recursive()}
    assert set(by_id) == {"country", "country__2", "state"}
    condition = by_id["state"].depends_on.conditions[0]
    assert condition.field_uid == by_id["country"].field_uid


def test_an_already_valid_document_is_skipped(migration_007, legacy_schema_json: dict) -> None:
    """Rows 006 already migrated (and re-runs of 007) must not be rewritten."""
    result = migration_007.repair_schema_document(legacy_schema_json)

    assert result.skipped_reason == "already_valid"
    assert result.repaired_json is None


def test_repair_is_idempotent(migration_007, cross_section_duplicate_json: dict) -> None:
    once = migration_007.repair_schema_document(cross_section_duplicate_json).repaired_json
    twice = migration_007.repair_schema_document(once)

    assert twice.skipped_reason == "already_valid"
    assert twice.repaired_json is None


def test_a_document_failing_for_another_reason_is_never_written(migration_007) -> None:
    """Deduplication is not a licence to write back anything that parses.

    A duplicate client-supplied `field_uid` is a different defect; 007 does
    not touch UIDs, so the row must be reported, not rewritten.
    """
    shared_uid = "11111111-1111-4111-8111-111111111111"
    doc = {
        "form_id": "f",
        "title": "F",
        "sections": [
            {
                "section_id": "s",
                "fields": [_field("a", field_uid=shared_uid), _field("b", field_uid=shared_uid)],
            }
        ],
    }
    result = migration_007.repair_schema_document(doc)

    assert result.repaired_json is None
    assert result.skipped_reason is not None
    assert result.skipped_reason.startswith("unrepairable:")
    assert "Duplicate field_uid" in result.skipped_reason


# ---------------------------------------------------------------------------
# repair_duplicate_field_ids() — DB-backed (stub pool)
# ---------------------------------------------------------------------------


class _StubConn:
    """asyncpg connection stub modelling `form_schemas` keyset pagination.

    `fetch()` re-evaluates the `id > $last_id` cursor on every call and rows
    are keyed by `row["id"]`, so the cursor advances whether a row was
    repaired, skipped or unchanged — the same infinite-loop guard 006's and
    003's suites rely on.
    """

    def __init__(self, form_schemas_rows=None) -> None:
        self._schemas: dict[str, dict] = dict(form_schemas_rows or {})
        self.executed: list[tuple[str, tuple]] = []

    async def fetch(self, sql: str, *args):
        if len(args) == 1:
            (limit,) = args
            last_id = None
        else:
            last_id, limit = args
        candidates = sorted(row_id for row_id in self._schemas if last_id is None or row_id > last_id)
        return [{"id": row_id, "schema_json": self._schemas[row_id]} for row_id in candidates[:limit]]

    async def execute(self, sql: str, schema_json: str, row_id: str) -> str:
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
async def test_runner_repairs_and_writes_back(migration_007, cross_section_duplicate_json: dict) -> None:
    conn = _StubConn(form_schemas_rows={"row-1": cross_section_duplicate_json})
    report = await migration_007.repair_duplicate_field_ids(_StubPool(conn), schema="navigator")

    assert report.repaired == 1
    assert report.renames["row-1"] == [("field_8984", "field_8984__2")]
    assert len(conn.executed) == 1
    FormSchema.model_validate(conn._schemas["row-1"])


@pytest.mark.asyncio
async def test_runner_dry_run_writes_nothing(migration_007, cross_section_duplicate_json: dict) -> None:
    conn = _StubConn(form_schemas_rows={"row-1": cross_section_duplicate_json})
    report = await migration_007.repair_duplicate_field_ids(_StubPool(conn), schema="navigator", dry_run=True)

    assert report.repaired == 1
    assert report.dry_run is True
    assert conn.executed == []
    assert conn._schemas["row-1"] == cross_section_duplicate_json


@pytest.mark.asyncio
async def test_runner_leaves_healthy_rows_alone(
    migration_007, legacy_schema_json: dict, cross_section_duplicate_json: dict
) -> None:
    conn = _StubConn(form_schemas_rows={"row-1": legacy_schema_json, "row-2": cross_section_duplicate_json})
    report = await migration_007.repair_duplicate_field_ids(_StubPool(conn), schema="navigator")

    assert report.repaired == 1
    assert report.already_valid == 1
    assert [row_id for _, (_, row_id) in conn.executed] == ["row-2"]


@pytest.mark.asyncio
async def test_runner_accepts_string_encoded_jsonb(migration_007, cross_section_duplicate_json: dict) -> None:
    """`schema_json` arrives as `str` on a plain pool, `dict` on a JSONB codec."""
    conn = _StubConn(form_schemas_rows={"row-1": json.dumps(cross_section_duplicate_json)})
    report = await migration_007.repair_duplicate_field_ids(_StubPool(conn), schema="navigator")

    assert report.repaired == 1


@pytest.mark.asyncio
async def test_runner_paginates_past_skipped_rows(migration_007, legacy_schema_json: dict) -> None:
    """Rows that are never written must still advance the keyset cursor."""
    conn = _StubConn(form_schemas_rows={f"row-{i}": dict(legacy_schema_json) for i in range(5)})
    report = await migration_007.repair_duplicate_field_ids(_StubPool(conn), schema="navigator", batch_size=2)

    assert report.already_valid == 5
    assert conn.executed == []


@pytest.mark.asyncio
async def test_runner_rejects_an_invalid_schema_name(migration_007) -> None:
    with pytest.raises(ValueError):
        await migration_007.repair_duplicate_field_ids(_StubPool(_StubConn()), schema="bad-schema; DROP TABLE x")
