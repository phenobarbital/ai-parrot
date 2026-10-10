"""FEAT-649 TASK-4229 — voice-capable sink columns are JSONB; envelopes serialised."""
from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import pytest

from parrot_formdesigner.core.persistence import PostgresTableTarget
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.core.voice import VoiceFormConfig
from parrot_formdesigner.services.sink_aliases import SinkAliasRegistry
from parrot_formdesigner.services.sinks.base import SinkTargetMismatchError
from parrot_formdesigner.services.sinks.mapper import flatten_submission, voice_capable_columns
from parrot_formdesigner.services.sinks.postgres_table import PostgresTableSink, _ddl_type_for
from parrot_formdesigner.services.submissions import FormSubmission


class _Conn:
    def __init__(self, pool: "_Pool") -> None:
        self.pool = pool

    async def execute(self, sql: str, *args: object) -> None:
        self.pool.executed.append((sql, args))

    async def fetch(self, sql: str, *args: object):
        if "information_schema.columns" in sql:
            return [{"column_name": k, "data_type": v} for k, v in self.pool.existing.items()]
        return []


class _Ctx:
    def __init__(self, pool: "_Pool") -> None:
        self.pool = pool

    async def __aenter__(self) -> _Conn:
        return _Conn(self.pool)

    async def __aexit__(self, *exc: object) -> bool:
        return False


class _Pool:
    def __init__(self, existing=None) -> None:
        self.executed: list[tuple[str, tuple]] = []
        self.existing = existing or {}

    def acquire(self) -> _Ctx:
        return _Ctx(self)

    async def close(self) -> None:
        return None


def _form(voice: bool = True) -> FormSchema:
    return FormSchema(
        form_id="v",
        title="V",
        voice=VoiceFormConfig() if voice else None,
        sections=[
            FormSection(
                section_id="s1",
                fields=[
                    FormField(field_id="name", field_type=FieldType.TEXT, label="Name"),
                    FormField(field_id="age", field_type=FieldType.INTEGER, label="Age"),
                    FormField(field_id="secret", field_type=FieldType.PASSWORD, label="Secret"),
                ],
            )
        ],
    )


def _sink(pool: _Pool) -> PostgresTableSink:
    target = PostgresTableTarget(type="postgres_table", connection="c", schema_name="s", table="t")
    return PostgresTableSink(target, alias_registry=SinkAliasRegistry(), tenant="navigator", pool=pool)


def _submission(data: dict) -> FormSubmission:
    return FormSubmission(
        submission_id=str(uuid.uuid4()),
        form_uid=uuid.uuid4(),
        form_id="v",
        form_version="1.0",
        data=data,
        is_valid=True,
        created_at=datetime.now(UTC),
    )


class TestVoiceJsonbSink:
    def test_ddl_type_for_voice_is_jsonb(self) -> None:
        assert _ddl_type_for(FieldType.TEXT, voice=True) == "JSONB"
        assert _ddl_type_for(FieldType.TEXT) == "TEXT"

    def test_voice_capable_columns_answer_envelope_and_form_voice(self) -> None:
        assert voice_capable_columns(_form(True)) == frozenset({"name", "age"})
        assert voice_capable_columns(_form(False)) == frozenset()
        form = _form(False)
        form.sections[0].fields[0].answer_envelope = "voice"
        assert voice_capable_columns(form) == frozenset({"name"})

    def test_flatten_serialises_envelope_and_scalar_in_voice_column(self) -> None:
        env = {"kind": "voice", "value": "Ann"}
        row = flatten_submission(_form(), _submission({"name": env, "age": 4, "secret": "x"}))
        assert json.loads(row["name"]) == env
        assert row["age"] == "4"
        assert row["secret"] == "x"

    def test_flatten_none_stays_null(self) -> None:
        row = flatten_submission(_form(), _submission({}))
        assert row["name"] is None

    @pytest.mark.asyncio
    async def test_ensure_target_adds_jsonb_column_for_voice_field(self) -> None:
        pool = _Pool()
        await _sink(pool).ensure_target(_form())
        sqls = [s for s, _ in pool.executed]
        assert any("name" in s and "JSONB" in s for s in sqls)
        assert any("secret" in s and "TEXT" in s for s in sqls)

    @pytest.mark.asyncio
    async def test_ensure_target_text_column_for_voice_field_mismatch_names_migration(self) -> None:
        pool = _Pool(existing={"name": "text"})
        with pytest.raises(SinkTargetMismatchError, match="009_voice_envelope_sink_tables.py"):
            await _sink(pool).ensure_target(_form())

    @pytest.mark.asyncio
    async def test_write_uses_text_jsonb_cast_for_voice_column(self) -> None:
        pool = _Pool()
        sink = _sink(pool)
        form = _form()
        await sink.ensure_target(form)
        pool.executed.clear()
        row = flatten_submission(form, _submission({"name": {"a": 1}}))
        await sink.write(_submission({}), row)
        sql, args = pool.executed[-1]
        assert "::text::jsonb" in sql
        assert sql.count("::text::jsonb") >= 3  # context, extra_data, name, age
        assert json.dumps({"a": 1}) in args

    def test_non_voice_form_unchanged(self) -> None:
        row = flatten_submission(_form(False), _submission({"name": "Ann", "age": 4}))
        assert row["name"] == "Ann"
        assert row["age"] == 4
