"""Unit tests for the A2UI Agent Functions runtime models (TASK-2568)."""

from datetime import UTC

import pytest
from parrot.outputs.a2ui.runtime.models import (
    A2UICallContext,
    A2UIErrorCode,
    DispatchResult,
    FunctionCallRecord,
    SurfaceState,
    error_envelope,
)


class TestErrorEnvelope:
    def test_generic_error_with_function_call_id(self):
        env = error_envelope(A2UIErrorCode.INTERNAL, "boom", function_call_id="fc-1")
        assert env == {
            "version": "v1.0",
            "error": {"code": "INTERNAL", "message": "boom", "functionCallId": "fc-1"},
        }

    def test_generic_error_rejects_both_ids(self):
        with pytest.raises(ValueError):
            error_envelope(A2UIErrorCode.INTERNAL, "boom", function_call_id="fc-1", surface_id="s-1")

    def test_generic_error_rejects_neither_id(self):
        with pytest.raises(ValueError):
            error_envelope(A2UIErrorCode.INTERNAL, "boom")

    def test_validation_code_requires_surface_and_path(self):
        with pytest.raises(ValueError):
            error_envelope(A2UIErrorCode.UNALLOWED_PARENT, "bad", function_call_id="fc-1")

    def test_validation_code_valid_shape(self):
        env = error_envelope(A2UIErrorCode.UNALLOWED_PARENT, "bad", surface_id="s-1", path="/components/0")
        assert env == {
            "version": "v1.0",
            "error": {
                "code": "UNALLOWED_PARENT",
                "message": "bad",
                "surfaceId": "s-1",
                "path": "/components/0",
            },
        }

    def test_never_hand_writes_version(self):
        assert error_envelope(A2UIErrorCode.NOT_FOUND, "x", function_call_id="f")["version"] == "v1.0"

    def test_error_envelope_validates_against_renderer_to_agent_schema(self):
        """Contract correction (2026-08-29): the wire's ``error`` message only
        exists in ``renderer_to_agent.json`` — ``A2UIAgentMessage`` has no
        ``error`` field at all, so it is structurally impossible to validate
        against ``agent_to_renderer.json``. See the task file's corrected AC."""
        from parrot.outputs.a2ui.catalog import validate_message
        from parrot.outputs.a2ui.serialization import deserialize

        env = error_envelope(A2UIErrorCode.NOT_FOUND, "not found", function_call_id="fc-1")
        message = deserialize(env)
        validate_message(message)


class TestRuntimeModels:
    def test_call_context_permission_context_is_opaque(self):
        ctx = A2UICallContext(
            agent_id="a",
            session_id="s",
            transport="http",
            permission_context=object(),
        )
        assert ctx.permission_context is not None

    def test_dispatch_result_defaults_empty(self):
        r = DispatchResult()
        assert r.messages == [] and r.user_turn is None and r.surface_state is None

    def test_function_call_record_defaults(self):
        from datetime import datetime

        record = FunctionCallRecord(function_call_id="fc-1", call="refreshChart", created_at=datetime.now(UTC))
        assert record.ttl_seconds == 900
        assert record.args == {}
        assert record.surface_id is None

    def test_surface_state_fields(self):
        from datetime import datetime

        state = SurfaceState(
            surface_id="s-1",
            catalog_id="https://parrot.dev/catalogs/v1",
            data_model={"count": 1},
            updated_at=datetime.now(UTC),
        )
        assert state.data_model == {"count": 1}


def test_runtime_models_do_not_import_agent_stack():
    """G8: runtime/ is pure protocol."""
    import parrot.outputs.a2ui.runtime.models as m

    with open(m.__file__) as f:
        src = f.read()
    for banned in ("from parrot.bots", "from parrot.clients", "from parrot.auth"):
        assert banned not in src
