"""Unit tests for ``A2UIRuntime.dispatch``/``call_renderer`` (TASK-2569)."""

from __future__ import annotations

import json

import pytest
from parrot.outputs.a2ui.catalog import DEFAULT_CATALOG_ID, FunctionDefinition
from parrot.outputs.a2ui.runtime.dispatch import A2UI_MAX_DATA_MODEL_BYTES, A2UIRuntime

pytestmark = pytest.mark.asyncio


def _call_agent_function_envelope(**overrides):
    env = {
        "version": "v1.0",
        "callAgentFunction": {
            "surfaceId": "s-1",
            "functionCallId": "fc-1",
            "callFunction": {
                "call": "get_weather",
                "args": {"location": "Caracas"},
                "catalogId": DEFAULT_CATALOG_ID,
            },
        },
    }
    env["callAgentFunction"].update(overrides)
    return env


def _action_envelope(**overrides):
    action = {
        "name": "submit",
        "surfaceId": "s-1",
        "sourceComponentId": "btn-1",
        "timestamp": "2026-08-29T10:00:00Z",
        "context": {},
    }
    action.update(overrides)
    return {"version": "v1.0", "action": action}


class TestEnvelopeGuards:
    async def test_rejects_multi_key_envelope(self, runtime, fake_executor, a2ui_call_ctx):
        env = {
            "version": "v1.0",
            "action": {
                "name": "x",
                "surfaceId": "s-1",
                "sourceComponentId": "c-1",
                "timestamp": "2026-08-29T10:00:00Z",
                "context": {},
            },
            "callAgentFunction": {
                "surfaceId": "s-1",
                "functionCallId": "fc-1",
                "callFunction": {"call": "get_weather", "args": {}},
            },
        }
        res = await runtime.dispatch(env, a2ui_call_ctx)
        assert res.messages[0]["error"]["code"] == "INVALID_FUNCTION_CALL"
        assert fake_executor.calls == []

    async def test_rejects_zero_key_envelope(self, runtime, fake_executor, a2ui_call_ctx):
        res = await runtime.dispatch({"version": "v1.0"}, a2ui_call_ctx)
        assert res.messages[0]["error"]["code"] == "INVALID_FUNCTION_CALL"
        assert fake_executor.calls == []

    async def test_rejects_agent_to_renderer_key(self, runtime, fake_executor, a2ui_call_ctx):
        env = {"version": "v1.0", "createSurface": {"surfaceId": "s-1"}}
        res = await runtime.dispatch(env, a2ui_call_ctx)
        assert res.messages[0]["error"]["code"] == "INVALID_FUNCTION_CALL"
        assert fake_executor.calls == []

    async def test_rejects_wrong_version(self, runtime, fake_executor, a2ui_call_ctx):
        env = _action_envelope()
        env["version"] = "0.9"
        res = await runtime.dispatch(env, a2ui_call_ctx)
        assert res.messages[0]["error"]["code"] == "INVALID_FUNCTION_CALL"
        assert fake_executor.calls == []


class TestCallAgentFunction:
    async def test_success_echoes_function_call_id(self, runtime, a2ui_call_ctx):
        res = await runtime.dispatch(_call_agent_function_envelope(), a2ui_call_ctx)
        assert res.messages[0]["agentFunctionResponse"]["functionCallId"] == "fc-1"
        assert res.messages[0]["agentFunctionResponse"]["value"] == {"ok": 1}

    async def test_forbidden_maps_to_FORBIDDEN(self, runtime_forbidden, a2ui_call_ctx):
        res = await runtime_forbidden.dispatch(_call_agent_function_envelope(), a2ui_call_ctx)
        assert res.messages[0]["error"]["code"] == "FORBIDDEN"

    async def test_not_found_maps_to_INVALID_FUNCTION_CALL(self, runtime_missing, a2ui_call_ctx):
        res = await runtime_missing.dispatch(_call_agent_function_envelope(), a2ui_call_ctx)
        assert res.messages[0]["error"]["code"] == "INVALID_FUNCTION_CALL"

    async def test_exception_maps_to_INTERNAL_without_traceback(self, runtime_raises, a2ui_call_ctx):
        res = await runtime_raises.dispatch(_call_agent_function_envelope(), a2ui_call_ctx)
        msg = res.messages[0]["error"]["message"]
        assert res.messages[0]["error"]["code"] == "INTERNAL"
        assert "secret internal detail" not in msg
        assert "Traceback" not in msg

    async def test_renderer_only_function_rejected(self, fake_surfaces, fake_pending, a2ui_call_ctx):
        from tests.outputs.a2ui.runtime.conftest import FakeExecutor

        executor = FakeExecutor(
            mode="success",
            functions=[
                FunctionDefinition(name="get_weather", catalog_id=DEFAULT_CATALOG_ID, allowed_callers="rendererOnly")
            ],
        )
        runtime = A2UIRuntime(executor=executor, surfaces=fake_surfaces, pending=fake_pending)
        res = await runtime.dispatch(_call_agent_function_envelope(), a2ui_call_ctx)
        assert res.messages[0]["error"]["code"] == "INVALID_FUNCTION_CALL"
        assert executor.calls == []

    async def test_catalog_resolution_precedence(self, fake_executor, fake_surfaces, fake_pending, a2ui_call_ctx):
        runtime = A2UIRuntime(executor=fake_executor, surfaces=fake_surfaces, pending=fake_pending)

        # Neither explicit catalogId nor a known surface -> error, executor not called.
        env_no_catalog = _call_agent_function_envelope()
        del env_no_catalog["callAgentFunction"]["callFunction"]["catalogId"]
        res = await runtime.dispatch(env_no_catalog, a2ui_call_ctx)
        assert res.messages[0]["error"]["code"] == "INVALID_FUNCTION_CALL"
        assert fake_executor.calls == []

        # Explicit catalogId on the call resolves it even with no known surface.
        res = await runtime.dispatch(_call_agent_function_envelope(), a2ui_call_ctx)
        assert res.messages[0]["agentFunctionResponse"]["functionCallId"] == "fc-1"


class TestAction:
    async def test_persists_data_model_and_sets_user_turn(self, runtime, fake_surfaces, a2ui_call_ctx):
        env = _action_envelope(userMessage="Clicked submit", dataModel={"count": 3})
        res = await runtime.dispatch(env, a2ui_call_ctx)
        assert len(fake_surfaces.put_calls) == 1
        assert res.surface_state is not None
        assert res.surface_state.data_model == {"count": 3}
        assert res.user_turn == "Clicked submit"

    async def test_without_data_model_does_not_touch_store(self, runtime, fake_surfaces, a2ui_call_ctx):
        res = await runtime.dispatch(_action_envelope(userMessage="hi"), a2ui_call_ctx)
        assert fake_surfaces.put_calls == []
        assert res.surface_state is None

    async def test_oversized_data_model_errors_and_preserves_state(self, runtime, fake_surfaces, a2ui_call_ctx):
        big = {"blob": "x" * (A2UI_MAX_DATA_MODEL_BYTES + 10)}
        env = _action_envelope(dataModel=big)
        res = await runtime.dispatch(env, a2ui_call_ctx)
        assert res.messages[0]["error"]["code"] == "INTERNAL"
        assert fake_surfaces.put_calls == []

    async def test_user_message_absent_yields_system_turn(self, runtime, a2ui_call_ctx):
        res = await runtime.dispatch(_action_envelope(), a2ui_call_ctx)
        parsed = json.loads(res.user_turn)
        assert parsed["type"] == "a2ui_action"
        assert parsed["action"]["action"]["name"] == "submit"

    async def test_data_model_never_leaks_into_turn_text(self, runtime, a2ui_call_ctx):
        env = _action_envelope(dataModel={"secret": "value"})
        res = await runtime.dispatch(env, a2ui_call_ctx)
        assert "secret" not in res.user_turn
        assert "value" not in res.user_turn

        env2 = _action_envelope(userMessage="visible", dataModel={"secret2": "v2"})
        res2 = await runtime.dispatch(env2, a2ui_call_ctx)
        assert res2.user_turn == "visible"
        assert "secret2" not in res2.user_turn


class TestRendererCalls:
    async def test_call_renderer_registers_pending_and_sets_catalog_id(self, runtime, fake_pending):
        function_call_id, envelope = await runtime.call_renderer("s-1", "surface-1", "refreshChart", {"x": 1})
        assert envelope["callRendererFunction"]["functionCallId"] == function_call_id
        assert envelope["callRendererFunction"]["callFunction"]["catalogId"] == DEFAULT_CATALOG_ID
        assert ("s-1", function_call_id) in fake_pending._store

    async def test_response_resolves_pending(self, runtime, fake_pending, a2ui_call_ctx):
        function_call_id, _ = await runtime.call_renderer(a2ui_call_ctx.session_id, "surface-1", "refreshChart", {})
        env = {
            "version": "v1.0",
            "rendererFunctionResponse": {"functionCallId": function_call_id, "value": {"done": True}},
        }
        res = await runtime.dispatch(env, a2ui_call_ctx)
        assert res.messages == []
        assert (a2ui_call_ctx.session_id, function_call_id) not in fake_pending._store

    async def test_unknown_function_call_id_is_not_found(self, runtime, a2ui_call_ctx):
        env = {
            "version": "v1.0",
            "rendererFunctionResponse": {"functionCallId": "nope", "value": {}},
        }
        res = await runtime.dispatch(env, a2ui_call_ctx)
        assert res.messages[0]["error"]["code"] == "NOT_FOUND"


class TestConformance:
    async def test_agent_function_response_validates_against_agent_to_renderer_schema(self, runtime, a2ui_call_ctx):
        from parrot.outputs.a2ui.catalog import validate_message
        from parrot.outputs.a2ui.serialization import deserialize

        res = await runtime.dispatch(_call_agent_function_envelope(), a2ui_call_ctx)
        validate_message(deserialize(res.messages[0]))

    async def test_error_envelope_validates_against_renderer_to_agent_schema(self, runtime_forbidden, a2ui_call_ctx):
        from parrot.outputs.a2ui.catalog import validate_message
        from parrot.outputs.a2ui.serialization import deserialize

        res = await runtime_forbidden.dispatch(_call_agent_function_envelope(), a2ui_call_ctx)
        validate_message(deserialize(res.messages[0]))

    async def test_call_renderer_envelope_validates_against_agent_to_renderer_schema(self, runtime):
        from parrot.outputs.a2ui.catalog import validate_message
        from parrot.outputs.a2ui.serialization import deserialize

        # Uses a Basic Catalog function name ("openUrl"), not the custom RPC
        # names used elsewhere in this file ("refreshChart"/"get_weather").
        # The vendored `FunctionCall` schema (`common_types.json#/$defs/
        # FunctionCall`) constrains `call` via a `oneOf` against
        # `catalog.json#/$defs/anyFunction` (the Basic Catalog's own ~14
        # functions) — a custom tool name can never satisfy that `oneOf`, so
        # jsonschema conformance for a `callRendererFunction`/
        # `callAgentFunction`/`agentFunctionResponse` carrying a real
        # ToolManager function name is structurally unverifiable against
        # this vendored file. This test instead proves the *envelope shape*
        # (functionCallId + required catalogId) is conformant using a name
        # the schema can actually resolve.
        _, envelope = await runtime.call_renderer("s-1", "surface-1", "openUrl", {"url": "https://example.com"})
        validate_message(deserialize(envelope))
