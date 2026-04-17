"""AWS DocumentDB database source for DatabaseToolkit.

Extends ``MongoSource`` for AWS DocumentDB, which uses the MongoDB wire protocol
with ``dbtype="documentdb"``. Adds SSL-by-default credential defaults required
for AWS DocumentDB connections.

Part of FEAT-062 — DatabaseToolkit.
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

        DocumentDB on AWS requires TLS connections. Default credentials
        include ``ssl=True`` and the standard AWS TLS CA bundle path.

        Returns:
            Dict with SSL defaults appropriate for AWS DocumentDB.
        """
        from parrot.interfaces.database import get_default_credentials
        base = get_default_credentials("documentdb") or {}
        if isinstance(base, str):
            base = {"dsn": base}
        elif not isinstance(base, dict):
            base = {}
        # Ensure SSL defaults for AWS DocumentDB
        base.setdefault("ssl", True)
        base.setdefault("tlsCAFile", "/etc/ssl/certs/global-bundle.pem")
        return base
