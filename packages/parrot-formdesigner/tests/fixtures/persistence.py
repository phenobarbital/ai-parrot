"""Shared fixtures for FEAT-457 (Autonomous FormSchema Persistence) tests.

Import the fixture functions you need into a local ``conftest.py`` (see
``tests/integration/conftest.py``), not directly into a test module —
pytest discovers fixtures by name in the importing module's namespace, but
importing them straight into a test module makes any same-named test
parameter look like an (unused) redefinition to static analysis tools.
"""

from __future__ import annotations

from typing import Any

import pytest
from parrot_formdesigner.core.persistence import FormPersistenceConfig
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.services.sink_aliases import SinkAliasRegistry


@pytest.fixture
def alias_registry(tmp_path, monkeypatch):
    """SinkAliasRegistry with one DSN alias and one base-dir alias."""
    monkeypatch.setenv("SURVEY_DB_DSN", "postgresql://u:p@localhost/surveys")
    reg = SinkAliasRegistry()
    reg.register("survey_db", tenant="navigator", dsn_env="SURVEY_DB_DSN")
    reg.register("exports", tenant="navigator", base_dir=str(tmp_path))
    return reg


@pytest.fixture
def survey_form_postgres():
    """FormSchema with a PostgresTableTarget, a GROUP, and an ARRAY field."""
    address = FormField(
        field_id="address",
        field_type=FieldType.GROUP,
        label="Address",
        children=[FormField(field_id="city", field_type=FieldType.TEXT, label="City")],
    )
    answers = FormField(
        field_id="answers",
        field_type=FieldType.ARRAY,
        label="Answers",
        item_template=FormField(field_id="q", field_type=FieldType.NUMBER, label="Q"),
    )
    section = FormSection(section_id="s1", fields=[address, answers])
    return FormSchema(
        form_id="survey",
        title="Survey",
        tenant="navigator",
        sections=[section],
        persistence=FormPersistenceConfig.model_validate(
            {
                "data": {
                    "type": "postgres_table",
                    "connection": "survey_db",
                    "schema_name": "surveys",
                    "table": "responses",
                }
            }
        ),
    )


@pytest.fixture
def survey_form_csv():
    """FormSchema with a CsvFileTarget pointing inside the alias's base dir."""
    section = FormSection(
        section_id="s1",
        fields=[FormField(field_id="comment", field_type=FieldType.TEXT, label="Comment")],
    )
    return FormSchema(
        form_id="csvsurvey",
        title="CSV Survey",
        tenant="navigator",
        sections=[section],
        persistence=FormPersistenceConfig.model_validate(
            {
                "data": {
                    "type": "csv_file",
                    "connection": "exports",
                    "path": "responses.csv",
                }
            }
        ),
    )


class _FakeConn:
    def __init__(self, pool: _FakePool) -> None:
        self.pool = pool

    async def execute(self, sql: str, *args: object) -> None:
        self.pool.executed.append(sql)

    async def fetch(self, sql: str, *args: object):
        if "information_schema.columns" in sql:
            return [
                {"column_name": k, "data_type": v}
                for k, v in self.pool.existing_columns.items()
            ]
        return self.pool.fetch_rows

    async def fetchrow(self, sql: str, *args: object):
        return self.pool.fetchrow_result


class _AcquireCtx:
    def __init__(self, pool: _FakePool) -> None:
        self.pool = pool

    async def __aenter__(self) -> _FakeConn:
        return _FakeConn(self.pool)

    async def __aexit__(self, *exc: object) -> bool:
        return False


class _FakePool:
    """asyncpg-pool double recording every executed SQL statement."""

    def __init__(self) -> None:
        self.executed: list[str] = []
        self.existing_columns: dict[str, str] = {}
        self.fetchrow_result: Any = None
        self.fetch_rows: list[Any] = []

    def acquire(self) -> _AcquireCtx:
        return _AcquireCtx(self)

    async def close(self) -> None:
        return None


@pytest.fixture
def fake_pool():
    """asyncpg-pool double recording executed SQL (see PostgresTableSink tests)."""
    return _FakePool()
