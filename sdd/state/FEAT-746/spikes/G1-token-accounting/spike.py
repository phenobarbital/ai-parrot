"""G1 — token accounting: descriptor path vs inline JSON for a 10k-row frame (FEAT-746)."""
from __future__ import annotations

import json
import sys
from typing import Any

import numpy as np
import pandas as pd

from parrot.interagent import HandleDescriptor, MediaType

ROWS, COLS, SEED = 10_000, 12, 746


def build_frame() -> pd.DataFrame:
    """Deterministic mixed-dtype frame (ints, floats, strings, dates, bools)."""
    rng = np.random.default_rng(SEED)
    # 12 columns: 4 int, 3 float, 3 str (department-like categories), 1 datetime, 1 bool
    data = {
        "id": rng.integers(0, 1_000_000, size=ROWS, dtype="int32"),
        "department": rng.choice(["Engineering", "Sales", "Marketing", "HR", "Finance"], size=ROWS),
        "salary": rng.uniform(30_000, 200_000, size=ROWS),
        "bonus": rng.uniform(0, 50_000, size=ROWS),
        "performance_score": rng.uniform(1, 5, size=ROWS),
        "tenure_months": rng.integers(0, 120, size=ROWS),
        "hire_date": rng.integers(0, 10_000, size=ROWS, dtype="int32"),
        "is_active": rng.choice([True, False], size=ROWS),
        "region": rng.choice(["North", "South", "East", "West"], size=ROWS),
        "manager_id": rng.integers(0, 500, size=ROWS),
        "project_hours": rng.uniform(0, 2000, size=ROWS),
        "team_size": rng.integers(1, 20, size=ROWS),
    }
    df = pd.DataFrame(data)
    df["hire_date"] = pd.to_datetime(df["hire_date"], unit="D", origin="1970-01-01")
    return df


def inline_payload(df: pd.DataFrame) -> str:
    """The JSON an A2A/REST call would put in context today."""
    return json.dumps(df.to_dict(orient="records"), default=str)


def descriptor_payload(df: pd.DataFrame, *, preview_rows: int, summary_chars: int) -> str:
    """JSON of the HandleDescriptor the external LLM would see."""
    summary: dict[str, Any] = {
        "rows": int(len(df)),
        "columns": [{"name": c, "dtype": str(t)} for c, t in df.dtypes.items()],
        "preview": json.loads(df.head(preview_rows).to_json(orient="records", date_format="iso")),
        "null_counts": {c: int(n) for c, n in df.isna().sum().items() if n},
    }
    text = json.dumps(summary, separators=(",", ":"))
    # Truncate `text` to summary_chars by dropping preview rows first, then null_counts
    while len(text) > summary_chars:
        if len(summary["preview"]) > 0:
            summary["preview"] = summary["preview"][:-1]
        elif len(summary["null_counts"]) > 0:
            summary["null_counts"] = {k: v for k, v in summary["null_counts"].items() if v > 0}
        else:
            break
        text = json.dumps(summary, separators=(",", ":"))
    desc = HandleDescriptor(
        media_type=MediaType.ARROW, byte_size=int(df.memory_usage(deep=True).sum()), summary=json.loads(text)
    )
    return desc.model_dump_json()


def count_tokens(text: str) -> dict[str, int]:
    """Heuristic always; tiktoken when importable."""
    out = {"heuristic_len4": len(text) // 4}
    try:
        import tiktoken  # optional, never declared

        out["tiktoken_cl100k"] = len(tiktoken.get_encoding("cl100k_base").encode(text))
    except ImportError:
        pass
    return out


def main() -> int:
    df = build_frame()
    print("inline", count_tokens(inline_payload(df)))
    for pr in (3, 5, 10):
        for sc in (600, 1000, 1500):
            print("descriptor", pr, sc, count_tokens(descriptor_payload(df, preview_rows=pr, summary_chars=sc)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
