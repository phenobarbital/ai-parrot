"""
QuerySlugSource and MultiQuerySlugSource implementations.

Wraps the QuerySource (QS) and MultiQS patterns as proper DataSource
implementations, replacing the inline _call_qs() / _call_multiquery()
logic that previously lived in DatasetManager.
"""
from __future__ import annotations
import hashlib
import json
import logging
from typing import Any, Dict, List, Optional, TYPE_CHECKING

import pandas as pd

from .base import DataSource
from parrot._imports import lazy_import

# Module-level variable so names are patchable in tests.
QS = None  # type: ignore[assignment,misc]


def _get_qs():
    """Lazily import QS from querysource. Returns None if not installed."""
    global QS
    if QS is not None:
        return QS
    try:
        _qs_mod = lazy_import("querysource.queries.qs", package_name="querysource", extra="db")
        QS = _qs_mod.QS
        return QS
    except ImportError:
        return None


class QuerySlugSource(DataSource):
    """DataSource backed by a single QuerySource slug.

    Wraps QS(slug=..., conditions=params) and exposes it as a lazy DataSource.
    Schema prefetch performs a 1-row query to infer column names and dtypes.

    Args:
        slug: The QuerySource slug identifier.
        prefetch_schema_enabled: When True, prefetch_schema() will call QS with
            querylimit=1 to infer the schema. Defaults to True.
        permanent_filter: Optional dict of conditions that are always merged
            into every fetch() call. Permanent filter keys take precedence
            over runtime params (cannot be overridden by the caller).
    """

    def __init__(
        self,
        slug: str,
        prefetch_schema_enabled: bool = True,
        permanent_filter: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.slug = slug
        self.prefetch_schema_enabled = prefetch_schema_enabled
        self._permanent_filter: Dict[str, Any] = permanent_filter or {}
        self.logger = logging.getLogger(__name__)

    @property
    def has_builtin_cache(self) -> bool:
        return True

    @property
    def cache_key(self) -> str:
        """Stable Redis cache key for this source.

        Returns:
            Cache key in the format ``qs:{slug}`` or ``qs:{slug}:f={hash}``
            when a permanent filter is set.
        """
        base = f"qs:{self.slug}"
        if self._permanent_filter:
            suffix = hashlib.md5(
                json.dumps(self._permanent_filter, sort_keys=True).encode()
            ).hexdigest()[:8]
            return f"{base}:f={suffix}"
        return base

    def describe(self) -> str:
        """Human-readable description for the LLM.

        Returns:
            Description string identifying the QuerySource slug.
        """
        desc = f"QuerySource slug '{self.slug}'"
        if self._permanent_filter:
            desc += f" [permanent filter: {self._permanent_filter}]"
        return desc

    async def prefetch_schema(self) -> Dict[str, str]:
        """Fetch one row to infer column names and dtypes.

        Calls QS with ``querylimit=1``. Returns an empty dict silently if the
        call fails or schema prefetch is disabled.

        Returns:
            Dictionary mapping column names to their dtype strings.
        """
        if not self.prefetch_schema_enabled:
            return {}

        try:
            qs_cls = _get_qs()
            if qs_cls is None:
                return {}
            conditions = {"querylimit": 1, **self._permanent_filter}
            qy = qs_cls(slug=self.slug, conditions=conditions)
            df, error = await qy.query(output_format='pandas')

            if error or not isinstance(df, pd.DataFrame) or df.empty:
                return {}

            return {col: str(dtype) for col, dtype in df.dtypes.items()}

        except Exception as e:
            self.logger.debug("prefetch_schema failed for slug '%s': %s", self.slug, e)
            return {}

    async def fetch(self, **params) -> pd.DataFrame:
        """Execute the QuerySource and return a DataFrame.

        Pops ``force_refresh`` from params (not a QS condition) and, when
        True, injects ``refresh=True`` into the QS conditions so that QS
        bypasses its own cache.

        Args:
            **params: Passed as the ``conditions`` dict to QS.
                force_refresh (bool): If True, tell QS to skip its cache.

        Returns:
            DataFrame with the query results.

        Raises:
            RuntimeError: If QS fails or returns no DataFrame.
        """
        force_refresh = params.pop('force_refresh', False)
        if force_refresh:
            params['refresh'] = True
        # Merge: permanent filter overwrites runtime params
        merged = {**params, **self._permanent_filter}
        self.logger.info("EXECUTING QUERY SOURCE: %s", self.slug)
        qs_cls = _get_qs()
        if qs_cls is None:
            raise RuntimeError(
                "querysource package is required for QuerySlugSource. "
                "Install it with: pip install querysource"
            )
        qy = qs_cls(slug=self.slug, conditions=merged)
        df, error = await qy.query(output_format='pandas')

        if error:
            raise RuntimeError(f"QuerySource slug '{self.slug}' failed: {error}")

        if not isinstance(df, pd.DataFrame):
            raise RuntimeError(
                f"QuerySource slug '{self.slug}' did not return a DataFrame"
            )

        return df


class MultiQuerySlugSource(DataSource):
    """DataSource backed by multiple QuerySource slugs whose results are merged.

    Fetches each slug independently and concatenates the resulting DataFrames.
    Schema prefetch performs a 1-row fetch per slug and merges the schema dicts.

    Args:
        slugs: List of QuerySource slug identifiers to merge.
    """

    def __init__(self, slugs: List[str]) -> None:
        self.slugs = slugs
        self.logger = logging.getLogger(__name__)

    @property
    def has_builtin_cache(self) -> bool:
        return True

    @property
    def cache_key(self) -> str:
        """Stable Redis cache key for this multi-slug source.

        Returns:
            Cache key in the format ``multiqs:{slug1}:{slug2}:...`` (slugs sorted).
        """
        return f"multiqs:{':'.join(sorted(self.slugs))}"

    def describe(self) -> str:
        """Human-readable description for the LLM.

        Returns:
            Description string listing all QuerySource slugs.
        """
        return f"Multi-QuerySource slugs: {', '.join(self.slugs)}"

    async def prefetch_schema(self) -> Dict[str, str]:
        """Fetch one row per slug and merge the inferred schemas.

        Returns an empty dict silently for any slug that fails.

        Returns:
            Merged dictionary mapping column names to their dtype strings.
        """
        schema: Dict[str, str] = {}

        for slug in self.slugs:
            try:
                qs_cls = _get_qs()
                if qs_cls is None:
                    continue
                qy = qs_cls(slug=slug, conditions={"querylimit": 1})
                df, error = await qy.query(output_format='pandas')

                if error or not isinstance(df, pd.DataFrame) or df.empty:
                    continue

                schema.update({col: str(dtype) for col, dtype in df.dtypes.items()})

            except Exception as e:
                self.logger.debug(
                    "prefetch_schema failed for slug '%s': %s", slug, e
                )

        return schema

    async def fetch(self, **params) -> pd.DataFrame:
        """Execute all slugs and concatenate the resulting DataFrames.

        Pops ``force_refresh`` from params and, when True, injects
        ``refresh=True`` into each QS conditions dict so that QS bypasses
        its own cache for every slug.

        Args:
            **params: Passed as the ``conditions`` dict to each QS call.
                force_refresh (bool): If True, tell QS to skip its cache.

        Returns:
            Concatenated DataFrame from all slugs.

        Raises:
            RuntimeError: If no slug returns a valid DataFrame.
        """
        force_refresh = params.pop('force_refresh', False)
        if force_refresh:
            params['refresh'] = True
        frames: List[pd.DataFrame] = []

        for slug in self.slugs:
            self.logger.info("EXECUTING QUERY SOURCE: %s", slug)
            try:
                qs_cls = _get_qs()
                if qs_cls is None:
                    raise RuntimeError(
                        "querysource package is required for MultiQuerySlugSource. "
                        "Install it with: pip install querysource"
                    )
                qy = qs_cls(slug=slug, conditions=params)
                df, error = await qy.query(output_format='pandas')

                if error:
                    self.logger.error("QuerySource slug '%s' failed: %s", slug, error)
                    continue

                if not isinstance(df, pd.DataFrame):
                    self.logger.error(
                        "QuerySource slug '%s' did not return a DataFrame", slug
                    )
                    continue

                frames.append(df)

            except Exception as e:
                self.logger.error("Failed to load query slug '%s': %s", slug, e)

        if not frames:
            raise RuntimeError(
                f"MultiQuerySlugSource: no slug returned data for slugs: {self.slugs}"
            )

        return pd.concat(frames, ignore_index=True)
