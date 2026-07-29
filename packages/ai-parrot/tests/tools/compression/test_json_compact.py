"""Unit tests for the `json_compact` codec (TASK-1949)."""
import pytest

import parrot.tools.compression.codecs  # noqa: F401 — triggers registration
from parrot.tools.compression import FilterLevel, get_codec


@pytest.fixture
def codec():
    return get_codec("json_compact")()


class TestJsonCompact:
    def test_json_compact_is_lossless(self, codec):
        data = {"a": 1, "b": None, "c": [{"x": 1}, {"x": 1}], "d": {"e": None}}
        out = codec.compress(data, level=FilterLevel.MINIMAL, params={})
        assert out.lossy is False
        assert out.bytes_after <= out.bytes_before
        # semantics preserved: no non-null value disappeared
        assert out.payload["a"] == 1
        assert "e" not in out.payload["d"] and out.payload["d"] == {}

    def test_none_level_is_passthrough(self, codec):
        data = {"a": None}
        out = codec.compress(data, level=FilterLevel.NONE, params={})
        assert out.payload is data
        assert out.bytes_after == out.bytes_before
        assert out.lossy is False

    def test_determinism(self, codec):
        data = {"rows": [{"k": i, "n": None} for i in range(50)]}
        first = codec.compress(data, level=FilterLevel.MINIMAL, params={})
        for _ in range(99):
            assert codec.compress(
                data, level=FilterLevel.MINIMAL, params={}
            ).payload == first.payload

    def test_non_serializable_passthrough(self, codec):
        class Weird:
            pass
        obj = Weird()
        out = codec.compress(obj, level=FilterLevel.MINIMAL, params={})
        assert out.payload is obj
        assert out.lossy is False

    def test_never_raises(self, codec):
        for bad in [object(), {1: object()}, [object()]]:
            assert codec.compress(bad, level=FilterLevel.NORMAL, params={}) is not None

    def test_est_tokens_saved_is_bytes_over_four(self, codec):
        data = {"a": 1, "b": None}
        out = codec.compress(data, level=FilterLevel.MINIMAL, params={})
        assert out.est_tokens_saved == max(0, out.bytes_before - out.bytes_after) // 4

    def test_exact_dedup_marker_shape(self, codec):
        data = {"c": [{"a": 1}, {"a": 1}, {"a": 1}, {"b": 2}]}
        out = codec.compress(data, level=FilterLevel.MINIMAL, params={})
        collapsed = out.payload["c"]
        assert collapsed[0] == {"_repeat": 3, "_value": {"a": 1}}
        assert collapsed[1] == {"b": 2}

    def test_dedup_disabled_via_params(self, codec):
        data = {"c": [{"a": 1}, {"a": 1}, {"a": 1}]}
        out = codec.compress(
            data, level=FilterLevel.MINIMAL, params={"dedup": False}
        )
        assert out.payload["c"] == [{"a": 1}, {"a": 1}, {"a": 1}]

    def test_marker_shaped_value_not_recollapsed(self, codec):
        # A list whose elements already look like a repeat marker must not
        # be wrapped again — would be ambiguous on decode.
        marker = {"_repeat": 2, "_value": {"a": 1}}
        data = {"c": [marker, marker]}
        out = codec.compress(data, level=FilterLevel.MINIMAL, params={})
        assert out.payload["c"] == [marker, marker]

    def test_lossy_always_false(self, codec):
        for data in [
            {"a": None, "b": [1, 1, 1]},
            {"nested": {"x": None, "y": {"z": None}}},
            [{"a": 1}, {"a": 1}],
            "plain string",
            42,
        ]:
            out = codec.compress(data, level=FilterLevel.AGGRESSIVE, params={})
            assert out.lossy is False

    def test_registered_after_import(self):
        assert get_codec("json_compact") is not None
