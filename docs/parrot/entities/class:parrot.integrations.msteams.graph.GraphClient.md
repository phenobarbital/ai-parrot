---
type: Wiki Entity
title: GraphClient
id: class:parrot.integrations.msteams.graph.GraphClient
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Async Microsoft Graph client for the Teams HITL channel.
---

# GraphClient

Defined in [`parrot.integrations.msteams.graph`](../summaries/mod:parrot.integrations.msteams.graph.md).

```python
class GraphClient
```

Async Microsoft Graph client for the Teams HITL channel.

Handles:
- Client-credentials token acquisition with in-process expiry caching.
- ``get_user_by_email``: resolves an email to a
  :class:`ResolvedTeamsUser` via ``/users/{upn}`` first, falling back
  to ``/users?$filter=mail eq '{email}'`` on 404.
- ``get_user_manager``: returns the Graph user object for ``/users/{upn}/manager``.

All methods return ``None`` (never raise) on any Graph error so the
caller (``TeamsHumanChannel``) can fail-fast cleanly.

Args:
    client_id: Graph app registration client ID.
    client_secret: Graph app registration client secret.
    tenant_id: AAD tenant ID (for the token URL).
    logger: Optional logger. Defaults to module-level logger.

## Methods

- `async def close(self) -> None` — Close the underlying aiohttp session and release resources.
- `async def get_user_by_email(self, email: str) -> Optional[ResolvedTeamsUser]` — Resolve an email address to a :class:`ResolvedTeamsUser`.
- `async def get_user_manager(self, upn: str) -> Optional[Dict[str, Any]]` — Return the Graph user object for a user's manager.
- `async def upload_file(self, file_path: Union[str, Path], *, user: str, folder: str='A2UI-Artifacts') -> Optional[str]` — Upload a local file to a user's OneDrive and return an org-view share link.
