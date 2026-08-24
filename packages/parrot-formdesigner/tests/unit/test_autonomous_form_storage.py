"""Unit tests for `AutonomousFormStorage` (FEAT-457, TASK-2427)."""

import uuid
from typing import Any

import pytest
from parrot_formdesigner.core.persistence import FormPersistenceConfig
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.services.autonomous_storage import AutonomousFormStorage
from parrot_formdesigner.services.registry import FormStorage
from parrot_formdesigner.services.sink_aliases import SinkAliasRegistry


class _InMemoryFormStorage(FormStorage):
    """Minimal FormStorage test double, including `load_by_slug`."""

    def __init__(self) -> None:
        self._rows: dict[tuple[uuid.UUID, str], FormSchema] = {}

    async def save(self, form, style=None, *, tenant=None) -> str:
        version = form.version or "1.0"
        self._rows[(form.form_uid, version)] = form
        return form.form_id

    async def load(self, form_uid, version=None, *, tenant=None):
        if version is not None:
            return self._rows.get((form_uid, version))
        candidates = [f for (uid, _v), f in self._rows.items() if uid == form_uid]
        return candidates[-1] if candidates else None

    async def load_by_slug(self, form_id, tenant, version=None):
        candidates = [f for f in self._rows.values() if f.form_id == form_id]
        if version is not None:
            candidates = [f for f in candidates if f.version == version]
        return candidates[-1] if candidates else None

    async def delete(self, form_uid, *, tenant=None) -> bool:
        keys = [k for k in self._rows if k[0] == form_uid]
        for key in keys:
            del self._rows[key]
        return bool(keys)

    async def list_forms(self, *, tenant=None) -> list[dict[str, Any]]:
        return [
            {
                "form_id": f.form_id,
                "version": f.version,
                "title": f.title,
                "description": f.description,
                "created_at": None,
            }
            for f in self._rows.values()
        ]


@pytest.fixture
def inner_storage():
    return _InMemoryFormStorage()


@pytest.fixture
def alias_registry(tmp_path):
    reg = SinkAliasRegistry()
    reg.register("defs", tenant="navigator", base_dir=str(tmp_path))
    return reg


@pytest.fixture
def autonomous_storage(inner_storage, alias_registry):
    return AutonomousFormStorage(inner_storage, alias_registry)


@pytest.fixture
def definition_path(tmp_path):
    return tmp_path / "nps.form.json"


@pytest.fixture
def autonomous_form():
    section = FormSection(
        section_id="s1",
        fields=[FormField(field_id="comment", field_type=FieldType.TEXT, label="Comment")],
    )
    return FormSchema(
        form_id="nps",
        title="NPS",
        tenant="navigator",
        sections=[section],
        persistence=FormPersistenceConfig.model_validate(
            {
                "data": {
                    "type": "csv_file",
                    "connection": "defs",
                    "path": "nps_data.csv",
                },
                "definition": {
                    "type": "file",
                    "connection": "defs",
                    "path": "nps.form.json",
                },
            }
        ),
    )


@pytest.fixture
def plain_form():
    section = FormSection(
        section_id="s1",
        fields=[FormField(field_id="name", field_type=FieldType.TEXT, label="Name")],
    )
    return FormSchema(
        form_id="plain",
        title="Plain",
        tenant="navigator",
        sections=[section],
    )


class TestABCCompliance:
    def test_instantiates(self, inner_storage, alias_registry):
        assert AutonomousFormStorage(inner_storage, alias_registry) is not None

    def test_load_by_slug_exists(self, autonomous_storage):
        # The ABC omits it, but FormRegistry calls it at registry.py:1075.
        assert callable(getattr(autonomous_storage, "load_by_slug", None))


class TestRoundtrip:
    async def test_save_then_load_by_uid(self, autonomous_storage, autonomous_form):
        await autonomous_storage.save(autonomous_form)
        got = await autonomous_storage.load(autonomous_form.form_uid, tenant="navigator")
        assert got == autonomous_form

    async def test_save_then_load_by_slug(self, autonomous_storage, autonomous_form):
        await autonomous_storage.save(autonomous_form)
        got = await autonomous_storage.load_by_slug(autonomous_form.form_id, "navigator")
        assert got == autonomous_form

    async def test_delete_removes_body(self, autonomous_storage, autonomous_form, definition_path):
        await autonomous_storage.save(autonomous_form)
        assert definition_path.exists()
        await autonomous_storage.delete(autonomous_form.form_uid, tenant="navigator")
        assert not definition_path.exists()

    async def test_body_file_contains_full_form(self, autonomous_storage, autonomous_form, definition_path):
        await autonomous_storage.save(autonomous_form)
        body = FormSchema.model_validate_json(definition_path.read_text())
        assert body == autonomous_form

    async def test_pointer_row_has_empty_sections(self, autonomous_storage, inner_storage, autonomous_form):
        await autonomous_storage.save(autonomous_form)
        pointer = await inner_storage.load(autonomous_form.form_uid, tenant="navigator")
        assert pointer.sections == []
        assert pointer.title == autonomous_form.title


class TestPassThrough:
    async def test_ordinary_form_untouched(self, autonomous_storage, plain_form):
        await autonomous_storage.save(plain_form)
        got = await autonomous_storage.load(plain_form.form_uid, tenant="navigator")
        assert got == plain_form

    async def test_list_forms_includes_pointer(self, autonomous_storage, autonomous_form):
        await autonomous_storage.save(autonomous_form)
        ids = [r["form_id"] for r in await autonomous_storage.list_forms(tenant="navigator")]
        assert autonomous_form.form_id in ids


class TestFailSoft:
    async def test_missing_body_raises_for_registry_to_catch(
        self, autonomous_storage, autonomous_form, definition_path
    ):
        await autonomous_storage.save(autonomous_form)
        definition_path.unlink()
        with pytest.raises(Exception):  # noqa: B017 — registry._read_through catches broadly
            await autonomous_storage.load(autonomous_form.form_uid, tenant="navigator")
