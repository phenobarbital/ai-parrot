"""Tabular response models shared by the data and database agents.

``PandasTable`` is the structured-output table contract produced by
``PandasAgent`` and wrapped by ``parrot.bots.database.models.QueryDataset``.
It lives here (not in ``parrot.bots.data``) so that importing the database
models — e.g. from ``wikitoolkit``'s schema plane — never loads the agent
machinery or the ai-parrot-tools satellite.
"""

import logging
from typing import List, Union

from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)

Scalar = Union[str, int, float, bool, None]


class PandasTable(BaseModel):
    """Tabular data structure for PandasAgent responses."""

    columns: List[str] = Field(description="Column names, in order")
    rows: List[List[Scalar]] = Field(
        description=(
            "Rows as lists of scalar values, aligned with `columns`. "
            "CRITICAL: All numeric values MUST be raw numbers without any formatting. "
            "Do NOT include currency symbols ($, €, £), percent signs (%), "
            "thousands separators (commas), or any other formatting characters. "
            "Correct: [764539.74, 85.3] | Wrong: ['$764,539.74', '85.3%']"
        )
    )

    @field_validator("rows")
    @classmethod
    def validate_rows_alignment(cls, v, info):
        """Ensure rows align with columns."""
        if "columns" in info.data:
            num_cols = len(info.data["columns"])
            if num_cols == 0:
                return v
            fixed_rows = []
            mismatch_count = 0
            for row in v:
                # Defensive: ensure row is a list
                if not isinstance(row, list):
                    row = [row]
                if len(row) != num_cols:
                    mismatch_count += 1
                    if len(row) < num_cols:
                        row = row + [None] * (num_cols - len(row))
                    else:
                        row = row[:num_cols]
                fixed_rows.append(row)
            if mismatch_count:
                logger.warning(
                    "PandasTable rows misaligned with columns: %d row(s) adjusted to %d columns.",
                    mismatch_count,
                    num_cols,
                )
            return fixed_rows
        return v


__all__ = ["PandasTable", "Scalar"]
