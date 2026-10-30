"""DocumentDB persistence layer for OAuth2 integrations.

``users_integrations``
    Durable credential records keyed by ``(user_id, provider)``.  One row
    per user per provider; upserts on token refresh.

The patterns here mirror :mod:`parrot.handlers.mcp_persistence`  — same
``DocumentDb`` context-manager, same ``$set / $setOnInsert`` upsert idiom.
"""
from __future__ import annotations

import logging
from typing import List, Optional

from navconfig.logging import logging  # noqa: F811 (navconfig logger replaces stdlib)

from parrot.interfaces.documentdb import DocumentDb
from parrot.auth.oauth2.models import UsersIntegrationRow

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Collection names
# ---------------------------------------------------------------------------

USERS_INTEGRATIONS_COLLECTION: str = "users_integrations"


# ---------------------------------------------------------------------------
# users_integrations repository
# ---------------------------------------------------------------------------


async def upsert_users_integration(row: UsersIntegrationRow) -> None:
    """Upsert a credential record in ``users_integrations``.

    The composite key is ``(user_id, provider)``.  A second call with the
    same key performs last-write-wins update of all other fields.

    Args:
        row: The credential record to persist.
    """
    query = {"user_id": row.user_id, "provider": row.provider}
    update_data = {
        "$set": row.model_dump(exclude={"user_id", "provider"}),
        "$setOnInsert": {"user_id": row.user_id, "provider": row.provider},
    }
    async with DocumentDb() as db:
        await db.update_one(
            USERS_INTEGRATIONS_COLLECTION, query, update_data, upsert=True
        )
    logger.debug(
        "Upserted users_integration for user_id=%s provider=%s",
        row.user_id,
        row.provider,
    )


async def get_users_integration(
    user_id: str, provider: str
) -> Optional[UsersIntegrationRow]:
    """Fetch a single credential record by ``(user_id, provider)``.

    Args:
        user_id: Navigator user identifier.
        provider: Provider identifier, e.g. ``"jira"``.

    Returns:
        The :class:`~parrot.integrations.oauth2.models.UsersIntegrationRow`
        if found, otherwise ``None``.
    """
    query = {"user_id": user_id, "provider": provider}
    async with DocumentDb() as db:
        doc = await db.read_one(USERS_INTEGRATIONS_COLLECTION, query)
    if doc is None:
        return None
    doc.pop("_id", None)
    return UsersIntegrationRow(**doc)


async def delete_users_integration(user_id: str, provider: str) -> None:
    """Hard-delete the credential record for ``(user_id, provider)``.

    A no-op if the record does not exist.

    Args:
        user_id: Navigator user identifier.
        provider: Provider identifier, e.g. ``"jira"``.
    """
    query = {"user_id": user_id, "provider": provider}
    async with DocumentDb() as db:
        await db.delete_many(USERS_INTEGRATIONS_COLLECTION, query)
    logger.debug(
        "Deleted users_integration for user_id=%s provider=%s",
        user_id,
        provider,
    )


async def list_users_integrations(user_id: str) -> List[UsersIntegrationRow]:
    """Return all provider connections stored for a principal.

    Invalid documents are logged and skipped so one malformed persisted record
    does not prevent a principal's other connections from being listed.

    Args:
        user_id: Navigator user identifier.

    Returns:
        Valid connection rows for the principal.
    """
    query = {"user_id": user_id}
    async with DocumentDb() as db:
        docs = await db.read(USERS_INTEGRATIONS_COLLECTION, query)

    rows = []
    for doc in docs:
        document = dict(doc)
        document.pop("_id", None)
        try:
            rows.append(UsersIntegrationRow.model_validate(document))
        except ValueError:
            logger.warning("Skipping invalid users_integration for user_id=%s", user_id)
    return rows
