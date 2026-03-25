"""
MongoSource — DataSource subclass for MongoDB/DocumentDB collections.

Read-only. Every fetch() call MUST include a ``filter`` dict parameter — no
full-collection scans are allowed. A ``projection`` dict is also required to
limit returned fields.

On registration, prefetch_schema() runs a find_one() on the collection to
infer field names and types from a single document (excluding the internal
``_id`` field).

Credential resolution supports either a DSN (MongoDB connection string) or a
credentials dict with host/port/user/password/database keys.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import pandas as pd

from .base import DataSource
from parrot._imports import lazy_import

logger = logging.getLogger(__name__)


def _infer_mongo_types(document: Dict[str, Any]) -> Dict[str, str]:
    """Infer field→type mapping from a single MongoDB document.

    Excludes the ``_id`` field (internal MongoDB identifier).

    Args:
        document: A MongoDB document dict (from find_one()).

    Returns:
        Dict mapping field name → Python type name as string.
    """
    type_map: Dict[str, str] = {}
    for key, value in document.items():
        if key == "_id":
            continue
        type_map[key] = type(value).__name__
    return type_map


class MongoSource(DataSource):
    """DataSource for MongoDB/DocumentDB collections via asyncdb's mongo driver.

    Read-only. Every fetch() call requires both a ``filter`` dict and a
    ``projection`` dict to prevent full-collection scans and limit the fields
    returned.

    ``prefetch_schema()`` calls ``find_one()`` on the collection to infer field
    names and Python types from a single document.

    Args:
        collection: MongoDB collection name, e.g. "orders".
        name: Dataset name/identifier for this source.
        database: MongoDB database name, e.g. "mydb".
        credentials: Optional credentials dict with host/port/user/password.
            Used when dsn is None.
        dsn: Optional MongoDB connection string (DSN). Takes priority over
            the credentials dict.
        required_filter: If True (default), fetch() raises ValueError when
            no filter is provided. Set False to allow unrestricted queries
            (not recommended for production).
    """

    def __init__(
        self,
        collection: str,
        name: str,
        database: str,
        credentials: Optional[Dict[str, Any]] = None,
        dsn: Optional[str] = None,
        required_filter: bool = True,
    ) -> None:
        self._collection = collection
        self._name = name
        self._database = database
        self._credentials = credentials
        self._dsn = dsn
        self._required_filter = required_filter
        self._schema: Dict[str, str] = {}

    # ─────────────────────────────────────────────────────────────
    # Internal helpers
    # ─────────────────────────────────────────────────────────────

    def _get_driver(self) -> Any:
        """Instantiate the asyncdb mongo driver.

        Returns:
            Configured asyncdb mongo driver instance.
        """
        mongo_mod = lazy_import(
            "asyncdb.drivers.mongo",
            package_name="asyncdb",
            extra="mongo",
        )
        MongoDriver = mongo_mod.mongo  # type: ignore[attr-defined]

        if self._dsn:
            return MongoDriver(dsn=self._dsn)

        params = dict(self._credentials) if self._credentials else {}
        if self._database and "database" not in params:
            params["database"] = self._database
        return MongoDriver(params=params)

    # ─────────────────────────────────────────────────────────────
    # DataSource interface
    # ─────────────────────────────────────────────────────────────

    async def prefetch_schema(self) -> Dict[str, str]:
        """Infer schema from a single MongoDB document via find_one().

        Excludes the internal ``_id`` field. The result is stored in
        ``self._schema`` and returned.

        Returns:
            Dict mapping field_name → Python type name.

        Raises:
            RuntimeError: If the collection is empty or the driver fails.
        """
        driver = self._get_driver()
        try:
            async with await driver.connection() as conn:
                document = await conn.find_one(
                    self._collection, database=self._database
                )
                if document is None:
                    logger.warning(
                        "MongoSource '%s.%s': find_one returned None — schema unknown",
                        self._database,
                        self._collection,
                    )
                    self._schema = {}
                else:
                    self._schema = _infer_mongo_types(document)
        except Exception as exc:
            raise RuntimeError(
                f"MongoSource: failed to prefetch schema for "
                f"'{self._database}.{self._collection}': {exc}"
            ) from exc

        logger.debug(
            "MongoSource '%s.%s': schema prefetched (%d fields)",
            self._database,
            self._collection,
            len(self._schema),
        )
        return self._schema

    async def fetch(self, **params) -> pd.DataFrame:
        """Query the MongoDB collection and return a DataFrame.

        Both ``filter`` and ``projection`` are required parameters.

        Args:
            **params:
                filter (dict): MongoDB query filter, e.g.
                    ``{"status": "active", "amount": {"$gt": 100}}``.
                    Required when ``required_filter=True`` (default).
                projection (dict): MongoDB projection to limit returned fields,
                    e.g. ``{"order_id": 1, "amount": 1, "_id": 0}``.
                    Always required.

        Returns:
            DataFrame built from the matching documents.

        Raises:
            ValueError: If ``filter`` is missing (when required_filter=True)
                or if ``projection`` is missing.
            RuntimeError: If the driver query fails.
        """
        filter_dict: Optional[Dict[str, Any]] = params.get("filter")
        projection: Optional[Dict[str, Any]] = params.get("projection")

        if self._required_filter and not filter_dict:
            raise ValueError(
                f"MongoSource '{self._name}' requires a 'filter' parameter. "
                "Full-collection scans are not allowed. "
                "Provide a filter dict, e.g. {\"status\": \"active\"}."
            )

        if not projection:
            raise ValueError(
                f"MongoSource '{self._name}' requires a 'projection' parameter. "
                "Provide a projection dict to limit returned fields, "
                "e.g. {\"order_id\": 1, \"amount\": 1, \"_id\": 0}."
            )

        driver = self._get_driver()
        try:
            async with await driver.connection() as conn:
                logger.info(
                    "MongoSource('%s.%s') querying with filter: %s",
                    self._database,
                    self._collection,
                    filter_dict,
                )
                results = await conn.query(
                    filter_dict,
                    collection=self._collection,
                    database=self._database,
                    projection=projection,
                )

                if results is None:
                    return pd.DataFrame()

                # Convert list of dicts to DataFrame
                if isinstance(results, list):
                    if not results:
                        return pd.DataFrame()
                    # Remove _id field from results if present
                    cleaned = [
                        {k: v for k, v in doc.items() if k != "_id"}
                        for doc in results
                    ]
                    return pd.DataFrame(cleaned)

                # If driver returns a DataFrame directly
                if isinstance(results, pd.DataFrame):
                    return results

                # Fallback: try to convert
                return pd.DataFrame(list(results))

        except (ValueError, RuntimeError):
            raise
        except Exception as exc:
            raise RuntimeError(
                f"MongoSource '{self._database}.{self._collection}' fetch failed: {exc}"
            ) from exc

    def describe(self) -> str:
        """Return a human-readable description for the LLM guide.

        Returns:
            String describing the MongoDB collection, database, and field count.
        """
        n_fields = len(self._schema)
        return (
            f"MongoDB collection '{self._collection}' in database '{self._database}' "
            f"({n_fields} fields known). "
            "Requires filter + projection on every fetch."
        )

    @property
    def cache_key(self) -> str:
        """Stable Redis cache key for this MongoDB source.

        Format: ``mongo:{database}:{collection}``
        """
        return f"mongo:{self._database}:{self._collection}"
