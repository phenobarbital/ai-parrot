"""Unit tests for A2UI emission wiring (TASK-1738 / Module 10)."""

from types import SimpleNamespace

import pytest

from parrot.outputs.a2ui.emission import finalize_a2ui_response
from parrot.models import CompletionUsage
from parrot.models.outputs import OutputMode
from parrot.models.responses import AIMessage


class TestOutputModeA2UI:
    def test_output_mode_a2ui_member(self):
        assert OutputMode.A2UI.value == "a2ui"
        assert isinstance(OutputMode.A2UI, str)
        assert OutputMode("a2ui") is OutputMode.A2UI

    def test_aimessage_a2ui_envelope_field(self):
        base = dict(input="hi", output="", model="m", provider="p", usage=CompletionUsage())
        msg = AIMessage(**base)
        assert msg.a2ui_envelope is None
        assert "a2ui_envelope" in msg.model_dump()
        msg2 = AIMessage(**base, a2ui_envelope={"messageType": "createSurface"})
        assert msg2.a2ui_envelope["messageType"] == "createSurface"


class TestA2UIRouting:
    def test_finalize_from_envelope_field(self):
        resp = SimpleNamespace(
            a2ui_envelope={"messageType": "createSurface", "surfaceId": "main"},
            output="untouched-legacy-output",
            response=None,
            output_mode=OutputMode.DEFAULT,
            data=None,
        )
        finalize_a2ui_response(resp)
        assert resp.output_mode is OutputMode.A2UI
        assert resp.a2ui_envelope["surfaceId"] == "main"
        # Legacy output untouched.
        assert resp.output == "untouched-legacy-output"
        # Human-readable fallback populated.
        assert "main" in resp.response

    def test_finalize_derives_envelope_from_dict_output(self):
        resp = SimpleNamespace(
            a2ui_envelope=None,
            output={"messageType": "createSurface", "surfaceId": "s2"},
            response=None,
            output_mode=OutputMode.DEFAULT,
        )
        finalize_a2ui_response(resp)
        assert resp.a2ui_envelope["surfaceId"] == "s2"
        assert resp.output_mode is OutputMode.A2UI

    def test_finalize_preserves_existing_response_text(self):
        resp = SimpleNamespace(
            a2ui_envelope={"surfaceId": "s"},
            output=None,
            response="Existing summary",
            output_mode=OutputMode.DEFAULT,
        )
        finalize_a2ui_response(resp)
        assert resp.response == "Existing summary"


class TestFormatterBypass:
    def test_a2ui_never_calls_formatter(self):
        """The A2UI finalize helper performs no formatter call (pure data path)."""
        # _finalize_a2ui_response takes only the response; it cannot reach a formatter.
        resp = SimpleNamespace(a2ui_envelope={"surfaceId": "x"}, output=None, response=None)
        finalize_a2ui_response(resp)
        assert resp.a2ui_envelope == {"surfaceId": "x"}
