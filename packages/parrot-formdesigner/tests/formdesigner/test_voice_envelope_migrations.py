"""Unit tests for migrations 009 (SQL + sink tables) and 010 (report/downgrade). No database."""

from __future__ import annotations

import importlib.util
import json
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


class _Tx:
    entered = 0

    async def __aenter__(self):
        type(self).entered += 1
        return self

    async def __aexit__(self, *exc):
        return False


class _Conn:
    def __init__(self, forms, col_types, data_rows=()):
        self.forms, self.col_types, self.data_rows = forms, col_types, list(data_rows)
        self.executed: list[tuple] = []

    async def fetch(self, sql: str, *args):
        if "information_schema" in sql:
            return [{"column_name": c, "data_type": t} for c, t in self.col_types.items()]
        if "form_schemas" in sql:
            last = args[0] if "id >" in sql else -1
            return [r for r in self.forms if r["id"] > last]
        if "form_data" in sql:
            last = args[0] if "id >" in sql else -1
            return [r for r in self.data_rows if r["id"] > last]
        return []

    async def execute(self, sql: str, *args):
        self.executed.append((sql, args))

    def transaction(self):
        return _Tx()


class _Pool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        conn = self.conn

        class _Ctx:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *exc):
                return False

        return _Ctx()


def _sink_form(voice=True):
    doc = {
        "persistence": {"data": {"type": "postgres_table", "connection": "c", "schema_name": "epson", "table": "t"}},
        "sections": [
            {
                "fields": [
                    {"field_id": "a", "field_type": "text"},
                    {"field_id": "h", "field_type": "hidden"},
                    {"field_id": "g", "field_type": "group", "children": [{"field_id": "c", "field_type": "text"}]},
                ]
            }
        ],
    }
    if voice:
        doc["voice"] = {"enabled": True}
    return doc


def test_migration_009_sql_defines_function_view_and_guarded_update():
    sql = (MIGRATIONS_DIR / "009_voice_envelope_form_data.sql").read_text()
    assert "CREATE OR REPLACE FUNCTION fd_unwrap_voice" in sql
    assert "CREATE OR REPLACE VIEW form_data_scalar" in sql
    assert re.search(r"jsonb_typeof\([^)]*\)\s*=\s*'string'", sql)


def test_envelope_columns_voice_and_voice_block(m009):
    assert m009.envelope_columns(_sink_form(voice=True)) == ["a", "g__c"]
    doc = _sink_form(voice=False)
    assert m009.envelope_columns(doc) == []
    doc["sections"][0]["fields"][0]["answer_envelope"] = "voice"
    assert m009.envelope_columns(doc) == ["a"]
    off = _sink_form(voice=True)
    off["voice"]["enabled"] = False
    assert m009.envelope_columns(off) == []


def test_alter_sql_rejects_bad_identifiers(m009):
    with pytest.raises(ValueError):
        m009.alter_sql("navigator", "t; DROP", "c")
    assert "jsonb_build_object('answer'" in m009.alter_sql("navigator", "t", "c")


async def test_sink_migration_dry_run_writes_nothing(m009):
    conn = _Conn([{"id": 1, "schema_json": json.dumps(_sink_form())}], {"a": "text", "g__c": "text"})
    report = await m009.migrate_sink_tables(_Pool(conn), schema="navigator", batch_size=10, dry_run=True)
    assert report.altered == ["epson.t.a", "epson.t.g__c"]
    assert conn.executed == []


async def test_sink_migration_alters_text_and_skips_jsonb_columns(m009):
    conn = _Conn([{"id": 1, "schema_json": _sink_form()}], {"a": "jsonb", "g__c": "text"})
    report = await m009.migrate_sink_tables(_Pool(conn), schema="navigator", batch_size=10, dry_run=False)
    assert report.skipped == ["epson.t.a"]
    assert report.altered == ["epson.t.g__c"]
    assert len(conn.executed) == 1 and '"g__c"' in conn.executed[0][0]


def test_report_is_envelope_shape(m010):
    assert m010.is_envelope({"answer": "x", "blob_ref": None})
    assert not m010.is_envelope({"answer": "x"})
    assert not m010.is_envelope("x")


def test_blob_exists_file_root_and_unsupported(m010, tmp_path):
    (tmp_path / "f" / "g").mkdir(parents=True)
    (tmp_path / "f" / "g" / "b1").write_text("x")
    assert m010.blob_exists(str(tmp_path), "local://f/g/b1") is True
    assert m010.blob_exists(tmp_path.as_uri(), "local://f/g/missing") is False
    assert m010.blob_exists("s3://bucket", "s3://bucket/f/g/b1") is None


def _data_rows():
    env = {"answer": "hi", "blob_ref": "local://f/g/gone", "source": "speech"}
    return [{"id": 1, "form_uid": "F", "data": json.dumps({"v": env, "plain": "x"})}]


async def test_report_inventory_and_orphans(m010, tmp_path):
    conn = _Conn([], {}, _data_rows())
    report = await m010.run_report(_Pool(conn), schema="navigator", blob_url=str(tmp_path))
    assert report.envelopes_by_field == {"F/v": 1}
    assert report.orphan_blob_refs == ["local://f/g/gone"]
    assert conn.executed == []
    assert "Voice envelopes: 1" in report.summary()


async def test_downgrade_requires_apply(m010):
    conn = _Conn([], {}, _data_rows())
    report = await m010.run_report(_Pool(conn), schema="navigator", downgrade=True, apply=False)
    assert report.downgraded == 1 and report.lost_blob_refs == 1
    assert conn.executed == []

    conn = _Conn([], {}, _data_rows())
    report = await m010.run_report(_Pool(conn), schema="navigator", downgrade=True, apply=True)
    assert len(conn.executed) == 1
    assert json.loads(conn.executed[0][1][0]) == {"v": "hi", "plain": "x"}


def test_009_exclusions_are_the_sink_mapper_rule(m009):
    """Ledger dfb11cf5d63f: the migration converts exactly the columns the sink writes as JSONB."""
    from parrot_formdesigner.services.sinks.mapper import _NON_VOICE_TYPES

    assert m009._NON_VOICE_TYPES == frozenset(t.value for t in _NON_VOICE_TYPES)
    doc = _sink_form(voice=True)
    doc["sections"][0]["fields"] += [
        {"field_id": "up", "field_type": "file"},
        {"field_id": "sig", "field_type": "signature"},
    ]
    assert m009.envelope_columns(doc) == ["a", "g__c", "up", "sig"]


def test_009_alter_keeps_sql_null(m009):
    assert "IS NULL THEN NULL" in m009.alter_sql("navigator", "t", "c")


async def test_010_downgrade_keeps_scalars_and_is_transactional(m010):
    """Ledger 8d6a964e54fe: bare JSON scalars survive the downgrade; the run is one transaction."""
    assert "jsonb_typeof" in m010._downgrade_sql('"s"."t"', "c")
    assert "#>> '{}'" in m010._downgrade_sql('"s"."t"', "c")
    conn = _Conn([{"id": 1, "schema_json": json.dumps(_sink_form())}], {"a": "jsonb"})
    _Tx.entered = 0
    await m010.run_report(_Pool(conn), schema="navigator", downgrade=True, apply=True)
    assert _Tx.entered == 1
    alter = [sql for sql, _ in conn.executed if "ALTER TABLE" in sql]
    assert len(alter) == 1 and "jsonb_typeof" in alter[0]
    _Tx.entered = 0
    await m010.run_report(_Pool(conn), schema="navigator", downgrade=True, apply=False)
    assert _Tx.entered == 0
