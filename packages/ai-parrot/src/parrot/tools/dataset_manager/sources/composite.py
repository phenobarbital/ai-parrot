"""
CompositeDataSource — virtual dataset that JOINs two or more existing datasets.

Implements the ``DataSource`` ABC.  Components are materialized independently
(respecting their own caching strategy), per-component filters are applied
before the JOIN, and sequential ``pd.merge()`` calls produce the result.

Key design decisions (from spec):
- ``has_builtin_cache = True``: DatasetManager skips its Redis layer for the
  composite result.  Components are cached individually by their own sources.
- Filter propagation: a filter key is applied only to components that contain
  that column (column-existence check per component).
- ``pd.errors.MergeError`` is captured and re-raised as ``ValueError`` with
  a descriptive message.
- Circular import avoided via ``TYPE_CHECKING`` for DatasetManager reference.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Set, TYPE_CHECKING, Union

import pandas as pd
from pydantic import BaseModel, Field

from .base import DataSource

if TYPE_CHECKING:  # pragma: no cover
    from ..tool import DatasetManager

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# JoinSpec — describes a single JOIN between two datasets
# ─────────────────────────────────────────────────────────────────────────────


class JoinSpec(BaseModel):
    """Specification for joining two datasets.

    Attributes:
        left: Left dataset name (must be registered in DatasetManager).
        right: Right dataset name (must be registered in DatasetManager).
        on: Column name(s) used as join key(s).
        how: Join type — one of ``"inner"``, ``"left"``, ``"right"``,
            ``"outer"``.
        suffixes: Tuple of suffixes appended to overlapping columns from
            left and right respectively.
    """

    left: str = Field(description="Left dataset name")
    right: str = Field(description="Right dataset name")
    on: Union[str, List[str]] = Field(description="Join column(s)")
    how: str = Field(default="inner", description="Join type: inner, left, right, outer")
    suffixes: tuple = Field(default=("", "_right"))


# ─────────────────────────────────────────────────────────────────────────────
# CompositeDataSource
# ─────────────────────────────────────────────────────────────────────────────


class CompositeDataSource(DataSource):
    """Virtual DataSource that JOINs existing datasets on demand.

    Components are fetched independently and JOINed sequentially using
    ``pd.merge()``.  Per-component filters are applied before each JOIN:
    a filter key is only forwarded to a component if that component has
    a column with that name.

    Attributes:
        name: Name of this composite dataset (used for logging and cache_key).
        joins: Ordered list of ``JoinSpec`` objects describing the JOINs.
        _dm: Back-reference to the owning ``DatasetManager`` (runtime only,
            not type-checked at import to avoid circular imports).
        description: Optional human-readable description.
    """

    def __init__(
        self,
        name: str,
        joins: List[JoinSpec],
        dataset_manager: "DatasetManager",
        description: str = "",
    ) -> None:
        """Initialise the composite source.

        Args:
            name: Dataset name for this composite.
            joins: Ordered list of ``JoinSpec`` objects.
            dataset_manager: The owning ``DatasetManager`` instance.
            description: Optional human-readable description.
        """
        self.name = name
        self.joins: List[JoinSpec] = joins
        self._dm = dataset_manager
        self._description = description

    # ─────────────────────────────────────────────────────────────
    # Helper: component introspection
    # ─────────────────────────────────────────────────────────────

    @property
    def component_names(self) -> Set[str]:
        """All unique dataset names referenced by the join specs."""
        names: Set[str] = set()
        for j in self.joins:
            names.add(j.left)
            names.add(j.right)
        return names

    def _get_component_columns(self, ds_name: str) -> List[str]:
        """Return known columns for a component dataset (loaded or schema only).

        Args:
            ds_name: Component dataset name.

        Returns:
            List of column names, or empty list if unknown.
        """
        entry = self._dm._datasets.get(ds_name)
        if entry is None:
            return []
        return entry.columns  # uses DatasetEntry.columns property

    # ─────────────────────────────────────────────────────────────
    # DataSource interface
    # ─────────────────────────────────────────────────────────────

    async def prefetch_schema(self) -> Dict[str, str]:
        """Return a merged schema from all component schemas.

        Collects ``_schema`` dicts from each component's source (available
        after prefetch for TableSource etc.) and merges them.  If a column
        appears in multiple components, the last definition wins.

        Returns:
            Dict mapping column names to their type strings.
        """
        merged: Dict[str, str] = {}
        for ds_name in self.component_names:
            entry = self._dm._datasets.get(ds_name)
            if entry is None:
                continue
            schema = getattr(entry.source, "_schema", {})
            merged.update(schema)
        return merged

    async def fetch(self, filter: Optional[Dict[str, Any]] = None, **params: Any) -> pd.DataFrame:
        """Materialize all components, apply per-component filters, then JOIN.

        Filter propagation:
            Each key in ``filter`` is applied only to components whose
            column list contains that key.  If a column exists in multiple
            components, all of them receive the filter.

        JOIN execution:
            JOINs are applied sequentially.  The accumulated result starts
            as the LEFT component of the first ``JoinSpec``, then merges
            each RIGHT component in order.

        Args:
            filter: Optional dict of equality filters.  Scalar values use
                ``==``; list/tuple/set values use ``isin``.
            **params: Extra keyword arguments (currently unused but accepted
                for DataSource interface compliance).

        Returns:
            Joined DataFrame.

        Raises:
            ValueError: If a component dataset is not registered.
            ValueError: If a join column is missing from either side.
            ValueError: If ``pd.merge()`` raises ``pd.errors.MergeError``.
        """
        filter = filter or {}

        # ── Validate all components exist ──────────────────────────────────
        for ds_name in self.component_names:
            entry = self._dm._datasets.get(ds_name)
            if entry is None:
                available = list(self._dm._datasets.keys())
                raise ValueError(
                    f"Composite '{self.name}': component dataset '{ds_name}' not found. "
                    f"Available datasets: {available}"
                )

        # ── Materialise components with per-component filters ──────────────
        component_dfs: Dict[str, pd.DataFrame] = {}
        for ds_name in self.component_names:
            # Determine applicable filter for this component
            comp_cols = self._get_component_columns(ds_name)
            applicable_filter: Dict[str, Any] = {}
            if filter and comp_cols:
                applicable_filter = {
                    k: v for k, v in filter.items() if k in comp_cols
                }

            # Materialise (force_refresh=True per spec — composite always re-fetches)
            df = await self._dm.materialize(ds_name, force_refresh=True)

            # Apply component-level filter
            if applicable_filter:
                df = self._dm._apply_filter(df, applicable_filter)

            component_dfs[ds_name] = df

        # ── Execute sequential JOINs ───────────────────────────────────────
        # Start with the left side of the first join
        first_join = self.joins[0]
        result = component_dfs[first_join.left]

        for join_spec in self.joins:
            right_df = component_dfs[join_spec.right]
            on_cols = join_spec.on if isinstance(join_spec.on, list) else [join_spec.on]

            # Validate join columns exist in both sides
            for col in on_cols:
                if col not in result.columns:
                    raise ValueError(
                        f"Composite '{self.name}': join column '{col}' not found "
                        f"in left dataset. Available left columns: {result.columns.tolist()}"
                    )
                if col not in right_df.columns:
                    raise ValueError(
                        f"Composite '{self.name}': join column '{col}' not found "
                        f"in right dataset '{join_spec.right}'. "
                        f"Available right columns: {right_df.columns.tolist()}"
                    )

            try:
                result = pd.merge(
                    result,
                    right_df,
                    on=join_spec.on,
                    how=join_spec.how,
                    suffixes=join_spec.suffixes,
                )
            except pd.errors.MergeError as exc:
                raise ValueError(
                    f"Composite '{self.name}': merge failed between result and "
                    f"'{join_spec.right}' on {join_spec.on}: {exc}"
                ) from exc

        logger.debug(
            "Composite '%s' materialized: %d rows × %d cols",
            self.name, len(result), result.shape[1],
        )
        return result

    def describe(self) -> str:
        """Return a human-readable join description for the LLM guide.

        Returns:
            Multi-line string showing each JOIN step and the join key(s).
        """
        if self._description:
            parts = [self._description]
        else:
            parts = [f"Composite dataset '{self.name}'"]

        for i, j in enumerate(self.joins, 1):
            on_str = j.on if isinstance(j.on, str) else ", ".join(j.on)
            parts.append(
                f"  Step {i}: {j.left} {j.how.upper()} JOIN {j.right} ON {on_str}"
            )
        return "\n".join(parts)

    @property
    def has_builtin_cache(self) -> bool:
        """Always True — DatasetManager skips Redis for the composite result.

        Components are cached individually by their own sources.  The JOIN
        result is recomputed on every ``fetch()`` call.

        Returns:
            True
        """
        return True

    @property
    def cache_key(self) -> str:
        """Stable cache key derived from the composite name.

        Returns:
            Cache key string in the format ``composite:{name}``.
        """
        return f"composite:{self.name}"
