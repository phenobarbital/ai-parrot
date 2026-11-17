"""A2UI stream/non-stream contract tests for AgentTalk (TASK-1738, spec §4).

The chunked stream is a public wire contract (header + separator + envelope keys).
These tests guard that contract and assert the A2UI envelope is carried in the final
dict / non-stream JSON. The heavy ``parrot.handlers.agent`` import (transitively a
Cython extension) is exercised where available; the wire-contract regression checks run
everywhere via source inspection.
"""

import re
from pathlib import Path

import pytest

_AGENT_SRC = Path(__file__).resolve().parents[2] / "src" / "parrot" / "handlers" / "agent.py"
_SRC = _AGENT_SRC.read_text(encoding="utf-8")

# Quote-agnostic: ``black`` may rewrite the handler's quotes, which is not a contract change.
_Q = r"[\"']"


def _has(pattern: str) -> bool:
    """Return True when ``pattern`` (with ``{q}`` standing for either quote) matches the source."""
    return re.search(pattern.format(q=_Q), _SRC) is not None


class TestA2UIStreamContract:
    def test_chunked_wire_contract_unchanged(self):
        # Header value and separator bytes are the public contract — must not change.
        assert _has(r"{q}X-Parrot-Stream{q}:\s*{q}chunked-aimessage{q}")
        assert _has(r"separator = b{q}\\n\\x00{q}")

    def test_a2ui_envelope_added_to_final_stream_dict(self):
        # Envelope-complete per output: one extra key in the FINAL dict only.
        assert _has(r"a2ui_envelope = getattr\(ai_message, {q}a2ui_envelope{q}, None\)")
        assert _has(r"envelope\[{q}a2ui_envelope{q}\] = a2ui_envelope")

    def test_non_stream_response_carries_envelope(self):
        # Non-stream path surfaces the envelope for A2UI output_mode.
        assert "OutputMode.A2UI" in _SRC
        assert '"a2ui_envelope": getattr(response, "a2ui_envelope", None)' in _SRC

    def test_handler_a2ui_envelope_is_v1(self):
        # FEAT-470: both the stream and non-stream paths document (and forward
        # verbatim, envelope-agnostic) the v1.0 sobre — never reshaping it or
        # branching on a legacy `messageType`/`properties` shape.
        assert _SRC.count("FEAT-470") >= 2
        assert "v1.0 sobre" in _SRC
        assert "messageType" not in _SRC
        assert "'properties'" not in _SRC

    def test_handler_importable_if_built(self):
        # Runs the real import only where the Cython extension is built (e.g. CI).
        pytest.importorskip("parrot.handlers.agent")
        from parrot.handlers.agent import AgentTalk

        assert AgentTalk is not None
