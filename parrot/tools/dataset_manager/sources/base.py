"""
DataSource abstract base class.

A DataSource is a reference to data. It knows how to:
- prefetch_schema(): retrieve column names and types cheaply (no rows)
- fetch(**params): execute and return a pd.DataFrame
- describe(): produce a human-readable string for the LLM
- cache_key: a stable, unique string for Redis keying

Key rule: prefetch_schema must be cheap — a single metadata query, no data rows.
fetch is the expensive call, only triggered on demand.

Cache key ownership: The cache_key is owned by DataSource, not by the agent name.
Two different agents registering the same source (e.g. same QuerySlugSource slug)
will share the same Redis cache entry.
"""
from abc import ABC, abstractmethod
from typing import Dict

import pandas as pd


class DataSource(ABC):
    """Abstract base for all data sources.

    A DataSource is a reference to data. It knows how to prefetch schema,
    fetch actual data, describe itself to the LLM, and provide a stable
    cache key for Redis.

    Subclasses must implement:
        - fetch(**params) -> pd.DataFrame
        - describe() -> str
        - cache_key (property) -> str

    Subclasses may optionally override:
        - prefetch_schema() -> Dict[str, str]
    """

    async def prefetch_schema(self) -> Dict[str, str]:
        """Return column-to-type mapping without fetching any rows.

        Subclasses override when cheap schema discovery is available
        (e.g. INFORMATION_SCHEMA query for TableSource, or a 1-row fetch
        for QuerySlugSource). The default returns an empty dict, meaning
        schema is unknown until the first fetch.

        Returns:
            Dictionary mapping column names to their type strings.
            Returns empty dict if schema is unavailable without fetching.
        """
        return {}

    @abstractmethod
    async def fetch(self, **params) -> pd.DataFrame:
        """Execute and return a DataFrame.

        This is the expensive call — only triggered on demand (materialization).
        Implementations should connect to the data source, execute the query,
        and return the result as a pandas DataFrame.

        Args:
            **params: Source-specific parameters (e.g. SQL template values,
                      query conditions, filter criteria).

        Returns:
            A pandas DataFrame with the fetched data.

        Raises:
            ValueError: If required params are missing or invalid.
            RuntimeError: If the data source is unreachable or returns no data.
        """
        ...

    @abstractmethod
    def describe(self) -> str:
        """Return a human-readable description for the LLM guide.

        This string is used in list_available() and the DataFrame guide
        to explain to the LLM what this data source contains and how to use it.

        Returns:
            A short descriptive string (1–2 lines).
        """
        ...

    @property
    def has_builtin_cache(self) -> bool:
        """Whether this source manages its own caching internally.

        When True, DatasetManager will skip its Redis caching layer and
        delegate cache management (including force-refresh semantics) entirely
        to the source. Override to True in sources like QuerySlugSource that
        rely on QuerySource's own caching infrastructure.

        Returns:
            False by default; override to True in QS-backed sources.
        """
        return False

    @property
    @abstractmethod
    def cache_key(self) -> str:
        """Stable, unique string for Redis keying.

        The key is shared across agents — two agents registering the same
        logical source (e.g. same query slug) will hit the same Redis entry.

        Format is source-type-specific:
            - InMemorySource:    'mem:{name}'
            - QuerySlugSource:  'qs:{slug}'
            - SQLQuerySource:   'sql:{driver}:{md5[:8]}'
            - TableSource:      'table:{driver}:{table}'

        Returns:
            A stable string used as the Redis cache key suffix.
        """
        ...
