"""FEAT-473 TASK-2565 — non-stream a2ui_envelope passthrough contract.

Mirrors ``test_agent_a2ui_stream.py``'s own source-inspection convention (the
handler pulls in a Cython-adjacent import chain that isn't guaranteed
importable in every environment): the widened non-stream gate and the
unchanged stream gate are both verified via source inspection, plus a real
import/attribute check where the handler module IS importable.
"""

from pathlib import Path

import pytest

_AGENT_SRC = Path(__file__).resolve().parents[2] / "src" / "parrot" / "handlers" / "agent.py"
_SRC = _AGENT_SRC.read_text(encoding="utf-8")


class TestNonStreamEnvelopePassthrough:
    def test_nonstream_handler_returns_envelope_for_structured(self):
        # FEAT-473 (G9): the generic (non-A2UI-mode) JSON body build now also
        # includes a2ui_envelope whenever the response carries one — not only
        # for output_mode == A2UI.
        assert '_a2ui_envelope = getattr(response, "a2ui_envelope", None)' in _SRC
        assert "if _a2ui_envelope is not None:" in _SRC
        assert 'obj_response["a2ui_envelope"] = _a2ui_envelope' in _SRC

    def test_a2ui_mode_body_shape_unchanged(self):
        # The OutputMode.A2UI-specific branch (dedicated response shape) is
        # untouched by the widened gate above.
        assert 'if getattr(response, "output_mode", None) == OutputMode.A2UI:' in _SRC
        assert '"a2ui_envelope": getattr(response, "a2ui_envelope", None),' in _SRC

    def test_stream_handler_unchanged(self):
        # Stream path (already ungated pre-FEAT-473) must not be touched.
        assert 'a2ui_envelope = getattr(ai_message, "a2ui_envelope", None)' in _SRC
        assert "if a2ui_envelope is not None:" in _SRC
        assert 'envelope["a2ui_envelope"] = a2ui_envelope' in _SRC

    def test_handler_importable_if_built(self):
        pytest.importorskip("parrot.handlers.agent")
        from parrot.handlers.agent import AgentTalk

        assert AgentTalk is not None
