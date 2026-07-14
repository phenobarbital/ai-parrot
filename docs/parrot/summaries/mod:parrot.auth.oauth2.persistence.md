---
type: Wiki Summary
title: parrot.auth.oauth2.persistence
id: mod:parrot.auth.oauth2.persistence
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: DocumentDB persistence layer for the OAuth2 integration collections.
relates_to:
- concept: func:parrot.auth.oauth2.persistence.delete_user_agent_toolkits_by_provider
  rel: defines
- concept: func:parrot.auth.oauth2.persistence.delete_users_integration
  rel: defines
- concept: func:parrot.auth.oauth2.persistence.get_users_integration
  rel: defines
- concept: func:parrot.auth.oauth2.persistence.list_user_agent_toolkits
  rel: defines
- concept: func:parrot.auth.oauth2.persistence.upsert_user_agent_toolkit
  rel: defines
- concept: func:parrot.auth.oauth2.persistence.upsert_users_integration
  rel: defines
- concept: mod:parrot.auth.oauth2.models
  rel: references
- concept: mod:parrot.interfaces.documentdb
  rel: references
---

# `parrot.auth.oauth2.persistence`

DocumentDB persistence layer for the OAuth2 integration collections.

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

## Functions

- `async def upsert_users_integration(row: UsersIntegrationRow) -> None` — Upsert a credential record in ``users_integrations``.
- `async def get_users_integration(user_id: str, provider: str) -> Optional[UsersIntegrationRow]` — Fetch a single credential record by ``(user_id, provider)``.
- `async def delete_users_integration(user_id: str, provider: str) -> None` — Hard-delete the credential record for ``(user_id, provider)``.
- `async def upsert_user_agent_toolkit(row: UserAgentToolkitRow) -> None` — Upsert an enablement record in ``user_agent_toolkits``.
- `async def list_user_agent_toolkits(user_id: str, agent_id: str) -> List[UserAgentToolkitRow]` — Return all enablement records for a ``(user_id, agent_id)`` pair.
- `async def delete_user_agent_toolkits_by_provider(user_id: str, provider: str) -> None` — Cascade-delete all enablement records for ``(user_id, provider)``.
