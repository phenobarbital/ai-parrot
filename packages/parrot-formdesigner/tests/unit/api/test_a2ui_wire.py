"""Unit tests for ``api/a2ui_wire.py`` (FEAT-544, TASK-3074)."""

from __future__ import annotations

import ast
import inspect

import pytest
from aiohttp.test_utils import make_mocked_request

pytest.importorskip("parrot.outputs.a2ui")

from parrot_formdesigner.api import a2ui_wire
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType

from parrot.outputs.a2ui.catalog import validate_message
from parrot.outputs.a2ui.serialization import deserialize


def test_module_import_does_not_import_ai_parrot_eagerly():
    """No top-level ``import``/``from`` in ``a2ui_wire.py`` names ``parrot``.

    A static (AST) check — see ``test_a2ui_renderer.py``'s equivalent test
    for why a ``sys.modules`` delete/reload dance is avoided instead.
    """
    tree = ast.parse(inspect.getsource(a2ui_wire))
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith("parrot."), f"unexpected top-level import: {alias.name}"
        elif isinstance(node, ast.ImportFrom):
            module_name = node.module or ""
            assert not module_name.startswith("parrot."), f"unexpected top-level import: {module_name}"


@pytest.fixture
def sample_form() -> FormSchema:
    return FormSchema(
        form_id="demo",
        title="Demo",
        tenant="acme",
        sections=[
            FormSection(
                section_id="s",
                fields=[
                    FormField(field_id="name", field_type=FieldType.TEXT, label="Name", required=True),
                ],
            )
        ],
    )


def _action(form: FormSchema, answers: dict, *, in_data_model: bool = True, name: str = "form.submit") -> dict:
    action: dict = {
        "name": name,
        "surfaceId": f"form-{form.form_uid}",
        "sourceComponentId": "root-submit",
        "timestamp": "2026-09-10T00:00:00Z",
        "context": {"form_uid": str(form.form_uid)},
    }
    if in_data_model:
        action["dataModel"] = {"answers": answers}
    else:
        action["context"]["answers"] = answers
    return {"version": "v1.0", "action": action}


def test_is_a2ui_request_by_media_type_and_body_shape(sample_form):
    request = make_mocked_request("POST", "/x", headers={"Content-Type": "application/a2ui+json"})
    assert a2ui_wire.is_a2ui_request(request, {}) is True

    request = make_mocked_request("POST", "/x", headers={"Content-Type": "application/json"})
    assert a2ui_wire.is_a2ui_request(request, _action(sample_form, {"name": "Ada"})) is True

    assert a2ui_wire.is_a2ui_request(request, {"name": "Ada"}) is False


def test_unwrap_prefers_datamodel_over_context(sample_form):
    body = _action(sample_form, {"name": "Ada"}, in_data_model=True)
    body["action"]["context"]["answers"] = {"name": "Ignored"}
    submission = a2ui_wire.unwrap_action(sample_form, body)
    assert submission.answers == {"name": "Ada"}
    assert submission.surface_id == f"form-{sample_form.form_uid}"
    assert submission.action_name == "form.submit"
    assert submission.source_component_id == "root-submit"


def test_unwrap_falls_back_to_context_when_no_datamodel(sample_form):
    body = _action(sample_form, {"name": "Ada"}, in_data_model=False)
    submission = a2ui_wire.unwrap_action(sample_form, body)
    assert submission.answers == {"name": "Ada"}


def test_unwrap_unescapes_pointer_tokens(sample_form):
    body = _action(sample_form, {"na~1me": "value"}, in_data_model=True)
    submission = a2ui_wire.unwrap_action(sample_form, body)
    assert "na/me" in submission.answers


def test_unwrap_rejects_surface_mismatch(sample_form):
    body = _action(sample_form, {"name": "Ada"})
    body["action"]["surfaceId"] = "form-does-not-exist"
    with pytest.raises(a2ui_wire.A2UIWireError) as excinfo:
        a2ui_wire.unwrap_action(sample_form, body)
    assert excinfo.value.status == 400
    validate_message(deserialize(excinfo.value.envelope))


def test_unwrap_rejects_wrong_action_name(sample_form):
    body = _action(sample_form, {"name": "Ada"}, name="something.else")
    with pytest.raises(a2ui_wire.A2UIWireError) as excinfo:
        a2ui_wire.unwrap_action(sample_form, body)
    assert excinfo.value.status == 400


def test_unwrap_rejects_no_action():
    form = FormSchema(form_id="f", title="F", sections=[FormSection(section_id="s", fields=[])])
    body = {"version": "v1.0", "error": {"code": "INTERNAL", "message": "x", "functionCallId": "1"}}
    with pytest.raises(a2ui_wire.A2UIWireError) as excinfo:
        a2ui_wire.unwrap_action(form, body)
    assert excinfo.value.status == 400


def test_unwrap_rejects_answers_not_dict(sample_form):
    body = _action(sample_form, {}, in_data_model=True)
    body["action"]["dataModel"]["answers"] = ["not", "a", "dict"]
    with pytest.raises(a2ui_wire.A2UIWireError):
        a2ui_wire.unwrap_action(sample_form, body)


def test_validation_errors_shape_and_conformance():
    envelopes = a2ui_wire.validation_errors("form-x", {"name": ["Name is required."]})
    assert len(envelopes) == 2
    error_env = envelopes[0]
    assert error_env["error"]["code"] == "VALIDATION_FAILED"
    assert error_env["error"]["surfaceId"] == "form-x"
    assert error_env["error"]["path"] == "/answers/name"
    assert envelopes[1]["updateDataModel"]["path"] == "/errors"

    for envelope in envelopes:
        validate_message(deserialize(envelope))


def test_validation_errors_unknown_field_uses_answers_path():
    envelopes = a2ui_wire.validation_errors("form-x", {"__unknown__": ["Unexpected field."]})
    assert envelopes[0]["error"]["path"] == "/answers"


def test_confirmation_shape_and_conformance():
    result = {"submission_id": "sub-1", "is_valid": True, "forwarded": False, "forward_status": None}
    envelopes = a2ui_wire.confirmation("form-x", result)
    assert len(envelopes) == 2
    assert envelopes[0]["updateDataModel"]["path"] == "/submission"
    assert envelopes[0]["updateDataModel"]["value"]["submission_id"] == "sub-1"

    components = envelopes[1]["updateComponents"]["components"]
    assert len(components) == 1
    assert components[0]["id"] == "root-status"
    assert components[0]["metadata"]["extensions"]["parrot_role"] == "status"
    assert components[0]["metadata"]["extensions"]["parrot_state"] == "submitted"

    for envelope in envelopes:
        validate_message(deserialize(envelope))


def test_a2ui_response_framing():
    single = a2ui_wire.a2ui_response([{"version": "v1.0", "error": {}}], status=400)
    assert single.content_type == "application/a2ui+json"

    many = a2ui_wire.a2ui_response(
        [{"version": "v1.0", "error": {}}, {"version": "v1.0", "error": {}}], status=422
    )
    assert many.content_type == "application/json"

    empty = a2ui_wire.a2ui_response([], status=200)
    assert empty.content_type == "application/json"


def test_import_without_ai_parrot(monkeypatch):
    """``is_a2ui_request`` returns False (never raises) when ai-parrot is unavailable."""
    import builtins

    real_import = builtins.__import__

    def _blocking_import(name, *args, **kwargs):
        if name == "parrot.a2a.models" or name.startswith("parrot.a2a"):
            raise ImportError("simulated: ai-parrot not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _blocking_import)
    request = make_mocked_request("POST", "/x", headers={"Content-Type": "application/a2ui+json"})
    assert a2ui_wire.is_a2ui_request(request, {}) is False
