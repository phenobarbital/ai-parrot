"""A2UI wire helpers for the form endpoints (FEAT-544, TASK-3074).

Spec: ``sdd/specs/a2ui-form-output-renderer.spec.md``, §3 Module 4.

Pure helper module the form endpoints (``FormAPIHandler.submit_data`` /
``.validate``, TASK-3075/3076) call to detect an inbound A2UI v1.0
renderer->agent ``action`` envelope, unwrap it into field_id-keyed answers,
and build the outbound A2UI replies. Framing mirrors ``A2UIHandler``
(``ai-parrot-server/handlers/a2ui.py``): a single envelope is the response
body; several are wrapped as ``{"messages": [...]}``.

``ai-parrot`` (and therefore ``parrot.outputs.a2ui``) is an OPTIONAL
dependency of parrot-formdesigner — every ``parrot.*`` symbol is imported
lazily, inside :func:`_a2ui_ns`. :func:`is_a2ui_request` in particular must
NEVER raise: it returns ``False`` (the legacy JSON path) whenever
``parrot.outputs.a2ui`` is not importable.
"""

from __future__ import annotations

import os
from typing import Any

from aiohttp import web
from pydantic import BaseModel

from ..core.schema import FormSchema
from ..renderers.a2ui import field_id_from_pointer_token, field_pointer

#: Action names this wire understands (spec §2 Overview).
A2UI_SUBMIT_ACTION = "form.submit"
A2UI_VALIDATE_ACTION = "form.validate"
A2UI_CANCEL_ACTION = "form.cancel"

#: Same cap (and same env var) as `A2UIRuntime`'s data-model size guard
#: (`parrot.outputs.a2ui.runtime.dispatch.A2UI_MAX_DATA_MODEL_BYTES`) — the
#: form receiver applies it to inbound A2UI request bodies (spec §7 "Known
#: Risks" — enforcement lives in the handlers that call this module).
A2UI_MAX_BODY_BYTES = int(os.environ.get("A2UI_MAX_DATA_MODEL_BYTES", str(1024 * 1024)))


class A2UIActionSubmission(BaseModel):
    """Answers unwrapped from an inbound A2UI ``action`` envelope.

    Attributes:
        surface_id: The surface the action originated from.
        action_name: ``"form.submit"`` or ``"form.validate"``.
        source_component_id: The component that triggered the event.
        answers: field_id-keyed answers (JSON-Pointer tokens unescaped).
        raw_context: The action's raw ``context`` dict, for callers that
            need something beyond ``answers`` (e.g. ``form_uid``).
    """

    surface_id: str
    action_name: str
    source_component_id: str
    answers: dict[str, Any]
    raw_context: dict[str, Any]


class A2UIWireError(Exception):
    """Raised when an inbound A2UI envelope cannot be unwrapped.

    Attributes:
        status: The HTTP status the caller should reply with.
        envelope: A ready-to-serialize generic A2UI ``error`` envelope
            (``{"version": "v1.0", "error": {...}}``).
    """

    def __init__(self, status: int, envelope: dict[str, Any]) -> None:
        message = envelope.get("error", {}).get("message", "A2UI wire error")
        super().__init__(message)
        self.status = status
        self.envelope = envelope


def _a2ui_ns() -> Any:
    """Lazily import the ai-parrot A2UI stack this module depends on.

    Returns:
        A namespace object exposing the required ``parrot.outputs.a2ui`` /
        ``parrot.a2a`` symbols as attributes.

    Raises:
        RuntimeError: If ``ai-parrot`` (the optional extra) is not installed.
    """
    try:
        from parrot.a2a.models import A2UI_MEDIA_TYPE
        from parrot.outputs.a2ui.models import (
            A2UIRendererMessage,
            Component,
            ComponentMetadata,
            ErrorMessage,
            Extensions,
            UpdateComponents,
            UpdateDataModel,
        )
        from parrot.outputs.a2ui.runtime.models import A2UIErrorCode, error_envelope
        from parrot.outputs.a2ui.serialization import deserialize, serialize
    except ImportError as exc:
        raise RuntimeError("a2ui_wire requires the 'ai-parrot' extra") from exc

    class _A2UIWireNamespace:
        pass

    ns = _A2UIWireNamespace()
    ns.A2UI_MEDIA_TYPE = A2UI_MEDIA_TYPE
    ns.A2UIRendererMessage = A2UIRendererMessage
    ns.Component = Component
    ns.ComponentMetadata = ComponentMetadata
    ns.ErrorMessage = ErrorMessage
    ns.Extensions = Extensions
    ns.UpdateComponents = UpdateComponents
    ns.UpdateDataModel = UpdateDataModel
    ns.A2UIErrorCode = A2UIErrorCode
    ns.error_envelope = error_envelope
    ns.deserialize = deserialize
    ns.serialize = serialize
    return ns


def is_a2ui_request(request: web.Request, body: Any) -> bool:
    """Detect whether an inbound request is speaking the A2UI wire.

    True when ``Content-Type: application/a2ui+json``, OR the JSON body's
    top level is ``{"version": "v1.0", "action": {...}}``. Anything else
    (including ai-parrot being unavailable) is the legacy JSON path.

    Args:
        request: The incoming aiohttp request.
        body: The already-parsed JSON body (``dict`` for the legacy path).

    Returns:
        ``True`` if this is an A2UI request, else ``False``. Never raises.
    """
    try:
        from parrot.a2a.models import A2UI_MEDIA_TYPE
    except ImportError:
        return False

    if request.content_type == A2UI_MEDIA_TYPE:
        return True
    return isinstance(body, dict) and body.get("version") == "v1.0" and "action" in body


def _malformed(form: FormSchema, message: str) -> A2UIWireError:
    """Build a generic 400 ``A2UIWireError`` for a malformed inbound envelope."""
    m = _a2ui_ns()
    surface_id = f"form-{form.form_uid}"
    return A2UIWireError(400, m.error_envelope(m.A2UIErrorCode.INVALID_FUNCTION_CALL, message, surface_id=surface_id))


def _surface_mismatch(incoming_surface_id: str) -> A2UIWireError:
    """Build a generic 400 ``A2UIWireError`` for a surfaceId that doesn't match this form."""
    m = _a2ui_ns()
    return A2UIWireError(
        400,
        m.error_envelope(
            m.A2UIErrorCode.NOT_FOUND, "Unknown surface for this form.", surface_id=incoming_surface_id
        ),
    )


def unwrap_action(form: FormSchema, body: dict[str, Any]) -> A2UIActionSubmission:
    """Unwrap an inbound A2UI ``action`` envelope into field_id-keyed answers.

    Args:
        form: The form the envelope is submitted against (its ``form_uid``
            determines the expected ``surfaceId``).
        body: The parsed request body (an A2UI v1.0 envelope dict).

    Returns:
        The unwrapped :class:`A2UIActionSubmission`.

    Raises:
        A2UIWireError: (status 400) on a malformed envelope, a missing/
            wrong-named action, a surfaceId mismatch, or non-dict answers.
    """
    m = _a2ui_ns()

    try:
        msg = m.deserialize(body)
    except Exception as exc:  # noqa: BLE001 - any deserialize failure is a 400
        raise _malformed(form, "Malformed A2UI envelope.") from exc

    if not isinstance(msg, m.A2UIRendererMessage) or msg.action is None:
        raise _malformed(form, "Expected an A2UI 'action' message.")

    action = msg.action
    expected_surface_id = f"form-{form.form_uid}"
    if action.surface_id != expected_surface_id:
        raise _surface_mismatch(action.surface_id)

    if action.name not in (A2UI_SUBMIT_ACTION, A2UI_VALIDATE_ACTION):
        raise _malformed(form, f"Unsupported action {action.name!r}.")

    if action.data_model is not None and "answers" in action.data_model:
        raw_answers = action.data_model["answers"]
    else:
        raw_answers = action.context.get("answers", {})

    if not isinstance(raw_answers, dict):
        raise _malformed(form, "'answers' must be an object.")

    declared_field_ids = {field.field_id for field in form.iter_all_fields()}
    answers: dict[str, Any] = {}
    for token, value in raw_answers.items():
        field_id = field_id_from_pointer_token(token)
        if value is None and field_id not in declared_field_ids:
            continue
        answers[field_id] = value

    return A2UIActionSubmission(
        surface_id=action.surface_id,
        action_name=action.name,
        source_component_id=action.source_component_id,
        answers=answers,
        raw_context=action.context,
    )


def validation_errors(surface_id: str, errors: dict[str, list[str] | str]) -> list[dict[str, Any]]:
    """Build the A2UI reply for a 422 (per-field errors + a data-model update).

    Args:
        surface_id: The surface to address the errors to.
        errors: field_id -> message(s). ``"__unknown__"`` (unknown-field
            rejections) and ``"_metadata"`` address ``path == "/answers"``.

    Returns:
        One ``error{code: "VALIDATION_FAILED"}`` envelope per field, plus a
        trailing ``updateDataModel{path: "/errors"}`` envelope.
    """
    m = _a2ui_ns()
    envelopes: list[dict[str, Any]] = []

    for field_id, messages in errors.items():
        text = "; ".join(messages) if isinstance(messages, list) else str(messages)
        path = "/answers" if field_id in ("__unknown__", "_metadata") else field_pointer(field_id)
        envelopes.append(
            m.serialize(m.ErrorMessage(code="VALIDATION_FAILED", surface_id=surface_id, path=path, message=text))
        )

    envelopes.append(m.serialize(m.UpdateDataModel(surface_id=surface_id, path="/errors", value=errors)))
    return envelopes


def confirmation(surface_id: str, result: dict[str, Any], *, message: str = "Form submitted.") -> list[dict[str, Any]]:
    """Build the A2UI reply for a 200 (submission summary + status update).

    Args:
        surface_id: The surface to address the confirmation to.
        result: The legacy submit result dict — only ``submission_id``,
            ``is_valid``, ``forwarded``, and ``forward_status`` are echoed.
        message: The confirmation text for the ``root-status`` ``Text``.

    Returns:
        An ``updateDataModel{path: "/submission"}`` envelope, followed by an
        ``updateComponents`` envelope replacing ``root-status``.
    """
    m = _a2ui_ns()
    submission_value = {key: result.get(key) for key in ("submission_id", "is_valid", "forwarded", "forward_status")}
    status_component = m.Component(
        id="root-status",
        component="Text",
        text=message,
        metadata=m.ComponentMetadata(extensions=m.Extensions({"parrot_role": "status", "parrot_state": "submitted"})),
    )
    return [
        m.serialize(m.UpdateDataModel(surface_id=surface_id, path="/submission", value=submission_value)),
        m.serialize(m.UpdateComponents(surface_id=surface_id, components=[status_component])),
    ]


def a2ui_response(envelopes: list[dict[str, Any]], *, status: int) -> web.Response:
    """Frame one or more A2UI envelopes into an aiohttp response.

    A single envelope is returned as the body with
    ``Content-Type: application/a2ui+json``; several (or zero) are wrapped
    as ``{"messages": [...]}`` with ``Content-Type: application/json``
    (mirrors ``A2UIHandler``'s framing).

    Args:
        envelopes: The envelopes to send (each already ``serialize()``d).
        status: The HTTP status code for the response.

    Returns:
        The framed ``web.Response``.
    """
    if len(envelopes) == 1:
        m = _a2ui_ns()
        return web.json_response(envelopes[0], status=status, content_type=m.A2UI_MEDIA_TYPE)
    return web.json_response({"messages": envelopes}, status=status)
