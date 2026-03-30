"""CSV-to-markdown converter for DatasetManager file loading."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional, Union

import pandas as pd

logger = logging.getLogger(__name__)


def csv_to_markdown(
    path: Union[str, Path],
    max_rows: int = 200,
    separator: Optional[str] = None,
    **kwargs,
) -> str:
    """Convert a CSV file to a clean markdown table.

    Args:
        path: Path to the CSV file.
        max_rows: Maximum rows to include (truncates with note).
        separator: Column separator. Auto-detected if None.
        **kwargs: Passed to pandas.read_csv().

    Returns:
        Markdown string with table header and data.
    """
    path = Path(path)

    # Try UTF-8 first, fall back to Latin-1.
    read_kwargs = dict(kwargs)
    if separator is not None:
        read_kwargs["sep"] = separator

    df: Optional[pd.DataFrame] = None
    for encoding in ("utf-8", "latin-1"):
        try:
            df = pd.read_csv(path, encoding=encoding, **read_kwargs)
            break
        except UnicodeDecodeError:
            continue
    if df is None:
        raise ValueError(f"Cannot decode CSV file: {path.name}")

    total_rows = len(df)
    truncated = False
    if total_rows > max_rows:
        df = df.head(max_rows)
        truncated = True

    header = f"File: {path.name} ({total_rows} rows x {len(df.columns)} cols)\n"
    markdown = df.to_markdown(index=False)

    if truncated:
        markdown += f"\n\n(Showing first {max_rows} of {total_rows} rows)"

    return header + markdown


def csv_to_structural_summary(path: Union[str, Path]) -> str:
    """Return a brief structural summary of a CSV file.

    Args:
        path: Path to the CSV file.

    Returns:
        Summary string with file info.
    """
    path = Path(path)
    df: Optional[pd.DataFrame] = None
    total_rows: int = 0
    for encoding in ("utf-8", "latin-1"):
        try:
            df = pd.read_csv(path, encoding=encoding, nrows=5)
            total_rows = sum(1 for _ in open(path, encoding=encoding)) - 1
            break
        except UnicodeDecodeError:
            continue

    if df is None:
        return f"CSV file: {path.name} (unable to read)"

    cols = ", ".join(df.columns[:10])
    if len(df.columns) > 10:
        cols += f", ... (+{len(df.columns) - 10} more)"

    return (
        f"CSV file: {path.name}\n"
        f"  Rows: ~{total_rows}, Columns: {len(df.columns)}\n"
        f"  Headers: {cols}"
    )
