"""resolve_dialect and render_a2ui_schema tests for FEAT-650 TASK-4192."""

from __future__ import annotations

import ast
import inspect
from typing import Any

import pytest
from aiohttp.test_utils import make_mocked_request

from parrot_formdesigner.api import dialect as dialect_module
from parrot_formdesigner.api.render import _RENDERERS, register_renderer
from parrot_formdesigner.core import FormDialect
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection, RenderedForm
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.renderers.base import AbstractFormRenderer


class _FakeA2UI(AbstractFormRenderer):
    """Minimal renderer that makes dialect negotiation independent of ai-parrot."""

    async def render(
        self,
        form: FormSchema,
        style: Any = None,
        *,
        locale: str = "en",
        prefilled: dict[str, Any] | None = None,
        errors: dict[str, str] | None = None,
    ) -> RenderedForm:
        """Return a deterministic createSurface-like envelope."""
        del style, locale, prefilled, errors
        return RenderedForm(
            content={"version": "v1.0", "createSurface": {"surfaceId": f"form-{form.form_uid}"}},
            content_type=dialect_module.A2UI_MEDIA_TYPE,
            metadata={},
            warnings=[],
        )


@pytest.fixture(autouse=True)
def _reset_renderers() -> None:
    """Isolate the global renderer registry for every test."""
    snapshot = dict(_RENDERERS)
    _RENDERERS.clear()
    yield
    _RENDERERS.clear()
    _RENDERERS.update(snapshot)


def _form(dialect: str = "json_schema") -> FormSchema:
    """Build the smallest valid form for dialect tests."""
    return FormSchema(
        form_id="f",
        title={"en": "F"},
        tenant="navigator",
        dialect=dialect,
        sections=[
            FormSection(
                section_id="s",
                fields=[FormField(field_id="a", field_type=FieldType.TEXT, label={"en": "A"})],
            )
        ],
    )


def _request(query: str = "", accept: str | None = None):
    """Build a request carrying the negotiated inputs."""
    headers = {"Accept": accept} if accept else {}
    return make_mocked_request("GET", f"/x{query}", headers=headers)


@pytest.mark.parametrize(
    ("query", "accept", "stored", "expected"),
    [
        ("", None, "json_schema", FormDialect.JSON_SCHEMA),
        ("", None, "a2ui", FormDialect.A2UI),
        ("", dialect_module.A2UI_MEDIA_TYPE, "json_schema", FormDialect.A2UI),
        ("", "application/json", "json_schema", FormDialect.JSON_SCHEMA),
        ("?dialect=json_schema", dialect_module.A2UI_MEDIA_TYPE, "a2ui", FormDialect.JSON_SCHEMA),
        ("?dialect=a2ui", None, "json_schema", FormDialect.A2UI),
        ("?dialect=a2ui", "application/json", "json_schema", FormDialect.A2UI),
        ("", "*/*", "json_schema", FormDialect.JSON_SCHEMA),
    ],
)
def test_precedence(query: str, accept: str | None, stored: str, expected: FormDialect) -> None:
    """Resolve all eight query, Accept, and stored-dialect combinations."""
    register_renderer("a2ui", _FakeA2UI())

    assert dialect_module.resolve_dialect(_request(query, accept), _form(stored)) is expected


def test_unknown_query_value_is_400() -> None:
    """Reject unknown query dialects with the documented error shape."""
    with pytest.raises(dialect_module.DialectError) as error_info:
        dialect_module.resolve_dialect(_request("?dialect=xml"), _form())

    assert error_info.value.status == 400
    assert error_info.value.payload == {
        "error": "unknown dialect 'xml'",
        "supported": ["json_schema", "a2ui"],
    }


def test_a2ui_without_renderer_is_415_with_supported_list() -> None:
    """Return the render dispatcher's supported-format payload when A2UI is absent."""
    register_renderer("html", _FakeA2UI())

    with pytest.raises(dialect_module.DialectError) as error_info:
        dialect_module.resolve_dialect(_request("?dialect=a2ui"), _form())

    assert error_info.value.status == 415
    assert error_info.value.payload == {"supported": ["html"]}


async def test_render_a2ui_schema_single_envelope_and_baseline_overrides() -> None:
    """Keep the createSurface envelope and warn for baseline overrides."""
    register_renderer("a2ui", _FakeA2UI())

    envelopes, rendered, warnings = await dialect_module.render_a2ui_schema(_form(), overrides={"title": "X"})

    assert len(envelopes) == 1
    assert rendered.content_type == dialect_module.A2UI_MEDIA_TYPE
    assert warnings == ["override_not_translatable:title"]


async def test_real_renderer_when_extra_installed() -> None:
    """Render one real A2UI createSurface when the optional extra is installed."""
    pytest.importorskip("parrot.outputs.a2ui")
    from parrot_formdesigner.renderers import A2UIFormRenderer

    register_renderer("a2ui", A2UIFormRenderer())

    envelopes, _, _ = await dialect_module.render_a2ui_schema(_form())

    assert envelopes[0]["createSurface"]["surfaceId"].startswith("form-")


def test_dialect_module_has_no_top_level_ai_parrot_import() -> None:
    """Keep dialect negotiation importable without the optional ai-parrot extra."""
    tree = ast.parse(inspect.getsource(dialect_module))
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith("parrot."), f"unexpected top-level import: {alias.name}"
        elif isinstance(node, ast.ImportFrom):
            module_name = node.module or ""
            assert not module_name.startswith("parrot."), f"unexpected top-level import: {module_name}"
