"""DocumentDB persistence layer for the OAuth2 integration collections.

Two collections are managed here:

``users_integrations``
    Durable credential records keyed by ``(user_id, provider)``.  One row
    per user per provider; upserts on token refresh.

``user_agent_toolkits``
    Per-``(user_id, agent_id, toolkit_id)`` enablement records.  Drives the
    cold-session hydration step in
    :class:`~parrot.handlers.user_objects.UserObjectsHandler`.

The patterns here mirror :mod:`parrot.handlers.mcp_persistence`  — same
``DocumentDb`` context-manager, same ``$set / $setOnInsert`` upsert idiom.
"""
from __future__ import annotations

import logging
from typing import List, Optional

from navconfig.logging import logging  # noqa: F811 (navconfig logger replaces stdlib)

from parrot.interfaces.documentdb import DocumentDb
from parrot.integrations.oauth2.models import UserAgentToolkitRow, UsersIntegrationRow

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Collection names
# ---------------------------------------------------------------------------

USERS_INTEGRATIONS_COLLECTION: str = "users_integrations"
USER_AGENT_TOOLKITS_COLLECTION: str = "user_agent_toolkits"


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


# ---------------------------------------------------------------------------
# user_agent_toolkits repository
# ---------------------------------------------------------------------------


async def upsert_user_agent_toolkit(row: UserAgentToolkitRow) -> None:
    """Upsert an enablement record in ``user_agent_toolkits``.

    The composite key is ``(user_id, agent_id, toolkit_id)``.  Calling this
    twice is idempotent — only ``enabled_at`` and ``provider`` are updated on
    a second call.

    Args:
        row: The enablement record to persist.
    """
    query = {
        "user_id": row.user_id,
        "agent_id": row.agent_id,
        "toolkit_id": row.toolkit_id,
    }
    update_data = {
        "$set": row.model_dump(exclude={"user_id", "agent_id", "toolkit_id"}),
        "$setOnInsert": {
            "user_id": row.user_id,
            "agent_id": row.agent_id,
            "toolkit_id": row.toolkit_id,
        },
    }
    async with DocumentDb() as db:
        await db.update_one(
            USER_AGENT_TOOLKITS_COLLECTION, query, update_data, upsert=True
        )
    logger.debug(
        "Upserted user_agent_toolkit for user_id=%s agent_id=%s toolkit_id=%s",
        row.user_id,
        row.agent_id,
        row.toolkit_id,
    )


async def list_user_agent_toolkits(
    user_id: str, agent_id: str
) -> List[UserAgentToolkitRow]:
    """Return all enablement records for a ``(user_id, agent_id)`` pair.

    Args:
        user_id: Navigator user identifier.
        agent_id: Agent identifier.

    Returns:
        List of :class:`~parrot.integrations.oauth2.models.UserAgentToolkitRow`
        instances.  Empty list when none are found.
    """
    query = {"user_id": user_id, "agent_id": agent_id}
    async with DocumentDb() as db:
        docs = await db.read(USER_AGENT_TOOLKITS_COLLECTION, query)
    rows = []
    for doc in docs:
        doc.pop("_id", None)
        rows.append(UserAgentToolkitRow(**doc))
    return rows


async def delete_user_agent_toolkits_by_provider(
    user_id: str, provider: str
) -> None:
    """Cascade-delete all enablement records for ``(user_id, provider)``.

    This implements the disconnect cascade rule: disconnecting a provider
    removes ALL ``user_agent_toolkits`` rows for that user+provider regardless
    of ``agent_id``.  A no-op when no rows exist.

    Args:
        user_id: Navigator user identifier.
        provider: Provider identifier, e.g. ``"jira"``.
    """
    query = {"user_id": user_id, "provider": provider}
    async with DocumentDb() as db:
        await db.delete_many(USER_AGENT_TOOLKITS_COLLECTION, query)
    logger.debug(
        "Cascade-deleted user_agent_toolkits for user_id=%s provider=%s",
        user_id,
        provider,
    )
