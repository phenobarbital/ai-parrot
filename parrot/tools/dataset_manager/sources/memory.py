"""
InMemorySource — wraps an already-loaded pd.DataFrame as a DataSource.

No I/O is performed; schema is derived directly from df.dtypes and fetch
returns the wrapped DataFrame unchanged.
"""
from typing import Dict

import pandas as pd

from .base import DataSource


class InMemorySource(DataSource):
    """Wraps an already-loaded pd.DataFrame as a DataSource.

    Args:
        df: The DataFrame to wrap.
        name: Logical name used as the cache key suffix.
    """

    def __init__(self, df: pd.DataFrame, name: str) -> None:
        self._df = df
        self._name = name

    async def prefetch_schema(self) -> Dict[str, str]:
        """Return column-to-type mapping derived from df.dtypes (no I/O).

        Returns:
            Dictionary mapping column names to their dtype strings.
        """
        return {col: str(dtype) for col, dtype in self._df.dtypes.items()}

    async def fetch(self, **params) -> pd.DataFrame:
        """Return the wrapped DataFrame unchanged.

        Args:
            **params: Ignored — in-memory sources have no query parameters.

        Returns:
            The original DataFrame passed at construction time.
        """
        return self._df

    def describe(self) -> str:
        """Return a human-readable description for the LLM.

        Returns:
            String describing the DataFrame shape.
        """
        rows, cols = self._df.shape
        return f"In-memory DataFrame ({rows} rows × {cols} columns)"

    @property
    def cache_key(self) -> str:
        """Stable cache key for Redis keying.

        Returns:
            Key in the format ``mem:{name}``.
        """
        return f"mem:{self._name}"
