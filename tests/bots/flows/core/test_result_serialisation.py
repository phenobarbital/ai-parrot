"""Unit tests for ``NodeResult.to_dict()`` — safe per-agent serialisation.

Covers TASK-1765 (FEAT-306): the serialisation must never raise, regardless
of what the node's ``result`` value holds.
"""
import json

import pytest

from parrot.bots.flows.core.result import NodeResult


def _mk(result):
    return NodeResult(node_id="a1", node_name="Agent One", task="do x", result=result)


class TestNodeResultToDict:
    def test_primitive_passthrough(self):
        d = _mk({"k": [1, "two", None]}).to_dict()
        assert d["result"] == {"k": [1, "two", None]}
        assert d["node_id"] == "a1" and d["agent_id"] == "a1"
        json.dumps(d)  # JSON-safe without default=str

    def test_timestamp_isoformat(self):
        d = _mk("ok").to_dict()
        assert isinstance(d["timestamp"], str) and "T" in d["timestamp"]

    def test_dataframe_bounded_preview(self):
        pd = pytest.importorskip("pandas")
        df = pd.DataFrame({"x": range(100)})
        d = _mk(df).to_dict()
        assert isinstance(d["result"], str) and "100" in d["result"]

    def test_arbitrary_object_fallback(self):
        class Weird:
            def __repr__(self):
                return "<weird>"

        d = _mk(Weird()).to_dict()
        assert d["result"] == "<weird>"

    def test_ai_message_excluded(self):
        r = _mk("ok")
        r.ai_message = object()
        assert "ai_message" not in r.to_dict()

    def test_json_dumps_succeeds_for_every_test_input(self):
        for value in ({"a": 1}, [1, 2, 3], "text", 42, 3.14, True, None):
            json.dumps(_mk(value).to_dict(), default=str)

    def test_nested_metadata_serialised(self):
        r = NodeResult(
            node_id="a1",
            node_name="Agent One",
            task="do x",
            result="ok",
            metadata={"nested": {"inner": object()}},
        )
        d = r.to_dict()
        json.dumps(d, default=str)
        assert isinstance(d["metadata"]["nested"]["inner"], str)

    def test_all_expected_fields_present(self):
        d = _mk("ok").to_dict()
        expected_keys = {
            "node_id", "node_name", "agent_id", "agent_name", "task",
            "result", "metadata", "execution_time", "timestamp",
            "parent_execution_id", "execution_id",
        }
        assert expected_keys.issubset(d.keys())
