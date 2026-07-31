"""Unit tests for the `columnar` codec (TASK-1954).

This is the executable specification the optional Rust path (TASK-1955)
must also satisfy — assertions are black-box (shape/values only), no
white-box assertions about internal helpers.
"""
import pytest

import parrot.tools.compression.codecs  # noqa: F401
from parrot.tools.compression import FilterLevel, get_codec


@pytest.fixture
def codec():
    return get_codec("columnar")()


class TestColumnar:
    def test_columnar_shape_matches_pandastable(self, codec, row_oriented_payload):
        out = codec.compress(row_oriented_payload, level=FilterLevel.NORMAL, params={})
        p = out.payload
        assert set(p) >= {"columns", "rows"}
        assert all(len(r) == len(p["columns"]) for r in p["rows"])
        assert out.bytes_after < out.bytes_before

    def test_columnar_constants_and_null_elision(self, codec, row_oriented_payload):
        out = codec.compress(row_oriented_payload, level=FilterLevel.NORMAL, params={})
        assert out.payload["constants"]["region"] == "south"
        assert out.payload["constants"]["active"] is True
        assert "notes" not in out.payload["columns"]
        assert out.lossy is True

    def test_columnar_min_rows_passthrough(self, codec, row_oriented_payload):
        small = row_oriented_payload[:19]
        out = codec.compress(small, level=FilterLevel.NORMAL, params={})
        assert out.payload is small
        assert out.bytes_after == out.bytes_before      # recorded as "no gain"
        assert out.lossy is False

    def test_columnar_heterogeneous_passthrough(self, codec, heterogeneous_payload):
        out = codec.compress(heterogeneous_payload, level=FilterLevel.NORMAL, params={})
        assert "columns" not in (out.payload if isinstance(out.payload, dict) else {})
        assert isinstance(out.payload, list)
        # null-elision only: no key set actually contains a None here, so
        # every row is unchanged and the outcome is not lossy.
        assert out.payload == heterogeneous_payload

    def test_columnar_heterogeneous_elides_nulls(self, codec):
        rows = [{f"k{i}": i, "shared": None} for i in range(30)]
        out = codec.compress(rows, level=FilterLevel.NORMAL, params={})
        assert isinstance(out.payload, list)
        assert all("shared" not in r for r in out.payload)
        assert out.lossy is True

    def test_columnar_nested_values_passthrough(self, codec):
        rows = [{"a": {"nested": 1}, "b": None} for _ in range(30)]
        out = codec.compress(rows, level=FilterLevel.NORMAL, params={})
        assert isinstance(out.payload, list)             # not columnarized
        assert all("b" not in r for r in out.payload)    # null-elided
        assert all(r["a"] == {"nested": 1} for r in out.payload)  # not flattened

    def test_determinism_and_stable_column_order(self, codec, row_oriented_payload):
        first = codec.compress(row_oriented_payload, level=FilterLevel.NORMAL, params={})
        for _ in range(99):
            again = codec.compress(row_oriented_payload, level=FilterLevel.NORMAL, params={})
            assert again.payload == first.payload
        # first-seen order across rows, not sorted / set-derived
        assert first.payload["columns"][0] == "store_id"
        assert first.payload["columns"][1] == "revenue"

    def test_queryresult_shape(self, codec, row_oriented_payload):
        payload = {"driver": "pg", "rows": row_oriented_payload,
                   "row_count": 500, "columns": [], "execution_time_ms": 1.0}
        out = codec.compress(payload, level=FilterLevel.NORMAL, params={})
        assert out.payload["driver"] == "pg"
        assert out.payload["row_count"] == 500
        assert "columns" in out.payload["rows"]

    def test_min_rows_configurable(self, codec, row_oriented_payload):
        out = codec.compress(row_oriented_payload[:5], level=FilterLevel.NORMAL,
                             params={"min_rows": 2})
        assert "columns" in out.payload

    def test_heterogeneity_ratio_configurable(self, codec, heterogeneous_payload):
        # With a very high ratio threshold, the same payload is no longer
        # considered heterogeneous enough to skip columnarization... but
        # since the rows are still fully disjoint aside from `shared`, the
        # zero-shared-keys guard doesn't apply here (there IS a shared key)
        # so a big enough ratio lets it through to columnarize.
        out = codec.compress(
            heterogeneous_payload, level=FilterLevel.NORMAL,
            params={"heterogeneity_ratio": 1000.0},
        )
        assert "columns" in out.payload

    def test_none_level_is_passthrough(self, codec, row_oriented_payload):
        out = codec.compress(row_oriented_payload, level=FilterLevel.NONE, params={})
        assert out.payload is row_oriented_payload
        assert out.lossy is False

    def test_non_list_dict_input_passthrough(self, codec):
        out = codec.compress("plain string", level=FilterLevel.NORMAL, params={})
        assert out.payload == "plain string"
        assert out.lossy is False

    def test_never_raises(self, codec):
        for bad in [object(), {1: object()}, [object()] * 25]:
            assert codec.compress(bad, level=FilterLevel.NORMAL, params={}) is not None

    def test_no_pandas_dependency(self):
        import pathlib
        src = pathlib.Path(
            __file__
        ).resolve().parents[3] / "src" / "parrot" / "tools" / "compression" / "codecs" / "columnar.py"
        assert src.is_file()
        assert "pandas" not in src.read_text()

    def test_registered_after_import(self):
        assert get_codec("columnar") is not None

    def test_est_tokens_saved_is_bytes_over_four(self, codec, row_oriented_payload):
        out = codec.compress(row_oriented_payload, level=FilterLevel.NORMAL, params={})
        assert out.est_tokens_saved == max(0, out.bytes_before - out.bytes_after) // 4

    def test_minimal_splits_columns_losslessly(self, codec, row_oriented_payload):
        # MINIMAL is the lossless-only level: the column split and constant
        # factoring still happen (both preserve every value), but the
        # all-null `notes` column must NOT be dropped — it is factored into
        # `constants` as None instead, so no information is lost.
        out = codec.compress(row_oriented_payload, level=FilterLevel.MINIMAL, params={})
        p = out.payload
        assert set(p) >= {"columns", "rows"}
        assert p["constants"]["region"] == "south"
        assert p["constants"]["active"] is True
        assert p["constants"]["notes"] is None
        assert out.lossy is False
        assert out.bytes_after < out.bytes_before

    def test_minimal_heterogeneous_skips_null_elision(self, codec):
        # NORMAL would elide the all-null `shared` key per row (lossy);
        # MINIMAL must pass the payload through unchanged instead.
        rows = [{f"k{i}": i, "shared": None} for i in range(30)]
        out = codec.compress(rows, level=FilterLevel.MINIMAL, params={})
        assert out.payload is rows
        assert out.lossy is False

    def test_minimal_nested_values_passthrough(self, codec):
        rows = [{"a": {"nested": 1}, "b": None} for _ in range(30)]
        out = codec.compress(rows, level=FilterLevel.MINIMAL, params={})
        assert out.payload is rows
        assert out.lossy is False

    def test_minimal_nonuniform_keys_passthrough(self, codec):
        # Code-review finding (Codex P2): `row.get()` fills a missing key
        # with None, conflating absent-with-null. One row carrying an extra
        # `note: None` stays under the heterogeneity ratio, so pre-guard it
        # would reach `_columnarize` and factor `note` into constants as if
        # EVERY row had it. MINIMAL must pass non-uniform key sets through.
        rows = [{"a": i, "b": i, "c": i} for i in range(29)]
        rows.append({"a": 1, "b": 2, "c": 3, "note": None})
        out = codec.compress(rows, level=FilterLevel.MINIMAL, params={})
        assert out.payload is rows
        assert out.lossy is False

    def test_normal_nonuniform_keys_still_columnarizes(self, codec):
        # Contrast pin: the same shape at NORMAL keeps today's behavior —
        # columnarized, all-null `note` column elided, lossy → tee-armed.
        rows = [{"a": i, "b": i, "c": i} for i in range(29)]
        rows.append({"a": 1, "b": 2, "c": 3, "note": None})
        out = codec.compress(rows, level=FilterLevel.NORMAL, params={})
        assert "columns" in out.payload
        assert "note" not in out.payload["columns"]
        assert out.lossy is True

    def test_minimal_serialized_input_keeps_null_columns(self, codec, row_oriented_payload):
        # The Rust transform elides null columns internally, so MINIMAL must
        # not dispatch to it even for the bytes/str input shape that is
        # normally Rust-eligible.
        import json
        out = codec.compress(
            json.dumps(row_oriented_payload), level=FilterLevel.MINIMAL, params={},
        )
        assert out.payload["constants"]["notes"] is None
        assert out.lossy is False

    def test_single_row_no_constants(self, codec):
        # len(rows) > 1 is required for constant factoring — a single row
        # trivially has "constant" columns for everything, which would be
        # nonsensical to factor out.
        out = codec.compress(
            [{"a": 1, "b": 2}], level=FilterLevel.NORMAL, params={"min_rows": 1},
        )
        assert out.payload["constants"] == {}
