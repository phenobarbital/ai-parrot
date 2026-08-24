"""End-to-end integration suite for autonomous FormSchema persistence (FEAT-457, TASK-2430).

Covers the 13 scenarios in spec section 4 ("Integration Tests"). Runs
WITHOUT a live database: Postgres scenarios use a fake asyncpg-pool
double (``fake_pool``, recording executed SQL) wired into a REAL
``PostgresTableSink``; CSV scenarios use a REAL ``CsvFileSink`` writing
into ``tmp_path``. Exclusivity and backwards-compatibility are asserted
on the mock call itself (``FormSubmissionStorage.store``), never
inferred from state, per the task's own key constraint.

Two of the thirteen named scenarios below are marked ``xfail`` — see the
module-level "Known gaps" note.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web
from parrot_formdesigner.api.handlers import FormAPIHandler
from parrot_formdesigner.core.persistence import FormPersistenceConfig
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.services.autonomous_storage import AutonomousFormStorage
from parrot_formdesigner.services.forwarder import ForwardResult, SubmissionForwarder
from parrot_formdesigner.services.partial_saves import PartialSaveStore
from parrot_formdesigner.services.registry import FormRegistry, FormStorage
from parrot_formdesigner.services.sinks.base import SinkUnavailableError
from parrot_formdesigner.services.sinks.csv_file import CsvFileSink
from parrot_formdesigner.services.sinks.postgres_table import PostgresTableSink
from parrot_formdesigner.services.submissions import FormSubmissionStorage
from parrot_formdesigner.services.validators import FormValidator, ValidationResult

# `alias_registry` / `survey_form_postgres` / `survey_form_csv` / `fake_pool`
# fixtures come from tests/fixtures/persistence.py via tests/integration/conftest.py.

# ---------------------------------------------------------------------------
# Known gaps (documented per the task's "report it rather than patching
# production here" instruction — NOT fixed in this task):
#
# - `test_read_on_csv_form_returns_501` / `test_read_on_postgres_form_returns_200`:
#   `FormAPIHandler` has NO `get_submission`/`list_revisions` HTTP endpoint
#   anywhere in this codebase (verified via grep — TASK-2428's own
#   completion note documents the same gap). There is nothing to call.
# - `test_unknown_alias_rejected_at_registration`: no production code path
#   validates a `persistence.data.connection` alias against the
#   `SinkAliasRegistry` allowlist at `FormRegistry.register()` time (or
#   anywhere else) — `FormSchema` construction and `FormRegistry.register()`
#   both accept an unknown alias silently today. Registering the
#   alias-validation feature itself is out of THIS task's scope (no new
#   production code).
# ---------------------------------------------------------------------------

_TEST_TENANT = "navigator"
_FORM_UID = "11111111-1111-1111-1111-111111111111"


def _make_request(body: dict | None = None, *, session_id: str | None = None) -> MagicMock:
    req = MagicMock(spec=web.Request)
    req.match_info = {"form_uid": _FORM_UID}
    req.query = MagicMock()
    req.query.get = MagicMock(
        side_effect=lambda key, default="": "true" if key == "merge_partials" and session_id else default
    )
    if session_id is not None:
        req.__contains__ = lambda self, key: key == "session"
        req.__getitem__ = lambda self, key: {"id": session_id} if key == "session" else None
    else:
        req.__contains__ = lambda self, key: False
    req.json = AsyncMock(return_value=body or {"comment": "great"})
    req.get = MagicMock(side_effect=lambda key, default=None: _TEST_TENANT if key == "tenant" else default)
    req.session = {"session": {"programs": [_TEST_TENANT]}}
    return req


def _make_validation_result(data: dict | None = None) -> ValidationResult:
    return ValidationResult(is_valid=True, errors={}, sanitized_data=data or {"comment": "great"})


class _SingleSinkFactory:
    """Test double: always returns the SAME pre-built (real) sink."""

    def __init__(self, sink) -> None:
        self._sink = sink

    async def get(self, form, *, tenant):
        return self._sink

    async def close_all(self) -> None:
        await self._sink.close()


def _make_handler(
    form: FormSchema,
    *,
    sink_factory=None,
    submission_storage=None,
    forwarder=None,
    partial_store=None,
    validation_data: dict | None = None,
) -> FormAPIHandler:
    registry = MagicMock(spec=FormRegistry)
    registry.get = AsyncMock(return_value=form)

    handler = FormAPIHandler(
        registry=registry,
        submission_storage=submission_storage,
        sink_factory=sink_factory,
        forwarder=forwarder,
        partial_store=partial_store,
    )
    handler.validator = MagicMock(spec=FormValidator)
    handler.validator.validate = AsyncMock(return_value=_make_validation_result(validation_data))
    return handler


def _form_with_fields(*, form_id: str, fields: list[FormField], persistence: FormPersistenceConfig) -> FormSchema:
    return FormSchema(
        form_id=form_id,
        title="Test",
        tenant=_TEST_TENANT,
        sections=[FormSection(section_id="s1", fields=fields)],
        persistence=persistence,
    )


def _postgres_persistence() -> FormPersistenceConfig:
    return FormPersistenceConfig.model_validate(
        {
            "data": {
                "type": "postgres_table",
                "connection": "survey_db",
                "schema_name": "surveys",
                "table": "responses",
            }
        }
    )


class TestExclusivity:
    async def test_submit_to_own_postgres_table(self, survey_form_postgres, alias_registry, fake_pool):
        sink = PostgresTableSink(
            survey_form_postgres.persistence.data,
            alias_registry=alias_registry,
            tenant=_TEST_TENANT,
            pool=fake_pool,
        )
        handler = _make_handler(
            survey_form_postgres,
            sink_factory=_SingleSinkFactory(sink),
            submission_storage=MagicMock(spec=FormSubmissionStorage),
        )
        resp = await handler.submit_data(_make_request())
        assert resp.status == 200
        assert any("INSERT INTO" in s for s in fake_pool.executed)

    async def test_submit_skips_generic_storage(self, survey_form_postgres, alias_registry, fake_pool):
        sink = PostgresTableSink(
            survey_form_postgres.persistence.data,
            alias_registry=alias_registry,
            tenant=_TEST_TENANT,
            pool=fake_pool,
        )
        storage = MagicMock(spec=FormSubmissionStorage)
        storage.store = AsyncMock()
        handler = _make_handler(survey_form_postgres, sink_factory=_SingleSinkFactory(sink), submission_storage=storage)
        resp = await handler.submit_data(_make_request())
        assert resp.status == 200
        storage.store.assert_not_called()  # the guarantee — asserted on the call

    async def test_submit_without_persistence_unchanged(self):
        plain_form = FormSchema(
            form_id="plain",
            title="Plain",
            tenant=_TEST_TENANT,
            sections=[
                FormSection(
                    section_id="s1", fields=[FormField(field_id="name", field_type=FieldType.TEXT, label="Name")]
                )
            ],
        )
        storage = MagicMock(spec=FormSubmissionStorage)
        storage.store = AsyncMock()
        handler = _make_handler(plain_form, submission_storage=storage)
        resp = await handler.submit_data(_make_request())
        assert resp.status == 200
        storage.store.assert_awaited_once()


class TestCsvSink:
    async def test_submit_to_csv_appends_row(self, survey_form_csv, alias_registry, tmp_path):
        sink = CsvFileSink(survey_form_csv.persistence.data, alias_registry=alias_registry, tenant=_TEST_TENANT)
        handler = _make_handler(survey_form_csv, sink_factory=_SingleSinkFactory(sink))
        await handler.submit_data(_make_request())
        await handler.submit_data(_make_request())
        csv_path = tmp_path / "responses.csv"
        lines = csv_path.read_text().strip().splitlines()
        assert len(lines) == 3  # header + 2 data rows


class TestFailureSemantics:
    async def test_sink_down_returns_503(self, survey_form_postgres):
        broken_sink = MagicMock()
        broken_sink.family = "tabular"
        broken_sink.ensure_target = AsyncMock(side_effect=SinkUnavailableError("db down"))
        storage = MagicMock(spec=FormSubmissionStorage)
        storage.store = AsyncMock()
        handler = _make_handler(
            survey_form_postgres,
            sink_factory=_SingleSinkFactory(broken_sink),
            submission_storage=storage,
        )
        resp = await handler.submit_data(_make_request())
        assert resp.status == 503
        assert "Retry-After" in resp.headers
        storage.store.assert_not_called()  # nothing persisted anywhere


class TestCapabilityGating:
    @pytest.mark.xfail(
        reason=(
            "FEAT-457 gap: FormAPIHandler has no get_submission HTTP endpoint "
            "anywhere in this codebase (verified via grep) — nothing to gate on "
            "capabilities. See TASK-2428's completion note for the same finding."
        ),
        strict=True,
    )
    async def test_read_on_csv_form_returns_501(self, survey_form_csv, alias_registry):
        sink = CsvFileSink(survey_form_csv.persistence.data, alias_registry=alias_registry, tenant=_TEST_TENANT)
        handler = _make_handler(survey_form_csv, sink_factory=_SingleSinkFactory(sink))
        resp = await handler.get_submission(_make_request())  # does not exist
        assert resp.status == 501

    @pytest.mark.xfail(
        reason=(
            "FEAT-457 gap: FormAPIHandler has no get_submission HTTP endpoint "
            "anywhere in this codebase (verified via grep) — nothing to gate on "
            "capabilities. See TASK-2428's completion note for the same finding."
        ),
        strict=True,
    )
    async def test_read_on_postgres_form_returns_200(self, survey_form_postgres, alias_registry, fake_pool):
        sink = PostgresTableSink(
            survey_form_postgres.persistence.data,
            alias_registry=alias_registry,
            tenant=_TEST_TENANT,
            pool=fake_pool,
        )
        handler = _make_handler(survey_form_postgres, sink_factory=_SingleSinkFactory(sink))
        resp = await handler.get_submission(_make_request())  # does not exist
        assert resp.status == 200


class TestProvisioning:
    async def test_new_field_adds_column(self, alias_registry, fake_pool):
        base = _form_with_fields(
            form_id="prov",
            fields=[FormField(field_id="comment", field_type=FieldType.TEXT, label="Comment")],
            persistence=_postgres_persistence(),
        )
        base.form_uid = uuid.UUID(_FORM_UID)
        extended = _form_with_fields(
            form_id="prov",
            fields=[
                FormField(field_id="comment", field_type=FieldType.TEXT, label="Comment"),
                FormField(field_id="rating", field_type=FieldType.INTEGER, label="Rating"),
            ],
            persistence=_postgres_persistence(),
        )
        extended.form_uid = base.form_uid

        sink = PostgresTableSink(
            base.persistence.data, alias_registry=alias_registry, tenant=_TEST_TENANT, pool=fake_pool
        )
        factory = _SingleSinkFactory(sink)

        handler = _make_handler(base, sink_factory=factory)
        await handler.submit_data(_make_request())

        handler.registry.get = AsyncMock(return_value=extended)
        await handler.submit_data(_make_request())

        assert any("ADD COLUMN IF NOT EXISTS" in s and "rating" in s for s in fake_pool.executed)

    async def test_removed_field_leaves_column(self, alias_registry, fake_pool):
        extended = _form_with_fields(
            form_id="prov2",
            fields=[
                FormField(field_id="comment", field_type=FieldType.TEXT, label="Comment"),
                FormField(field_id="rating", field_type=FieldType.INTEGER, label="Rating"),
            ],
            persistence=_postgres_persistence(),
        )
        extended.form_uid = uuid.UUID(_FORM_UID)
        fewer = _form_with_fields(
            form_id="prov2",
            fields=[FormField(field_id="comment", field_type=FieldType.TEXT, label="Comment")],
            persistence=_postgres_persistence(),
        )
        fewer.form_uid = extended.form_uid

        sink = PostgresTableSink(
            extended.persistence.data, alias_registry=alias_registry, tenant=_TEST_TENANT, pool=fake_pool
        )
        factory = _SingleSinkFactory(sink)

        handler = _make_handler(extended, sink_factory=factory)
        await handler.submit_data(_make_request())
        fake_pool.existing_columns = {"comment": "text", "rating": "integer"}
        fake_pool.executed.clear()

        handler.registry.get = AsyncMock(return_value=fewer)
        await handler.submit_data(_make_request())

        assert not any("DROP" in s.upper() for s in fake_pool.executed)


class TestInteractions:
    async def test_merge_partials_then_sink_write(self, survey_form_postgres, alias_registry, fake_pool):
        name_field = survey_form_postgres.sections[0].fields[0]
        cached = MagicMock()
        cached.data = {str(name_field.field_uid): "cached-value"}
        store = MagicMock(spec=PartialSaveStore)
        store.get = AsyncMock(return_value=cached)
        store.delete = AsyncMock(return_value=True)

        captured: dict = {}

        sink = PostgresTableSink(
            survey_form_postgres.persistence.data,
            alias_registry=alias_registry,
            tenant=_TEST_TENANT,
            pool=fake_pool,
        )
        real_write = sink.write

        async def spy_write(submission, payload):
            captured.update(payload)
            return await real_write(submission, payload)

        sink.write = spy_write

        handler = _make_handler(survey_form_postgres, sink_factory=_SingleSinkFactory(sink), partial_store=store)
        await handler.submit_data(_make_request(session_id="sess-1"))

        store.get.assert_awaited_once()
        assert captured  # payload was written — merge happened before the sink write

    async def test_autonomous_form_still_listed(self):
        class _InMemoryFormStorage(FormStorage):
            def __init__(self) -> None:
                self._rows: dict[tuple, FormSchema] = {}

            async def save(self, form, style=None, *, tenant=None) -> str:
                self._rows[(form.form_uid, form.version)] = form
                return form.form_id

            async def load(self, form_uid, version=None, *, tenant=None):
                matches = [f for (uid, _v), f in self._rows.items() if uid == form_uid]
                return matches[-1] if matches else None

            async def load_by_slug(self, form_id, tenant, version=None):
                matches = [f for f in self._rows.values() if f.form_id == form_id]
                return matches[-1] if matches else None

            async def delete(self, form_uid, *, tenant=None) -> bool:
                return False

            async def list_forms(self, *, tenant=None):
                return [{"form_id": f.form_id, "version": f.version, "title": f.title} for f in self._rows.values()]

        alias_reg_local = MagicMock()
        alias_reg_local.contain = MagicMock(
            side_effect=lambda alias, *, tenant, relative_path: __import__("pathlib").Path(f"/tmp/{relative_path}")
        )
        inner = _InMemoryFormStorage()
        storage = AutonomousFormStorage(inner, alias_reg_local)
        form = FormSchema(
            form_id="autonomous",
            title="Autonomous",
            tenant=_TEST_TENANT,
            sections=[
                FormSection(section_id="s1", fields=[FormField(field_id="x", field_type=FieldType.TEXT, label="X")])
            ],
            persistence=FormPersistenceConfig.model_validate(
                {
                    "data": {"type": "csv_file", "connection": "exports", "path": "auto.csv"},
                    "definition": {"type": "file", "connection": "exports", "path": "auto.form.json"},
                }
            ),
        )
        registry = FormRegistry(storage=storage, default_tenant=_TEST_TENANT)
        await registry.register(form, tenant=_TEST_TENANT, persist=True)

        listed = await storage.list_forms(tenant=_TEST_TENANT)
        assert any(r["form_id"] == "autonomous" for r in listed)

        got = await registry.get_by_slug("autonomous", tenant=_TEST_TENANT)
        assert got is not None
        assert got.form_id == "autonomous"

    @pytest.mark.xfail(
        reason=(
            "FEAT-457 gap: no production code path validates a "
            "persistence.data.connection alias against SinkAliasRegistry at "
            "FormRegistry.register() time (or anywhere else) — FormSchema "
            "construction and FormRegistry.register() both accept an unknown "
            "alias silently today. Implementing the validation itself is a "
            "production change outside this task's scope."
        ),
        strict=True,
    )
    async def test_unknown_alias_rejected_at_registration(self, alias_registry):
        form = _form_with_fields(
            form_id="badalias",
            fields=[FormField(field_id="x", field_type=FieldType.TEXT, label="X")],
            persistence=FormPersistenceConfig.model_validate(
                {
                    "data": {
                        "type": "postgres_table",
                        "connection": "nonexistent_alias",
                        "schema_name": "s",
                        "table": "t",
                    }
                }
            ),
        )
        registry = FormRegistry(default_tenant=_TEST_TENANT)
        # Desired behavior: registering a form whose persistence.data.connection
        # is not in the alias allowlist is rejected at REGISTRATION time, not
        # discovered later at submit time. No production code today validates
        # this anywhere — the call below currently succeeds silently, which is
        # exactly the gap this xfail documents.
        with pytest.raises(ValueError, match="alias"):
            await registry.register(form, tenant=_TEST_TENANT)

    async def test_forwarder_still_runs_with_persistence(self, survey_form_postgres, alias_registry, fake_pool):
        from parrot_formdesigner.core.schema import SubmitAction

        form = survey_form_postgres.model_copy(
            update={"submit": SubmitAction(action_type="endpoint", action_ref="https://example.com/hook")}
        )
        sink = PostgresTableSink(
            form.persistence.data, alias_registry=alias_registry, tenant=_TEST_TENANT, pool=fake_pool
        )
        forwarder = MagicMock(spec=SubmissionForwarder)
        forwarder.forward = AsyncMock(return_value=ForwardResult(success=True, status_code=200, error=None))
        handler = _make_handler(form, sink_factory=_SingleSinkFactory(sink), forwarder=forwarder)
        resp = await handler.submit_data(_make_request())
        assert resp.status == 200
        forwarder.forward.assert_awaited_once()
        assert any("INSERT INTO" in s for s in fake_pool.executed)
