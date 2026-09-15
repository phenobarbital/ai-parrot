"""Unit tests for A2UIFormRenderer (FEAT-544, TASK-3071).

Covers the renderer skeleton: surface layout, dataModel construction,
submit/cancel Buttons, pointer helpers and envelope validation. Field
lowering itself is stubbed in this module (every field -> Text notice) —
see TASK-3072 for the FieldType lowering table tests.
"""

from __future__ import annotations

import ast
import inspect

import pytest

pytest.importorskip("parrot.outputs.a2ui")

from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.renderers.a2ui import (
    A2UIFormRenderer,
    field_id_from_pointer_token,
    field_pointer,
)

from parrot.outputs.a2ui.catalog import validate_envelope
from parrot.outputs.a2ui.catalog.base import DEFAULT_CATALOG_ID, ProducerOrigin
from parrot.outputs.a2ui.models import CreateSurface, is_valid_pointer


@pytest.fixture
def sample_form() -> FormSchema:
    return FormSchema(
        form_id="demo",
        title={"en": "Demo", "es": "Demo"},
        tenant="acme",
        sections=[
            FormSection(
                section_id="main",
                title="Main",
                fields=[
                    FormField(field_id="name", field_type=FieldType.TEXT, label="Name", required=True),
                    FormField(field_id="agree", field_type=FieldType.BOOLEAN, label="Agree", default=False),
                ],
            )
        ],
    )


def _surface_dict(content: dict) -> dict:
    return content["createSurface"]


async def test_render_returns_createsurface_with_a2ui_media_type(sample_form):
    renderer = A2UIFormRenderer()
    result = await renderer.render(sample_form)

    assert result.content_type == "application/a2ui+json"
    assert result.content["version"] == "v1.0"
    surface = _surface_dict(result.content)
    assert surface["surfaceId"] == f"form-{sample_form.form_uid}"
    assert surface["sendDataModel"] is True
    assert surface["catalogId"] == DEFAULT_CATALOG_ID


async def test_root_is_first_and_unique_with_status_placeholder(sample_form):
    renderer = A2UIFormRenderer()
    result = await renderer.render(sample_form)
    surface = _surface_dict(result.content)
    components = surface["components"]

    root_ids = [c for c in components if c["id"] == "root"]
    assert len(root_ids) == 1
    assert components[0]["id"] == "root"
    assert components[0]["component"] == "Column"

    status = next(c for c in components if c["id"] == "root-status")
    assert status["component"] == "Text"
    assert status["metadata"]["extensions"]["parrot_role"] == "status"
    assert status["text"] == ""


async def test_submit_button_action_targets_form_data_endpoint(sample_form):
    renderer = A2UIFormRenderer()
    result = await renderer.render(sample_form)
    surface = _surface_dict(result.content)
    submit = next(c for c in surface["components"] if c["id"] == "root-submit")

    event = submit["action"]["event"]
    assert event["name"] == "form.submit"
    assert event["context"]["submit_url"] == f"/api/v1/{sample_form.tenant}/forms/{sample_form.form_uid}/data"
    assert event["context"]["answers"] == {"path": "/answers"}


async def test_cancel_button_only_when_cancel_allowed(sample_form):
    renderer = A2UIFormRenderer()

    result = await renderer.render(sample_form)
    surface = _surface_dict(result.content)
    assert any(c["id"] == "root-cancel" for c in surface["components"])

    sample_form.cancel_allowed = False
    result = await renderer.render(sample_form)
    surface = _surface_dict(result.content)
    assert not any(c["id"] == "root-cancel" for c in surface["components"])


async def test_root_extensions_carry_identity(sample_form):
    renderer = A2UIFormRenderer()
    result = await renderer.render(sample_form)
    surface = _surface_dict(result.content)
    root = next(c for c in surface["components"] if c["id"] == "root")
    extensions = root["metadata"]["extensions"]

    assert extensions["parrot_variant"] == "form"
    assert extensions["parrot_form_uid"] == str(sample_form.form_uid)
    assert extensions["parrot_form_id"] == sample_form.form_id
    assert extensions["parrot_tenant"] == sample_form.tenant
    assert extensions["parrot_submit_url"] == f"/api/v1/{sample_form.tenant}/forms/{sample_form.form_uid}/data"

    for key in root:
        assert not key.startswith("parrot_")


async def test_datamodel_seeds_prefilled_then_default_then_null(sample_form):
    renderer = A2UIFormRenderer()
    result = await renderer.render(sample_form, prefilled={"name": "Ada"})
    surface = _surface_dict(result.content)
    answers = surface["dataModel"]["answers"]

    assert answers["name"] == "Ada"  # prefilled wins
    assert answers["agree"] is False  # falls back to default (not truthiness-tested as None)


async def test_errors_param_emits_error_text_and_datamodel_errors(sample_form):
    renderer = A2UIFormRenderer()
    result = await renderer.render(sample_form, errors={"name": "Name is required."})
    surface = _surface_dict(result.content)

    error_text = next(c for c in surface["components"] if c["id"] == "f-name-error")
    assert error_text["text"] == "Name is required."
    assert error_text["metadata"]["extensions"]["parrot_role"] == "error"
    assert surface["dataModel"]["errors"]["name"] == "Name is required."


def test_field_pointer_escapes_rfc6901_and_roundtrips():
    assert field_pointer("a/b") == "/answers/a~1b"
    assert field_pointer("x~y") == "/answers/x~0y"
    assert is_valid_pointer(field_pointer("a/b"))
    assert is_valid_pointer(field_pointer("x~y"))

    assert field_id_from_pointer_token(field_pointer("a/b").removeprefix("/answers/")) == "a/b"
    assert field_id_from_pointer_token(field_pointer("x~y").removeprefix("/answers/")) == "x~y"


async def test_envelope_passes_validate_envelope_tool_origin_and_fails_llm(sample_form):
    renderer = A2UIFormRenderer()
    result = await renderer.render(sample_form)
    surface_model = CreateSurface.model_validate(_surface_dict(result.content))

    validate_envelope(surface_model, origin=ProducerOrigin.TOOL, surface_catalog_id=DEFAULT_CATALOG_ID)

    with pytest.raises(Exception):
        validate_envelope(surface_model, origin=ProducerOrigin.LLM, surface_catalog_id=DEFAULT_CATALOG_ID)


def test_module_import_does_not_import_ai_parrot_eagerly():
    """No top-level ``import``/``from`` statement in ``a2ui.py`` names ``parrot``.

    A static (AST) check rather than a ``sys.modules`` deletion/reload dance —
    the latter would mutate process-global module identity for every other
    test in the same session (``parrot.outputs.a2ui`` classes reimported
    fresh would no longer ``is``-match ones already bound elsewhere).
    """
    import parrot_formdesigner.renderers.a2ui as a2ui_module

    tree = ast.parse(inspect.getsource(a2ui_module))
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith("parrot."), f"unexpected top-level import: {alias.name}"
        elif isinstance(node, ast.ImportFrom):
            module_name = node.module or ""
            assert not module_name.startswith("parrot."), f"unexpected top-level import: {module_name}"
