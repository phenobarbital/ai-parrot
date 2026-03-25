# Feature Specification: User-Based Credentials

**Feature ID**: FEAT-063
**Date**: 2026-03-25
**Author**: Claude (SDD Spec)
**Status**: draft
**Target version**: 1.x
**Brainstorm**: sdd/proposals/user-based-credentials.brainstorm.md

---

## 1. Motivation & Business Requirements

### Problem Statement

Users of AI-Parrot have no way to store and manage their own database credentials within the platform. When using DatabaseToolkit or DatasetManager, credentials must be configured externally each time. There is no persistent, per-user credential vault that survives across sessions.

The DatabaseToolkit (FEAT-062) is being built and needs a mechanism for users to supply their own database connection credentials dynamically. Without this, users cannot configure database connections through the agent interface.

### Goals
- Provide a REST API for users to create, read, update, and delete database credentials (asyncdb-syntax dicts)
- Store credentials in the user session vault for immediate availability
- Persist credentials to DocumentDB for durability across sessions, using fire-and-forget with retry
- Encrypt credentials at rest in DocumentDB using navigator-auth's existing encryption
- Credentials are unique per user by name (not globally unique)

### Non-Goals (explicitly out of scope)
- DatabaseToolkit/DatasetManager consumption of credentials (future integration)
- Credential sharing between users
- Credential rotation or expiration policies
- Admin-level credential management or bulk operations
- OAuth/token-based credential types (only asyncdb dictionary format)

---

## 2. Architectural Design

### Overview

A single class-based HTTP handler (`CredentialsHandler`) extends `BaseView` and provides CRUD endpoints at `/api/v1/users/credentials`. On write operations (POST/PUT), credentials are immediately saved to the user's session vault and asynchronously persisted to DocumentDB via `DocumentDb.save_background()`. On read (GET), credentials are loaded from DocumentDB. Encryption uses navigator-session's `encrypt_for_db` / `decrypt_for_db` functions.

### Component Diagram
```
Client
  │
  ▼
CredentialsHandler (BaseView)
  ├── @is_authenticated()
  ├── @user_session()
  │
  ├── POST/PUT ──→ validate ──→ session vault ──→ response (201/200)
  │                                   │
  │                                   └──→ DocumentDb.save_background() [fire-and-forget]
  │                                              │
  │                                              └──→ retry on failure (exponential backoff)
  │
  ├── GET ──→ DocumentDb.read() ──→ decrypt ──→ response (200)
  │
  └── DELETE ──→ session vault remove ──→ DocumentDb.delete() ──→ response (200)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `navigator.views.BaseView` | extends | Class-based view pattern with HTTP method dispatch |
| `navigator_auth.decorators` | uses | `@is_authenticated()` and `@user_session()` for auth + session |
| `navigator_session.vault.crypto` | uses | `encrypt_for_db()` / `decrypt_for_db()` for at-rest encryption |
| `parrot.interfaces.documentdb.DocumentDb` | uses | `save_background()`, `read()`, `read_one()`, `delete()` |
| `navigator_session.data.SessionData` | uses | Session vault for immediate credential availability |
| Application router | extends | New routes at `/api/v1/users/credentials` |

### Data Models
```python
from pydantic import BaseModel, Field
from typing import Optional, Any
from datetime import datetime


class CredentialPayload(BaseModel):
    """Input model for creating/updating a credential."""
    name: str = Field(..., min_length=1, max_length=128, description="Unique credential name per user")
    driver: str = Field(..., description="asyncdb driver name (e.g., 'pg', 'mysql', 'bigquery')")
    params: dict[str, Any] = Field(
        default_factory=dict,
        description="Connection parameters (host, port, user, password, database, etc.)"
    )


class CredentialDocument(BaseModel):
    """DocumentDB storage model (credential values are encrypted)."""
    user_id: str
    name: str
    credential: str = Field(..., description="Encrypted JSON string of driver + params")
    created_at: datetime
    updated_at: datetime


class CredentialResponse(BaseModel):
    """Response model for a single credential."""
    name: str
    driver: str
    params: dict[str, Any]
```

### New Public Interfaces
```python
@is_authenticated()
@user_session()
class CredentialsHandler(BaseView):
    """CRUD handler for user database credentials."""

    async def get(self) -> web.Response:
        """GET /api/v1/users/credentials — all credentials for user.
        GET /api/v1/users/credentials/{name} — single credential by name."""
        ...

    async def post(self) -> web.Response:
        """POST /api/v1/users/credentials — create a new credential."""
        ...

    async def put(self) -> web.Response:
        """PUT /api/v1/users/credentials/{name} — update existing credential."""
        ...

    async def delete(self) -> web.Response:
        """DELETE /api/v1/users/credentials/{name} — remove a credential."""
        ...
```

---

## 3. Module Breakdown

### Module 1: Credential Data Models
- **Path**: `packages/ai-parrot/src/parrot/handlers/models/credentials.py`
- **Responsibility**: Pydantic models for credential payload validation, DocumentDB document schema, and API response format
- **Depends on**: None

### Module 2: Credential Encryption Helpers
- **Path**: `packages/ai-parrot/src/parrot/handlers/credentials_utils.py`
- **Responsibility**: Thin wrapper around `navigator_session.vault.crypto.encrypt_for_db` / `decrypt_for_db` specialized for credential dicts. Handles serialization (dict -> JSON bytes -> encrypted) and deserialization (encrypted -> JSON bytes -> dict). Manages master key retrieval from app config.
- **Depends on**: Module 1, `navigator_session.vault.crypto`

### Module 3: CredentialsHandler (HTTP View)
- **Path**: `packages/ai-parrot/src/parrot/handlers/credentials.py`
- **Responsibility**: Class-based view implementing GET/POST/PUT/DELETE. Validates input via Pydantic models, manages session vault, calls DocumentDB for persistence (fire-and-forget on writes, direct on reads), handles error responses.
- **Depends on**: Module 1, Module 2, `parrot.interfaces.documentdb.DocumentDb`

### Module 4: Route Registration
- **Path**: `packages/ai-parrot/src/parrot/handlers/credentials.py` (bottom of file or separate setup function)
- **Responsibility**: Register `/api/v1/users/credentials` and `/api/v1/users/credentials/{name}` routes with the application router. Ensure DocumentDB collection `user_credentials` has a compound index on `(user_id, name)`.
- **Depends on**: Module 3

### Module 5: Tests
- **Path**: `tests/handlers/test_credentials.py`
- **Responsibility**: Unit and integration tests for all CRUD operations, encryption round-trip, session vault behavior, fire-and-forget verification, and error cases.
- **Depends on**: Modules 1-4

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_credential_payload_valid` | Module 1 | Valid asyncdb-style dict passes validation |
| `test_credential_payload_missing_driver` | Module 1 | Rejects payload without `driver` field |
| `test_credential_payload_name_too_long` | Module 1 | Rejects name exceeding 128 chars |
| `test_encrypt_credential_roundtrip` | Module 2 | Encrypt then decrypt returns original dict |
| `test_encrypt_handles_special_chars` | Module 2 | Passwords with special chars survive encryption |
| `test_post_creates_credential` | Module 3 | POST returns 201, credential in session |
| `test_post_duplicate_name_409` | Module 3 | POST with existing name returns 409 |
| `test_put_updates_credential` | Module 3 | PUT returns 200, credential updated |
| `test_put_nonexistent_404` | Module 3 | PUT on unknown name returns 404 |
| `test_get_all_credentials` | Module 3 | GET returns dict of all user credentials |
| `test_get_single_credential` | Module 3 | GET with name returns single credential |
| `test_get_nonexistent_404` | Module 3 | GET unknown name returns 404 |
| `test_delete_credential` | Module 3 | DELETE removes from session and DocumentDB |
| `test_delete_nonexistent_404` | Module 3 | DELETE unknown name returns 404 |
| `test_unauthenticated_401` | Module 3 | Request without auth returns 401 |

### Integration Tests
| Test | Description |
|---|---|
| `test_full_crud_lifecycle` | Create -> Read -> Update -> Read -> Delete -> Verify gone |
| `test_credentials_persist_to_documentdb` | Create credential, verify it exists in DocumentDB |
| `test_credentials_unique_per_user` | Two users can have same credential name |
| `test_fire_and_forget_completes` | POST returns immediately, background task writes to DocumentDB |

### Test Data / Fixtures
```python
@pytest.fixture
def sample_credential():
    return {
        "name": "my-postgres",
        "driver": "pg",
        "params": {
            "host": "localhost",
            "port": 5432,
            "user": "testuser",
            "password": "testpass",
            "database": "mydb"
        }
    }

@pytest.fixture
def sample_mongo_credential():
    return {
        "name": "my-mongo",
        "driver": "mongo",
        "params": {
            "host": "localhost",
            "port": 27017,
            "database": "analytics"
        }
    }
```

---

## 5. Acceptance Criteria

- [ ] POST `/api/v1/users/credentials` creates a credential and returns 201
- [ ] PUT `/api/v1/users/credentials/{name}` updates a credential and returns 200
- [ ] GET `/api/v1/users/credentials` returns all credentials for the authenticated user
- [ ] GET `/api/v1/users/credentials/{name}` returns a single credential by name
- [ ] DELETE `/api/v1/users/credentials/{name}` removes the credential
- [ ] POST/PUT save to session vault immediately and return before DocumentDB write completes
- [ ] DocumentDB writes use `save_background()` with retry on failure
- [ ] Credentials are encrypted at rest in DocumentDB using navigator-session vault crypto
- [ ] Credential names are unique per user (not globally)
- [ ] Duplicate name on POST returns 409 Conflict
- [ ] Missing name on GET/PUT/DELETE returns 404 Not Found
- [ ] Invalid payload returns 400 Bad Request with details
- [ ] Unauthenticated requests return 401
- [ ] All unit tests pass
- [ ] No breaking changes to existing handlers or routes

---

## 6. Implementation Notes & Constraints

### Patterns to Follow
- Use `BaseView` from `navigator.views` — same pattern as `ChatHandler`, `AgentTalk`
- Apply `@is_authenticated()` and `@user_session()` decorators at class level
- Use `self.session` for vault access, `self.user` for user identity
- Use `DocumentDb` context manager for read operations
- Use `DocumentDb.save_background()` for fire-and-forget writes
- Use `encrypt_for_db()` / `decrypt_for_db()` from `navigator_session.vault.crypto` for encryption
- Pydantic models for all input validation and response serialization
- Async-first — no blocking I/O
- `self.logger` for all logging

### Session Vault Key Convention
Credentials stored in the session under key `_credentials:{name}` within the session data dictionary. All credentials can be collected by iterating keys with the `_credentials:` prefix.

### DocumentDB Collection Schema
- **Collection**: `user_credentials`
- **Compound index**: `(user_id, name)` — unique
- **Document structure**:
  ```json
  {
    "user_id": "uuid-string",
    "name": "my-postgres",
    "credential": "<encrypted-base64-string>",
    "created_at": "2026-03-25T10:00:00Z",
    "updated_at": "2026-03-25T10:00:00Z"
  }
  ```

### Known Risks / Gotchas
- **Master key availability**: `encrypt_for_db` requires a master key. Must ensure the key is available in the app config at handler init time. If missing, credential writes should fail gracefully with a 500 error.
- **Session vault size**: Large numbers of credentials in the session could increase Redis memory. Mitigated by storing only names + decrypted dicts (no metadata).
- **Fire-and-forget observability**: If `save_background()` silently fails after retries, credentials exist in session but not in DocumentDB. Log at WARNING level. Consider a periodic reconciliation in the future (out of scope).

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `navigator-auth` | existing | Authentication decorators, vault integration |
| `navigator-session` | existing | SessionData, vault crypto (`encrypt_for_db` / `decrypt_for_db`) |
| `parrot.interfaces.documentdb` | existing | DocumentDB interface with `save_background()` |
| `pydantic` | existing | Input validation and response models |

---

## 7. Open Questions

- [x] Encryption approach — **Resolved**: Re-use navigator-auth / navigator-session vault encryption (`encrypt_for_db` / `decrypt_for_db`)
- [x] Collection TTL — **Resolved**: Credentials persist indefinitely, no TTL
- [x] URL prefix — **Resolved**: `/api/v1/users/credentials`
- [x] Max credentials per user — **Resolved**: No limit

---

## Worktree Strategy

- **Isolation**: `per-spec` — all tasks sequential in one worktree
- **Rationale**: Small feature with tightly coupled modules (models -> encryption -> handler -> routes -> tests). No meaningful parallelism.
- **Cross-feature dependencies**: None. FEAT-062 (DatabaseToolkit) is a future consumer but not a blocker.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-03-25 | Claude | Initial draft from brainstorm |
