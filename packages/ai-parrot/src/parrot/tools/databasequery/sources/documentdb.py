"""AWS DocumentDB database source for DatabaseToolkit.

Extends ``MongoSource`` for AWS DocumentDB, which uses the MongoDB wire protocol
with ``dbtype="documentdb"``. Adds SSL-by-default credential defaults required
for AWS DocumentDB connections.

Inherits ``test_connection()`` from ``MongoSource`` (MongoDB ping command via
the asyncdb mongo driver).

Part of FEAT-062 — DatabaseToolkit.
Part of FEAT-136 — database-toolkit-parity (TASK-933 test_connection inheritance).
"""
from __future__ import annotations

from typing import Any

from parrot.tools.databasequery.sources import register_source
from parrot.tools.databasequery.sources.mongodb import MongoSource


@register_source("documentdb")
class DocumentDBSource(MongoSource):
    """AWS DocumentDB database source.

    Extends ``MongoSource`` with DocumentDB-specific credential defaults:
    - ``ssl=True`` (required by AWS)
    - ``tlsCAFile`` defaults to the AWS global bundle path

    Uses the asyncdb ``mongo`` driver with ``dbtype="documentdb"``.
    """

    driver = "documentdb"
    dbtype = "documentdb"

    async def get_default_credentials(self) -> dict[str, Any]:
        """Return default DocumentDB credentials with SSL enabled.

        Delegates to ``parrot.interfaces.database.get_default_credentials("documentdb")``
        which reads ``DOCUMENTDB_HOSTNAME``, ``DOCUMENTDB_PORT``,
        ``DOCUMENTDB_DATABASE``, ``DOCUMENTDB_USERNAME``, ``DOCUMENTDB_PASSWORD``,
        ``DOCUMENTDB_USE_SSL``, ``DOCUMENTDB_COLLECTION`` from navconfig.

        Applies ``ssl=True`` and a default ``tlsCAFile`` path as safety
        defaults if the interface does not return them (e.g., env vars not set).

        Returns:
            Dict with DocumentDB connection parameters including SSL defaults.
        """
        from parrot.interfaces.database import get_default_credentials
        creds = get_default_credentials("documentdb")
        if not isinstance(creds, dict):
            creds = {}
        # Ensure SSL is always enabled for AWS DocumentDB
        creds.setdefault("ssl", True)
        creds.setdefault("tlsCAFile", "/etc/ssl/certs/global-bundle.pem")
        return creds
