# TASK-760: Identity Mapping Service

**Feature**: FEAT-108 — Jira OAuth2 3LO Authentication from Telegram WebApp
**Spec**: `sdd/specs/FEAT-108-jiratoolkit-auth-telegram.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-756
**Assigned-to**: unassigned

---

## Context

This task creates a service for managing user identity records in the
`auth.users_identities` table. It provides CRUD operations to link a
navigator-auth user_id with external provider identities (Telegram, Jira, etc.)
using the `UserIdentity` model from navigator-auth.

Implements Spec Module 5.

---

## Scope

- Create `parrot/services/identity_mapping.py`.
- Implement `IdentityMappingService` class with:
  - `__init__(db_pool)` — accepts an asyncdb/asyncpg connection pool
  - `async upsert_identity(nav_user_id, auth_provider, auth_data, display_name=None, email=None)` — insert or update on `(user_id, auth_provider)` conflict
  - `async get_identity(nav_user_id, auth_provider)` — retrieve `auth_data` dict
  - `async get_all_identities(nav_user_id)` — list all provider identities for a user
  - `async delete_identity(nav_user_id, auth_provider)` — remove a provider identity
- Handle the DB interaction using navigator-auth's connection pattern (asyncdb or
  direct asyncpg via the `authdb` pool).
- Write unit tests with mocked DB pool.

**NOT in scope**: HTTP endpoints for identity management, vault storage (TASK-761),
or integration with the wrapper (TASK-763).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/services/__init__.py` | CREATE (if missing) | Package init |
| `packages/ai-parrot/src/parrot/services/identity_mapping.py` | CREATE | IdentityMappingService |
| `packages/ai-parrot/tests/unit/test_identity_mapping.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# navigator-auth UserIdentity model (user-provided, external package)
# EXACT import path must be verified at implementation time — see Open Questions
# Likely: from navigator_auth.models import UserIdentity
# OR use raw SQL via the authdb pool

# For DB access pattern, reference credentials handler:
# packages/ai-parrot/src/parrot/handlers/credentials.py uses:
from navigator_session import get_session  # credentials.py, used for session access
```

### Existing Signatures to Use
```python
# User-provided UserIdentity model (navigator-auth, external)
# Table: auth.users_identities
class UserIdentity(Model):
    identity_id: UUID    # PK, auto-generated
    display_name: str
    email: str
    user_id: User        # FK to auth.users, this is the navigator-auth internal ID
    auth_provider: str   # e.g., "telegram", "jira"
    auth_data: Optional[dict]  # JSONB column
    attributes: Optional[dict]
    created_at: datetime

    class Meta:
        name = "user_identities"
        schema = AUTH_DB_SCHEMA  # typically "auth"
```

### Does NOT Exist
- ~~`parrot.services.identity_mapping`~~ — does not exist yet (this task creates it)
- ~~`parrot.services`~~ — package may not exist (check, create `__init__.py` if needed)
- ~~`UserIdentity` import in ai-parrot~~ — the model lives in navigator-auth, not imported anywhere in parrot yet
- ~~`IdentityMappingService`~~ — does not exist yet (this task creates it)

---

## Implementation Notes

### Pattern to Follow
Since the `UserIdentity` model is in navigator-auth and its exact import path is
uncertain, prefer **raw SQL via the authdb pool** for reliability:

```python
class IdentityMappingService:
    def __init__(self, db_pool) -> None:
        self._pool = db_pool
        self.logger = logging.getLogger(__name__)

    async def upsert_identity(
        self,
        nav_user_id: str,
        auth_provider: str,
        auth_data: Dict[str, Any],
        display_name: Optional[str] = None,
        email: Optional[str] = None,
    ) -> None:
        query = """
            INSERT INTO auth.users_identities
                (user_id, auth_provider, auth_data, display_name, email, created_at)
            VALUES ($1, $2, $3::jsonb, $4, $5, NOW())
            ON CONFLICT (user_id, auth_provider)
            DO UPDATE SET
                auth_data = EXCLUDED.auth_data,
                display_name = COALESCE(EXCLUDED.display_name, auth.users_identities.display_name),
                email = COALESCE(EXCLUDED.email, auth.users_identities.email)
        """
        async with self._pool.acquire() as conn:
            await conn.execute(query, nav_user_id, auth_provider,
                               json.dumps(auth_data), display_name, email)
```

### Key Constraints
- The `auth.users_identities` table has a composite unique constraint on `(user_id, auth_provider)` — use `ON CONFLICT` for upsert
- `auth_data` is JSONB — serialize with `json.dumps()`, deserialize with `json.loads()`
- The `user_id` column references `auth.users(user_id)` — must be a valid navigator-auth user ID
- Use the `authdb` pool available at `app.get("authdb")` in the aiohttp app context
- All DB operations must be async

### References in Codebase
- `packages/ai-parrot/src/parrot/handlers/credentials.py:71-157` — pattern for DB access with pool
- User-provided `UserIdentity` model definition (see Codebase Contract above)

---

## Acceptance Criteria

- [ ] `IdentityMappingService` class with `upsert_identity`, `get_identity`, `get_all_identities`, `delete_identity`
- [ ] Upsert handles both insert and update (on provider conflict)
- [ ] `auth_data` properly serialized/deserialized as JSON
- [ ] All methods are async
- [ ] All tests pass: `pytest packages/ai-parrot/tests/unit/test_identity_mapping.py -v`
- [ ] Importable: `from parrot.services.identity_mapping import IdentityMappingService`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/test_identity_mapping.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from parrot.services.identity_mapping import IdentityMappingService


@pytest.fixture
def mock_pool():
    pool = AsyncMock()
    conn = AsyncMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool, conn


@pytest.fixture
def service(mock_pool):
    pool, _ = mock_pool
    return IdentityMappingService(pool)


class TestIdentityMappingService:
    async def test_upsert_identity(self, service, mock_pool):
        _, conn = mock_pool
        await service.upsert_identity(
            nav_user_id="user-123",
            auth_provider="jira",
            auth_data={"account_id": "jira-456", "cloud_id": "cloud-789"},
            display_name="Jira User",
            email="jira@example.com",
        )
        conn.execute.assert_called_once()
        call_args = conn.execute.call_args
        assert "INSERT INTO auth.users_identities" in call_args[0][0]

    async def test_get_identity(self, service, mock_pool):
        _, conn = mock_pool
        conn.fetchrow.return_value = {
            "auth_data": '{"account_id": "jira-456"}',
            "display_name": "Jira User",
        }
        result = await service.get_identity("user-123", "jira")
        assert result is not None

    async def test_get_identity_not_found(self, service, mock_pool):
        _, conn = mock_pool
        conn.fetchrow.return_value = None
        result = await service.get_identity("user-123", "nonexistent")
        assert result is None

    async def test_get_all_identities(self, service, mock_pool):
        _, conn = mock_pool
        conn.fetch.return_value = [
            {"auth_provider": "telegram", "auth_data": '{"telegram_id": 123}'},
            {"auth_provider": "jira", "auth_data": '{"account_id": "abc"}'},
        ]
        results = await service.get_all_identities("user-123")
        assert len(results) == 2
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** for full context
2. **Check dependencies** — verify TASK-756 is completed
3. **Check if `parrot/services/` package exists** — create `__init__.py` if needed
4. **Verify the `auth.users_identities` table schema** if possible (check navigator-auth)
5. **Implement** the identity mapping service
6. **Verify** all acceptance criteria
7. **Move this file** to `sdd/tasks/completed/`
8. **Update index** → `"done"`

---

## Completion Note

**Completed by**: sdd-worker (Claude Opus 4.7)
**Date**: 2026-04-19
**Notes**:

- Created `packages/ai-parrot/src/parrot/services/identity_mapping.py` with
  `IdentityMappingService` using raw SQL against the `authdb` asyncpg pool.
- Used the correct table name `auth.user_identities` (matches
  `UserIdentity.Meta.name = "user_identities"` + `schema = AUTH_DB_SCHEMA`).
  Note: the task's example SQL incorrectly showed `auth.users_identities`;
  I followed the model (single source of truth).
- Implemented `upsert_identity`, `get_identity`, `get_all_identities`, and
  `delete_identity` — all async.
- JSONB `auth_data` is stored via `json.dumps()` (cast `$3::jsonb`) and
  normalized on read via `_decode_auth_data()` which handles dict / str /
  bytes / malformed input.
- `__init__.py` was untouched — we did NOT export `IdentityMappingService`
  from the package init to avoid loading DB deps when importing
  `parrot.services` (heavyweight modules already imported there).
- Created `packages/ai-parrot/tests/unit/test_identity_mapping.py` with
  14 tests — all pass.

**Deviations from spec**: table name corrected to `auth.user_identities`
(task example had a typo).
