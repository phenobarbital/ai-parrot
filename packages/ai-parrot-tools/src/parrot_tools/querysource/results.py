"""Shape QuerySource results into bounded, JSON-safe Pydantic models (spec §3 M5, S8/S9)."""

from __future__ import annotations

import time
from datetime import date, datetime, time as dt_time
from decimal import Decimal
from typing import Any

import numpy as np
import pandas as pd

from parrot_tools.querysource.models import ExecutionResult, MultiQueryResult


def json_safe(value: Any) -> Any:
    """Convert pandas/numpy/datetime scalars and containers into json.dumps-able Python values."""
    if value is None:
        return None
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(v) for v in value]
    # NaT/NaN/pandas-NA scalars first: NaTType duck-types datetime (its own .isoformat() returns the
    # literal string "NaT"), so this check MUST run before the datetime branch below.
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass  # not a scalar pandas can classify as NA — fall through to the type-specific checks
    if isinstance(value, (datetime, date, dt_time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    if isinstance(value, (bool, int, float, str)):
        return value
    return str(value)


def _as_frame(result: Any) -> pd.DataFrame:
    """Coerce QS outputs (DataFrame | list[dict] | dict | None) into a DataFrame without changing dtypes."""
    if isinstance(result, pd.DataFrame):
        return result
    if result is None:
        return pd.DataFrame()
    if isinstance(result, dict):
        return pd.DataFrame([result])
    return pd.DataFrame(list(result))


def frame_to_result(
    result: Any, *, slug: str | None, max_rows: int, applied: dict[str, Any], rejected: list[str], started: float
) -> ExecutionResult:
    """DataFrame → ExecutionResult: head(max_rows) rows, honest counts, status 'empty' for zero rows."""
    frame = _as_frame(result)
    total = int(len(frame))
    head = frame.head(max_rows)
    rows = [json_safe(rec) for rec in head.to_dict(orient="records")]
    return ExecutionResult(
        status="empty" if total == 0 else "success",
        slug=slug,
        rows=rows,
        returned_rows=len(rows),
        total_rows=total,
        truncated=total > max_rows,
        columns=[str(c) for c in frame.columns],
        applied_conditions=json_safe(applied) or {},
        rejected_inputs=list(rejected),
        duration_ms=int((time.monotonic() - started) * 1000),
    )


def multi_to_result(result: Any, *, max_rows: int, started: float) -> MultiQueryResult:
    """MultiQS output (DataFrame | dict[str, DataFrame]) → MultiQueryResult keyed by frame name ('result' when single)."""
    frames = result if isinstance(result, dict) else {"result": result}
    results = {
        str(name): frame_to_result(frame, slug=None, max_rows=max_rows, applied={}, rejected=[], started=started)
        for name, frame in frames.items()
    }
    status = "empty" if results and all(r.status == "empty" for r in results.values()) else "success"
    return MultiQueryResult(status=status, results=results, duration_ms=int((time.monotonic() - started) * 1000))
