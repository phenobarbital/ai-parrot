"""A2UI Agent Functions runtime — v1.0 wire conformance sweep (FEAT-469 TASK-2576).

Every A->R envelope the runtime EMITS must validate against the vendored
``agent_to_renderer.json``; every R->A envelope it ACCEPTS must validate
against ``renderer_to_agent.json`` (spec §5 Acceptance Criteria). Uses the
SAME two-step ``jsonschema`` path ``catalog.validate_message`` uses
internally (``Draft202012Validator(schema, registry=schema_registry())``) —
the vendored schemas ``$ref`` into ``common_types.json``/``catalog.json``,
so validating without the registry would fail to resolve those refs.

Function-name restriction (confirmed in TASK-2569/2571's own completion
notes): ``common_types.json#/$defs/FunctionCall`` constrains ``call`` via a
``oneOf`` against ``catalog.json#/$defs/anyFunction`` — the ~14 Basic
Catalog functions only. A custom ToolManager tool name (``get_weather``)
can never satisfy that ``oneOf``. Envelopes carrying a ``FunctionCall``
(``callAgentFunction``, ``callRendererFunction``) therefore use a Basic
Catalog function name (``openUrl``) here — this sweep proves *envelope
shape* conformance, not that arbitrary tool names pass a schema that
structurally cannot express them (already documented as a vendored-schema
limitation, not a defect, in TASK-2569's completion note).
"""

from __future__ import annotations

import pytest

jsonschema = pytest.importorskip("jsonschema")

from parrot.outputs.a2ui.catalog.basic import schema_registry


def _validate(schema: dict, payload: dict) -> None:
    validator_cls = jsonschema.validators.validator_for(schema)
    validator_cls(schema, registry=schema_registry()).validate(payload)


# ---------------------------------------------------------------------------
# Agent -> Renderer envelopes the runtime emits
# ---------------------------------------------------------------------------

AGENT_TO_RENDERER_ENVELOPES = [
    pytest.param(
        {"version": "v1.0", "agentFunctionResponse": {"functionCallId": "fc-1", "value": {"ok": True}}},
        id="agentFunctionResponse-success",
    ),
    pytest.param(
        {
            "version": "v1.0",
            "agentFunctionResponse": {
                "functionCallId": "fc-1",
                "error": {"code": "FORBIDDEN", "message": "denied"},
            },
        },
        id="agentFunctionResponse-error",
    ),
    pytest.param(
        {
            "version": "v1.0",
            "callRendererFunction": {
                "functionCallId": "fc-2",
                "callFunction": {"call": "openUrl", "args": {"url": "https://x"}, "catalogId": "https://a2ui.org/specification/v1_0/catalog.json"},
            },
        },
        id="callRendererFunction-with-catalogId",
    ),
]


@pytest.mark.parametrize("envelope", AGENT_TO_RENDERER_ENVELOPES)
def test_agent_to_renderer_conformance(envelope, v1_schemas):
    _validate(v1_schemas["agent_to_renderer"], envelope)


def test_call_renderer_function_requires_catalog_id(v1_schemas):
    """Stricter than the shared pydantic FunctionCall model — jsonschema-only gap."""
    with pytest.raises(jsonschema.ValidationError):
        _validate(
            v1_schemas["agent_to_renderer"],
            {
                "version": "v1.0",
                "callRendererFunction": {
                    "functionCallId": "fc-2",
                    "callFunction": {"call": "openUrl", "args": {"url": "https://x"}},  # no catalogId
                },
            },
        )


# ---------------------------------------------------------------------------
# Renderer -> Agent envelopes the runtime accepts
# ---------------------------------------------------------------------------

RENDERER_TO_AGENT_ENVELOPES = [
    pytest.param(
        {
            "version": "v1.0",
            "action": {
                "name": "submit",
                "surfaceId": "s-1",
                "sourceComponentId": "btn-1",
                "timestamp": "2026-08-29T10:00:00Z",
                "context": {},
            },
        },
        id="action-without-dataModel",
    ),
    pytest.param(
        {
            "version": "v1.0",
            "action": {
                "name": "submit",
                "surfaceId": "s-1",
                "sourceComponentId": "btn-1",
                "timestamp": "2026-08-29T10:00:00Z",
                "context": {},
                "dataModel": {"rows": [1, 2, 3]},
            },
        },
        id="action-with-dataModel",
    ),
    pytest.param(
        {
            "version": "v1.0",
            "callAgentFunction": {
                "surfaceId": "s-1",
                "functionCallId": "fc-1",
                "callFunction": {"call": "openUrl", "args": {"url": "https://x"}},
            },
        },
        id="callAgentFunction",
    ),
    pytest.param(
        {"version": "v1.0", "rendererFunctionResponse": {"functionCallId": "fc-2", "value": {"done": True}}},
        id="rendererFunctionResponse-success",
    ),
    pytest.param(
        {
            "version": "v1.0",
            "rendererFunctionResponse": {
                "functionCallId": "fc-2",
                "error": {"code": "TIMEOUT", "message": "no response"},
            },
        },
        id="rendererFunctionResponse-error",
    ),
    pytest.param(
        {
            "version": "v1.0",
            "error": {"code": "UNALLOWED_PARENT", "surfaceId": "s-1", "path": "/components/0", "message": "bad"},
        },
        id="error-validation-shape",
    ),
    pytest.param(
        {"version": "v1.0", "error": {"code": "NOT_FOUND", "functionCallId": "fc-9", "message": "unknown"}},
        id="error-generic-shape",
    ),
]


@pytest.mark.parametrize("envelope", RENDERER_TO_AGENT_ENVELOPES)
def test_renderer_to_agent_conformance(envelope, v1_schemas):
    _validate(v1_schemas["renderer_to_agent"], envelope)


def test_call_agent_function_rejects_data_model(v1_schemas):
    """additionalProperties: false on callAgentFunction (TASK-2567)."""
    with pytest.raises(jsonschema.ValidationError):
        _validate(
            v1_schemas["renderer_to_agent"],
            {
                "version": "v1.0",
                "callAgentFunction": {
                    "surfaceId": "s",
                    "functionCallId": "f",
                    "callFunction": {"call": "openUrl", "args": {}},
                    "dataModel": {},
                },
            },
        )


def test_action_accepts_data_model(v1_schemas):
    """No additionalProperties key on `action` -> defaults to true (TASK-2567)."""
    _validate(
        v1_schemas["renderer_to_agent"],
        {
            "version": "v1.0",
            "action": {
                "name": "submit",
                "surfaceId": "s-1",
                "sourceComponentId": "btn-1",
                "timestamp": "2026-08-29T10:00:00Z",
                "context": {},
                "dataModel": {"any": "shape"},
            },
        },
    )


def test_error_validation_shape_requires_surface_and_path(v1_schemas):
    with pytest.raises(jsonschema.ValidationError):
        _validate(
            v1_schemas["renderer_to_agent"],
            {"version": "v1.0", "error": {"code": "UNALLOWED_PARENT", "message": "bad"}},
        )


def test_error_generic_shape_requires_exactly_one_id(v1_schemas):
    with pytest.raises(jsonschema.ValidationError):
        _validate(
            v1_schemas["renderer_to_agent"],
            {
                "version": "v1.0",
                "error": {
                    "code": "NOT_FOUND",
                    "message": "x",
                    "surfaceId": "s-1",
                    "functionCallId": "fc-1",
                },
            },
        )
    with pytest.raises(jsonschema.ValidationError):
        _validate(
            v1_schemas["renderer_to_agent"],
            {"version": "v1.0", "error": {"code": "NOT_FOUND", "message": "x"}},
        )


# ---------------------------------------------------------------------------
# Runtime-produced envelopes, exercised through the real dispatch path
# ---------------------------------------------------------------------------


class TestRuntimeProducedEnvelopesConformance:
    """Round-trips REAL `A2UIRuntime` output through the sweep above's validator.

    Complements the static parametrized cases: proves the actual
    `error_envelope()`/`serialize()` output — not a hand-built dict — is
    conformant too.
    """

    def test_error_envelope_helper_output_conforms(self, v1_schemas):
        from parrot.outputs.a2ui.runtime.models import A2UIErrorCode, error_envelope

        env = error_envelope(A2UIErrorCode.FORBIDDEN, "denied", function_call_id="fc-1")
        _validate(v1_schemas["renderer_to_agent"], env)

    async def test_dispatch_agent_function_response_conforms(self, v1_schemas):

        from parrot.outputs.a2ui.catalog.base import FunctionDefinition
        from parrot.outputs.a2ui.runtime.dispatch import A2UIRuntime
        from parrot.outputs.a2ui.runtime.models import A2UICallContext
        from parrot.tools.abstract import ToolResult

        class _Executor:
            def __init__(self):
                self.calls = []

            async def call(self, name, args, ctx):
                self.calls.append((name, args))
                return ToolResult(success=True, status="success", result={"ok": 1})

            def list_functions(self):
                return [
                    FunctionDefinition(
                        name="openUrl",
                        catalog_id="https://a2ui.org/specification/v1_0/catalog.json",
                        allowed_callers="rendererOrAgent",
                    )
                ]

        class _Store:
            async def get(self, session_id, surface_id):
                return None

            async def put(self, session_id, state):
                pass

            async def delete(self, session_id, surface_id):
                pass

            async def add(self, session_id, record):
                pass

            async def resolve(self, session_id, function_call_id, value, error):
                return None

        store = _Store()
        runtime = A2UIRuntime(
            executor=_Executor(), surfaces=store, pending=store, catalog_id="https://a2ui.org/specification/v1_0/catalog.json"
        )
        ctx = A2UICallContext(agent_id="a", session_id="s", transport="http", permission_context=None)
        env = {
            "version": "v1.0",
            "callAgentFunction": {
                "surfaceId": "s-1",
                "functionCallId": "fc-1",
                "callFunction": {
                    "call": "openUrl",
                    "args": {"url": "https://x"},
                    "catalogId": "https://a2ui.org/specification/v1_0/catalog.json",
                },
            },
        }
        result = await runtime.dispatch(env, ctx)
        assert len(result.messages) == 1
        _validate(v1_schemas["agent_to_renderer"], result.messages[0])
