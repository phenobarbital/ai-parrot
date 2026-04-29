"""MongoDB Atlas database source for DatabaseToolkit.

Extends ``MongoSource`` for MongoDB Atlas cloud service, which uses the
``mongodb+srv://`` connection string format and ``dbtype="atlas"``.

Part of FEAT-062 — DatabaseToolkit.
Part of FEAT-136 — database-toolkit-parity (G8 credential resolution).
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
        """Return default MongoDB Atlas credentials from environment variables.

        Delegates to ``parrot.interfaces.database.get_default_credentials("atlas")``
        which reads ``ATLAS_HOST``, ``ATLAS_PORT``, ``ATLAS_DATABASE``,
        ``ATLAS_USER``, ``ATLAS_PASSWORD`` from navconfig.

        If the ``host`` field looks like a full ``mongodb+srv://`` URI or an
        Atlas cluster hostname (ending in ``.mongodb.net``), converts it to a
        proper ``dsn`` and removes individual host/port fields.

        Returns:
            Dict with Atlas connection parameters. Falls back to empty dict
            if no env vars are configured.
        """
        from parrot.interfaces.database import get_default_credentials
        creds = get_default_credentials("atlas")
        if not creds:
            return {}

        # If ATLAS_HOST is a full SRV URI, normalise it to a dsn key
        host = creds.get("host", "")
        if isinstance(host, str) and host:
            if host.startswith("mongodb+srv://") or host.startswith("mongodb://"):
                creds["dsn"] = host
                creds.pop("host", None)
                creds.pop("port", None)
            elif ".mongodb.net" in host:
                # Bare SRV hostname — convert to mongodb+srv:// DSN
                username = creds.get("username", "")
                password = creds.get("password", "")
                database = creds.get("database", "test")
                if username and password:
                    creds["dsn"] = (
                        f"mongodb+srv://{username}:{password}@{host}/{database}"
                    )
                else:
                    creds["dsn"] = f"mongodb+srv://{host}/{database}"
                creds.pop("host", None)
                creds.pop("port", None)
                creds.pop("username", None)
                creds.pop("password", None)

        return creds
