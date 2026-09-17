import json
import time
from decimal import Decimal

import numpy as np
import pandas as pd
from parrot_tools.querysource.results import frame_to_result, multi_to_result, json_safe


def _df(n=3):
    return pd.DataFrame({
        "ts": pd.to_datetime(["2026-08-09", None, "2026-08-11"][:n]),
        "qty": np.array([1, 2, 3][:n], dtype="int64"),
        "amt": [Decimal("1.5"), float("nan"), 2.0][:n],
        "cat": pd.Categorical(["a", "b", "a"][:n]),
    })


def test_json_safe_contract():
    r = frame_to_result(_df(), slug="s", max_rows=10, applied={"querylimit": 10}, rejected=[], started=time.monotonic())
    json.dumps(r.model_dump())
    assert r.rows[1]["ts"] is None and r.rows[0]["ts"].startswith("2026-08-09") and r.rows[0]["amt"] == 1.5


def test_truncation_and_counts():
    big = pd.DataFrame({"x": range(500)})
    r = frame_to_result(big, slug="s", max_rows=200, applied={}, rejected=[], started=time.monotonic())
    assert (r.returned_rows, r.total_rows, r.truncated, r.status) == (200, 500, True, "success")


def test_empty_frame():
    r = frame_to_result(pd.DataFrame(columns=["a", "b"]), slug="s", max_rows=5, applied={}, rejected=[], started=time.monotonic())
    assert r.status == "empty" and r.columns == ["a", "b"] and r.rows == []


def test_multi_shapes():
    m = multi_to_result({"a": _df(), "b": pd.DataFrame()}, max_rows=10, started=time.monotonic())
    assert set(m.results) == {"a", "b"} and m.status == "success"
    assert multi_to_result(pd.DataFrame(), max_rows=10, started=time.monotonic()).status == "empty"
    assert "result" in multi_to_result(_df(), max_rows=10, started=time.monotonic()).results


def test_json_safe_scalars_directly():
    assert json_safe(None) is None
    assert json_safe(float("nan")) is None
    assert json_safe(b"abc") == "abc"
    assert json_safe(np.int64(7)) == 7
    assert json_safe(np.float64(1.5)) == 1.5
    assert json_safe(pd.NaT) is None
