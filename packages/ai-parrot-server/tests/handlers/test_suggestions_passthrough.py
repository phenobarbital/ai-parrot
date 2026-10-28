"""FEAT-752 TASK-4802 — AgentTalk passes follow-up chips through, only when present.

The handler pulls in an import chain that is not guaranteed importable everywhere, so — like
``test_structured_envelope_passthrough.py`` — the four body builders are verified by source inspection, and the
shared helper is exercised for real.
"""

import json
import re
from pathlib import Path

import pytest

from parrot.models import AIMessage, Suggestion
from parrot.models.basic import CompletionUsage

_AGENT_SRC = Path(__file__).resolve().parents[2] / "src" / "parrot" / "handlers" / "agent.py"
_SRC = _AGENT_SRC.read_text(encoding="utf-8")


def _msg(**kw):
    return AIMessage(input="q", output="a", model="m", provider="p", usage=CompletionUsage(), **kw)


def _helper():
    pytest.importorskip("parrot.handlers.agent")
    from parrot.handlers.agent import _suggestions_payload

    return _suggestions_payload


def test_payload_none_when_empty():
    assert _helper()(_msg()) is None


def test_payload_json_ready():
    out = _helper()(_msg(suggestions=[Suggestion(label="A", prompt="a")]))
    assert out == [
        {"label": "A", "prompt": "a", "output_mode": None, "kind": "followup", "source": "provider", "action": None}
    ]
    json.dumps(out)  # must be JSON-serialisable as is


def test_payload_serialises_enum_values_and_actions():
    chips = [
        Suggestion(label="Table", prompt="t", output_mode="structured_table", kind="presentation"),
        Suggestion(label="Explain this", prompt="Explain this answer", kind="action", action="explain"),
    ]
    out = _helper()(_msg(suggestions=chips))
    json.dumps(out)
    assert out[0]["output_mode"] == "structured_table" and out[0]["kind"] == "presentation"
    assert out[1]["action"] == "explain"


def test_payload_tolerates_legacy_messages_and_plain_dicts():
    helper = _helper()

    class Legacy:  # no `suggestions` attribute at all
        pass

    assert helper(Legacy()) is None

    class WithDicts:
        suggestions = [{"label": "A", "prompt": "a"}]

    assert helper(WithDicts()) == [{"label": "A", "prompt": "a"}]


class TestFourSitesAreAdditive:
    """Every site sets the key only inside `if _suggestions is not None`, so a chip-less body is unchanged."""

    def test_all_four_sites_use_the_helper_conditionally(self):
        # definition + four body builders + the stream trailer writer (TASK-4807)
        assert _SRC.count("_suggestions_payload(") == 6
        for target in ("envelope", "a2ui_body", "obj_response"):
            pattern = (
                r"_suggestions = _suggestions_payload\((?:ai_message|response)\)\n"
                r"\s+if _suggestions is not None(?: and not suggestions_trailer)?:\n"
                rf"\s+{target}\[\"suggestions\"\] = _suggestions"
            )
            assert re.search(pattern, _SRC), target
        assert len(re.findall(r'obj_response\["suggestions"\] = _suggestions', _SRC)) == 2  # JSON path + infographic

    def test_key_is_never_set_unconditionally(self):
        for line_no, line in enumerate(_SRC.splitlines()):
            if '["suggestions"] = _suggestions' in line:
                previous = _SRC.splitlines()[line_no - 1].strip()
                # the stream envelope additionally yields to the opt-in trailer frame (TASK-4807)
                assert previous in (
                    "if _suggestions is not None:",
                    "if _suggestions is not None and not suggestions_trailer:",
                ), (line_no, previous)

    def test_a2ui_branch_keeps_its_original_key_order(self):
        keys = ["input", "output", "output_mode", "a2ui_envelope", "artifact_id", "metadata"]
        block = _SRC.split("a2ui_body = {", 1)[1].split("}", 1)[0]
        found = re.findall(r'"(\w+)":', block)
        assert found == keys

    def test_stream_envelope_sets_suggestions_before_the_separator(self):
        stream = _SRC.split('envelope["a2ui_envelope"] = a2ui_envelope', 1)[1]
        assert stream.index('envelope["suggestions"] = _suggestions') < stream.index('separator = b"\\n\\x00"')

    def test_text_chunks_are_not_touched(self):
        # chips never travel in text chunks: the key is only ever assigned at the four additive sites
        assert len(re.findall(r'\["suggestions"\] = ', _SRC)) == 4
