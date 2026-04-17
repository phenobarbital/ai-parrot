"""MongoDB Atlas database source for DatabaseToolkit.

Extends ``MongoSource`` for MongoDB Atlas cloud service, which uses the
``mongodb+srv://`` connection string format and ``dbtype="atlas"``.

Part of FEAT-062 — DatabaseToolkit.
"""
from __future__ import annotations

from typing import Any

from parrot.tools.databasequery.sources import register_source
from parrot.tools.databasequery.sources.mongodb import MongoSource


@register_source("atlas")
class AtlasSource(MongoSource):
    """MongoDB Atlas database source.

    Extends ``MongoSource`` with Atlas-specific credential handling:
    the ``mongodb+srv://`` URI scheme is expected for Atlas connections.

    Uses the asyncdb ``mongo`` driver with ``dbtype="atlas"``.
    """

    driver = "atlas"
    dbtype = "atlas"

    async def get_default_credentials(self) -> dict[str, Any]:
        """Return default MongoDB Atlas credentials.

        Atlas connections use ``mongodb+srv://`` URI format.
        If a DSN is configured, it should use this scheme.

        Returns:
            Dict with Atlas connection credentials, or empty dict if
            no defaults are configured.
        """
        from parrot.interfaces.database import get_default_credentials
        dsn = get_default_credentials("atlas")
        if not dsn:
            dsn = get_default_credentials("mongo")
        if dsn and isinstance(dsn, str):
            # Ensure atlas DSN uses mongodb+srv:// format
            if not dsn.startswith("mongodb+srv://") and not dsn.startswith("mongodb://"):
                dsn = f"mongodb+srv://{dsn}"
            return {"dsn": dsn}
        return {}
