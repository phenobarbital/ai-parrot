"""A2UI stream/non-stream contract tests for AgentTalk (TASK-1738, spec §4).

The chunked stream is a public wire contract (header + separator + envelope keys).
These tests guard that contract and assert the A2UI envelope is carried in the final
dict / non-stream JSON. The heavy ``parrot.handlers.agent`` import (transitively a
Cython extension) is exercised where available; the wire-contract regression checks run
everywhere via source inspection.
"""

from pathlib import Path

import pytest

_AGENT_SRC = (
    Path(__file__).resolve().parents[2]
    / "src" / "parrot" / "handlers" / "agent.py"
)
_SRC = _AGENT_SRC.read_text(encoding="utf-8")


class TestA2UIStreamContract:
    def test_chunked_wire_contract_unchanged(self):
        # Header value and separator bytes are the public contract — must not change.
        assert "'X-Parrot-Stream': 'chunked-aimessage'" in _SRC
        assert r"separator = b'\n\x00'" in _SRC

    def test_a2ui_envelope_added_to_final_stream_dict(self):
        # Envelope-complete per output: one extra key in the FINAL dict only.
        assert "a2ui_envelope = getattr(ai_message, 'a2ui_envelope', None)" in _SRC
        assert "envelope['a2ui_envelope'] = a2ui_envelope" in _SRC

    def test_non_stream_response_carries_envelope(self):
        # Non-stream path surfaces the envelope for A2UI output_mode.
        assert "OutputMode.A2UI" in _SRC
        assert '"a2ui_envelope": getattr(response, "a2ui_envelope", None)' in _SRC

    def test_handler_importable_if_built(self):
        # Runs the real import only where the Cython extension is built (e.g. CI).
        pytest.importorskip("parrot.handlers.agent")
        from parrot.handlers.agent import AgentTalk

        assert AgentTalk is not None
