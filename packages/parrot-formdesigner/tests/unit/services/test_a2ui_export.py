"""A2UIExportService tests for FEAT-650 TASK-4196."""

from __future__ import annotations

from typing import Any

import pytest

from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection, RenderedForm
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.renderers.base import AbstractFormRenderer
from parrot_formdesigner.services.a2ui_export import A2UIExportService
from parrot_formdesigner.services.registry import FormRegistry, FormStorage


class _FakeRenderer(AbstractFormRenderer):
    """Renderer double that can fail for one form slug."""

    def __init__(self, fail_for: str | None = None) -> None:
        self.fail_for = fail_for

    async def render(
        self,
        form: FormSchema,
        style: Any = None,
        *,
        locale: str = "en",
        prefilled: dict[str, Any] | None = None,
        errors: dict[str, str] | None = None,
    ) -> RenderedForm:
        """Render a minimal createSurface envelope or raise for the selected form."""
        if form.form_id == self.fail_for:
            raise ValueError("boom")
        return RenderedForm(
            content={"createSurface": {"surfaceId": f"form-{form.form_uid}"}},
            content_type="application/a2ui+json",
            metadata={},
            warnings=[],
        )


class _RecordingStorage(FormStorage):
    """Storage double that records hydration operations."""

    def __init__(self, form: FormSchema, events: list[str]) -> None:
        self.form = form
        self.events = events

    async def save(
        self,
        form: FormSchema,
        style: Any = None,
        *,
        tenant: str | None = None,
    ) -> str:
        """Store the supplied form for completeness of the storage contract."""
        self.form = form
        return form.form_id

    async def load(
        self,
        form_id: str,
        version: str | None = None,
        *,
        tenant: str | None = None,
    ) -> FormSchema | None:
        """Return the persisted form and record the load."""
        self.events.append("storage.load")
        return self.form

    async def delete(self, form_id: str, *, tenant: str | None = None) -> bool:
        """Report that the test form was deleted."""
        return True

    async def list_forms(self, *, tenant: str | None = None) -> list[dict[str, Any]]:
        """Return the storage summary consumed by registry hydration."""
        self.events.append("storage.list_forms")
        return [{"form_uid": str(self.form.form_uid), "form_id": self.form.form_id, "version": self.form.version}]


class _RecordingRegistry(FormRegistry):
    """Registry double that records when the hydrated cache is listed."""

    def __init__(self, storage: FormStorage, events: list[str]) -> None:
        super().__init__(storage=storage, default_tenant="t1")
        self.events = events

    async def list_forms(self, *, tenant: str | None = None) -> list[FormSchema]:
        """Record cache iteration after delegating to the real registry."""
        self.events.append("registry.list_forms")
        return await super().list_forms(tenant=tenant)


def _form(form_id: str, tenant: str = "t1", published: str | None = None) -> FormSchema:
    """Build a minimal form fixture."""
    return FormSchema(
        form_id=form_id,
        title={"en": form_id},
        tenant=tenant,
        published_version=published,
        sections=[
            FormSection(
                section_id="s",
                fields=[
                    FormField(
                        field_id="a",
                        field_type=FieldType.TEXT,
                        label={"en": "A"},
                    )
                ],
            )
        ],
    )


@pytest.fixture
async def registry() -> FormRegistry:
    """Return a registry containing forms in two tenants."""
    form_registry = FormRegistry(storage=None, default_tenant="t1")
    for form in (_form("a"), _form("b", published="1.0"), _form("c", tenant="t2")):
        await form_registry.register(form, tenant=form.tenant)
    return form_registry


async def test_export_tenant_isolates_failures_and_never_crosses_tenants(registry: FormRegistry) -> None:
    """A failed form becomes an error row without leaking another tenant."""
    service = A2UIExportService(registry, renderer=_FakeRenderer(fail_for="b"))

    rows = [row async for row in service.export_tenant("t1")]

    assert sorted(row.form_id for row in rows) == ["a", "b"]
    by_id = {row.form_id: row for row in rows}
    assert by_id["a"].envelope and by_id["a"].error is None
    assert by_id["b"].envelope is None and by_id["b"].error == "boom"


async def test_published_only_and_uid_filter(registry: FormRegistry) -> None:
    """Published and UID filters independently select the requested forms."""
    service = A2UIExportService(registry, renderer=_FakeRenderer())
    forms = {form.form_id: form for form in await registry.list_forms(tenant="t1")}

    published_rows = [row async for row in service.export_tenant("t1", published_only=True)]
    selected_rows = [row async for row in service.export_tenant("t1", form_uids=[forms["a"].form_uid])]

    assert [row.form_id for row in published_rows] == ["b"]
    assert [row.form_id for row in selected_rows] == ["a"]


async def test_hydrates_from_storage_first() -> None:
    """Storage hydration completes before the tenant cache is enumerated."""
    events: list[str] = []
    persisted_form = _form("persisted")
    storage = _RecordingStorage(persisted_form, events)
    registry = _RecordingRegistry(storage, events)
    service = A2UIExportService(registry, renderer=_FakeRenderer())

    rows = [row async for row in service.export_tenant("t1")]

    assert [row.form_id for row in rows] == ["persisted"]
    assert events == ["storage.list_forms", "storage.load", "registry.list_forms"]


async def test_json_schema_dialect_uses_jsonschema_renderer(registry: FormRegistry) -> None:
    """The JSON Schema dialect resolves its built-in renderer."""
    service = A2UIExportService(registry, dialect="json_schema")

    rows = [row async for row in service.export_tenant("t1")]

    assert all(row.dialect == "json_schema" and row.envelope and row.envelope.get("type") == "object" for row in rows)


async def test_default_renderer_requires_extra(registry: FormRegistry, monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing optional A2UI registration produces an explicit install hint."""
    import parrot_formdesigner.api.render as render

    monkeypatch.setattr(render, "_RENDERERS", {})
    with pytest.raises(RuntimeError, match="ai-parrot"):
        A2UIExportService(registry)


async def test_real_a2ui_renderer(registry: FormRegistry) -> None:
    """The optional real renderer produces createSurface envelopes."""
    pytest.importorskip("parrot.outputs.a2ui")
    from parrot_formdesigner.renderers.a2ui import A2UIFormRenderer

    service = A2UIExportService(registry, renderer=A2UIFormRenderer())

    rows = [row async for row in service.export_tenant("t1")]

    assert rows
    assert all(row.envelope and "createSurface" in row.envelope for row in rows)
