"""Unit tests for the sink dispatch table and `SinkFactory` (FEAT-457, TASK-2426)."""

import pytest
from parrot_formdesigner.core.persistence import FormPersistenceConfig
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.services.sink_aliases import SinkAliasRegistry
from parrot_formdesigner.services.sinks import SUPPORTED_SINKS, SinkFactory
from parrot_formdesigner.services.sinks.base import SinkTargetMismatchError


@pytest.fixture
def alias_registry(tmp_path):
    reg = SinkAliasRegistry()
    reg.register("survey_db", tenant="navigator", dsn_env="SURVEY_DB_DSN")
    reg.register("exports", tenant="navigator", base_dir=str(tmp_path))
    return reg


@pytest.fixture
def factory(alias_registry):
    return SinkFactory(alias_registry)


def _postgres_form(*, form_id="nps", version="1.0", table="nps_2026", extra_field=False):
    fields = [FormField(field_id="comment", field_type=FieldType.TEXT, label="Comment")]
    if extra_field:
        fields.append(FormField(field_id="rating", field_type=FieldType.INTEGER, label="Rating"))
    section = FormSection(section_id="s1", fields=fields)
    return FormSchema(
        form_id=form_id,
        title="NPS",
        version=version,
        sections=[section],
        persistence=FormPersistenceConfig.model_validate(
            {
                "data": {
                    "type": "postgres_table",
                    "connection": "survey_db",
                    "schema_name": "surveys",
                    "table": table,
                }
            }
        ),
    )


@pytest.fixture
def form():
    return _postgres_form()


@pytest.fixture
def same_identity_forms():
    """Two forms sharing the same form_uid, one a version bump."""
    base = _postgres_form()
    bumped = _postgres_form(version="2.0")
    bumped.form_uid = base.form_uid
    return base, bumped


@pytest.fixture
def moved_table_forms():
    base = _postgres_form()
    moved = _postgres_form(table="different_table")
    moved.form_uid = base.form_uid
    return base, moved


@pytest.fixture
def extra_field_forms():
    base = _postgres_form()
    extended = _postgres_form(extra_field=True)
    extended.form_uid = base.form_uid
    return base, extended


def _csv_form(*, delimiter=","):
    section = FormSection(
        section_id="s1",
        fields=[FormField(field_id="comment", field_type=FieldType.TEXT, label="Comment")],
    )
    return FormSchema(
        form_id="csvform",
        title="CSV Form",
        sections=[section],
        persistence=FormPersistenceConfig.model_validate(
            {
                "data": {
                    "type": "csv_file",
                    "connection": "exports",
                    "path": "nps.csv",
                    "delimiter": delimiter,
                }
            }
        ),
    )


@pytest.fixture
def csv_delimiter_forms():
    base = _csv_form()
    semicolon = _csv_form(delimiter=";")
    semicolon.form_uid = base.form_uid
    return base, semicolon


class TestDispatch:
    @pytest.mark.parametrize("type_", sorted(SUPPORTED_SINKS))
    def test_every_key_resolves(self, type_):
        from parrot_formdesigner.services.sinks import _load

        assert _load(type_) is not None


class TestCache:
    async def test_same_key_same_instance(self, factory, form):
        a = await factory.get(form, tenant="navigator")
        b = await factory.get(form, tenant="navigator")
        assert a is b

    async def test_version_bump_new_instance(self, factory, same_identity_forms):
        base, bumped = same_identity_forms
        a = await factory.get(base, tenant="navigator")
        b = await factory.get(bumped, tenant="navigator")
        assert a is not b


class TestCoordinateImmutability:
    async def test_table_change_rejected(self, factory, moved_table_forms):
        base, moved = moved_table_forms
        await factory.get(base, tenant="navigator")
        with pytest.raises(SinkTargetMismatchError):
            await factory.get(moved, tenant="navigator")

    async def test_added_field_allowed(self, factory, extra_field_forms):
        base, extended = extra_field_forms
        await factory.get(base, tenant="navigator")
        assert await factory.get(extended, tenant="navigator") is not None

    async def test_delimiter_change_allowed(self, factory, csv_delimiter_forms):
        base, semicolon = csv_delimiter_forms
        await factory.get(base, tenant="navigator")
        assert await factory.get(semicolon, tenant="navigator") is not None


class TestCloseAll:
    async def test_close_all_idempotent(self, factory, form):
        await factory.get(form, tenant="navigator")
        await factory.close_all()
        await factory.close_all()  # must not raise

    async def test_no_persistence_raises(self, factory):
        section = FormSection(
            section_id="s1",
            fields=[FormField(field_id="x", field_type=FieldType.TEXT, label="X")],
        )
        bare_form = FormSchema(form_id="bare", title="Bare", sections=[section])
        with pytest.raises(ValueError):
            await factory.get(bare_form, tenant="navigator")
