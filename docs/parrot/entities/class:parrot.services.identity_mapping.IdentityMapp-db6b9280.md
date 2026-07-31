---
type: Wiki Entity
title: IdentityMappingService
id: class:parrot.services.identity_mapping.IdentityMappingService
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: CRUD service for ``auth.user_identities`` records.
---

# IdentityMappingService

Defined in [`parrot.services.identity_mapping`](../summaries/mod:parrot.services.identity_mapping.md).

```python
class IdentityMappingService
```

CRUD service for ``auth.user_identities`` records.

Args:
    db_pool: An asyncpg-compatible connection pool (typically the
        navigator-auth ``authdb`` pool obtained from
        ``app.get("authdb")``).

Example:
    >>> service = IdentityMappingService(db_pool=app["authdb"])
    >>> await service.upsert_identity(
    ...     nav_user_id="nav-123",
    ...     auth_provider="jira",
    ...     auth_data={"account_id": "abc", "cloud_id": "def"},
    ...     display_name="Jane Doe",
    ...     email="jane@example.com",
    ... )

## Methods

- `async def upsert_identity(self, nav_user_id: str, auth_provider: str, auth_data: Dict[str, Any], display_name: Optional[str]=None, email: Optional[str]=None) -> None` — Create or update a user identity record.
- `async def get_identity(self, nav_user_id: str, auth_provider: str) -> Optional[Dict[str, Any]]` — Fetch a single identity record by (user_id, provider).
- `async def get_all_identities(self, nav_user_id: str) -> List[Dict[str, Any]]` — List all identity records for a user.
- `async def delete_identity(self, nav_user_id: str, auth_provider: str) -> None` — Remove the identity record for (user_id, provider).
