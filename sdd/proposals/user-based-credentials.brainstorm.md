# Brainstorm: User-Based Credentials

**Date**: 2026-03-25
**Author**: Claude (SDD Brainstorm)
**Status**: exploration
**Recommended Option**: Option A

---

## Problem Statement

Users of AI-Parrot have no way to store and manage their own database credentials within the platform. When using DatabaseToolkit or DatasetManager, credentials must be configured externally each time. There is no persistent, per-user credential vault that survives across sessions.

**Who is affected**: End users who interact with databases through AI-Parrot agents.

**Why now**: The DatabaseToolkit (FEAT-062) is being built, and it needs a way for users to supply their own database connection credentials. Without this, users cannot dynamically configure database connections through the agent interface.

## Constraints & Requirements

- Must use asyncdb-syntax dictionaries (driver + connection params) as the credential format
- Credentials stored in the user session vault (navigator-session) for immediate use
- Credentials persisted to DocumentDB (via `parrot/interfaces/documentdb`) for durability across sessions
- POST/PUT must return immediately; DocumentDB persistence is fire-and-forget with retry
- Credentials are unique per user by `name` (not globally unique)
- Must follow existing class-based View pattern (`BaseView` from navigator)
- Must use `@is_authenticated()` and `@user_session()` decorators
- Credentials should be encrypted when stored in DocumentDB
- GET must support both "all credentials for user" and "single credential by name"

---

## Options Explored

### Option A: Single Class-Based View with DocumentDB Fire-and-Forget

A single `CredentialsHandler(BaseView)` class that manages the full CRUD lifecycle. Credentials are stored as asyncdb-syntax dicts keyed by name. On POST/PUT, the credential is immediately saved to the session vault and a fire-and-forget task persists it to DocumentDB using the existing `DocumentDb.save_background()` method. On GET, credentials are loaded from DocumentDB (with session cache as fallback). A startup/login hook loads persisted credentials into the session.

**Pros:**
- Simplest architecture — one handler, one collection, clear responsibility
- Leverages existing `DocumentDb.save_background()` with built-in retry and exponential backoff
- Follows established patterns in `ChatHandler`, `AgentTalk`, `ProgramsUserHandler`
- Session vault integration means credentials are immediately available after save
- No new dependencies required

**Cons:**
- GET from DocumentDB on every request (mitigated by session caching)
- Single collection must handle per-user indexing

**Effort:** Low

**Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `navigator-auth` | Authentication + vault encryption | Already in use |
| `navigator-session` | Session management (SessionData) | Already in use |
| `parrot.interfaces.documentdb` | DocumentDB persistence | Built-in fire-and-forget |
| `cryptography` / `Fernet` | Encrypt credentials at rest in DocumentDB | May need addition |

**Existing Code to Reuse:**
- `parrot/handlers/chat.py` — Class-based view pattern with `@is_authenticated()` / `@user_session()`
- `parrot/interfaces/documentdb.py` — `DocumentDb.save_background()` for fire-and-forget with retry
- `parrot/handlers/user_objects.py` — Session-scoped object management pattern
- `parrot/interfaces/credentials.py` — `CredentialsInterface` for credential validation patterns

---

### Option B: Separate Service Layer with Event-Driven Persistence

A `CredentialService` class handles all credential logic (validation, encryption, session management). The handler delegates to the service. Persistence is event-driven: credential changes emit events that a background listener processes and writes to DocumentDB. The service is session-scoped (stored in `SessionData._objects`).

**Pros:**
- Clean separation of concerns — handler is thin, logic is in the service
- Event-driven persistence is decoupled and testable independently
- Service object can be shared with DatabaseToolkit/DatasetManager directly from the session

**Cons:**
- More moving parts: handler + service + event system
- Event infrastructure may be overkill for a simple CRUD operation
- Higher effort for the same end result
- Need to manage service lifecycle in session

**Effort:** Medium

**Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `navigator-auth` | Authentication + vault | Already in use |
| `navigator-session` | Session management | Already in use |
| `parrot.interfaces.documentdb` | DocumentDB persistence | Already in use |
| `asyncio.Queue` | Event bus for persistence events | stdlib |

**Existing Code to Reuse:**
- `parrot/handlers/user_objects.py` — `UserObjectsHandler` pattern for session-scoped services
- `parrot/interfaces/documentdb.py` — DocumentDB read/write
- `parrot/handlers/jobs/job.py` — `JobManager` pattern for background task management

---

### Option C: Redis-Only with Lazy DocumentDB Sync

Credentials are stored only in the Redis-backed session vault. A periodic background task (or on-session-close hook) bulk-syncs all credentials from Redis to DocumentDB. GET reads from the session vault directly (fast). DocumentDB serves as a cold backup loaded on session start.

**Pros:**
- Fastest possible reads — always from Redis/session
- No per-request DocumentDB writes
- Simple implementation for the handler itself

**Cons:**
- Data loss risk: if Redis evicts the session before sync, credentials are lost
- Bulk sync is harder to implement correctly (conflict resolution, partial failures)
- Session TTL pressure — large credential sets increase session size
- Harder to query credentials outside the session context
- Goes against the user's stated requirement of fire-and-forget per-operation persistence

**Effort:** Medium

**Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `navigator-session` | Redis session as primary store | Already in use |
| `parrot.interfaces.documentdb` | Cold backup sync | Already in use |

**Existing Code to Reuse:**
- `parrot/handlers/chat.py` — Handler pattern
- `parrot/interfaces/documentdb.py` — Bulk write operations

---

## Recommendation

**Option A** is recommended because:

- It directly matches the stated requirements: immediate session save + fire-and-forget DocumentDB persistence
- It leverages the existing `DocumentDb.save_background()` which already has retry with exponential backoff — no need to build new infrastructure
- It follows the exact same patterns already established in `ChatHandler`, `AgentTalk`, and `ProgramsUserHandler`
- Lowest effort with no new abstractions or dependencies
- Option B's service layer adds complexity without proportional benefit at this stage — it can be refactored later if DatabaseToolkit/DatasetManager consumption requires it
- Option C violates the core requirement of per-operation persistence and introduces data loss risk

---

## Feature Description

### User-Facing Behavior

Users interact with a REST API to manage their database credentials:

- **POST `/api/v1/credentials`** — Create a new credential. Body: `{"name": "my-postgres", "driver": "pg", "host": "...", "port": 5432, "user": "...", "password": "..."}`. Returns `201` immediately. Credential is available in session vault and will be persisted to DocumentDB in background.

- **PUT `/api/v1/credentials/{name}`** — Update an existing credential by name. Body: same format as POST (partial or full update). Returns `200` immediately. Background persistence fires.

- **GET `/api/v1/credentials`** — Return all credentials for the authenticated user as a dictionary keyed by name. Loads from DocumentDB, caches in session.

- **GET `/api/v1/credentials/{name}`** — Return a single credential by name.

- **DELETE `/api/v1/credentials/{name}`** — Remove a credential from both session and DocumentDB.

### Internal Behavior

1. **Request arrives** at `CredentialsHandler`, passes through `@is_authenticated()` and `@user_session()`.
2. **POST/PUT flow**:
   - Validate the credential dict (must contain `driver` at minimum).
   - Save to session vault under key `vault:credentials:{name}` (or similar structured key).
   - Call `DocumentDb.save_background()` to persist `{"user_id": user_id, "name": name, "credential": encrypted_dict, "updated_at": timestamp}` to the `user_credentials` collection.
   - Return success response immediately.
3. **GET flow**:
   - Query DocumentDB: `{"user_id": user_id}` for all, or `{"user_id": user_id, "name": name}` for single.
   - Decrypt credential dicts.
   - Return as JSON response.
   - Optionally refresh session vault cache.
4. **DELETE flow**:
   - Remove from session vault.
   - Delete from DocumentDB (can also be fire-and-forget).

### Edge Cases & Error Handling

- **Duplicate name on POST**: Return `409 Conflict` if a credential with that name already exists for the user. Suggest using PUT to update.
- **Name not found on GET/PUT/DELETE**: Return `404 Not Found`.
- **Invalid credential format**: Return `400 Bad Request` with validation details (missing `driver`, invalid types).
- **DocumentDB write failure**: Handled by `save_background()` retry mechanism (exponential backoff, up to 3 retries). Failed writes are tracked in `FailedWrite` dataclass. Log warning on final failure.
- **DocumentDB read failure on GET**: Return `503 Service Unavailable` with message suggesting retry.
- **Session expired but credentials in DocumentDB**: Normal flow — GET loads from DocumentDB regardless of session state.
- **Large number of credentials**: Paginate GET all (optional, implement if needed).
- **Empty/null password fields**: Allow — some databases use token auth or trust-based auth.

---

## Capabilities

### New Capabilities
- `user-credentials-api`: HTTP handler for CRUD operations on per-user database credentials with session vault + DocumentDB persistence
- `credential-encryption`: Encryption/decryption layer for credentials stored in DocumentDB

### Modified Capabilities
- None (this is a standalone feature with no existing spec modifications)

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/handlers/` | extends | New `credentials.py` handler added |
| `parrot/interfaces/documentdb` | depends on | Uses `DocumentDb` for persistence and `save_background()` for fire-and-forget |
| `navigator-auth` | depends on | Uses `@is_authenticated()` decorator and vault encryption patterns |
| `navigator-session` | depends on | Uses `SessionData` for vault variable storage |
| Application routes | extends | New routes registered for `/api/v1/credentials` |
| DocumentDB `user_credentials` collection | new | New collection with index on `(user_id, name)` |

---

## Parallelism Assessment

- **Internal parallelism**: Low — this is a focused feature with a single handler, one collection, and one encryption concern. Tasks are sequential (handler depends on encryption, routes depend on handler).
- **Cross-feature independence**: High — no conflicts with in-flight specs. The `databasetoolkit` spec (FEAT-062) is a future consumer but not a dependency.
- **Recommended isolation**: `per-spec` — all tasks sequential in one worktree.
- **Rationale**: Small feature with tightly coupled components (handler, encryption, routes). Splitting into parallel worktrees would add overhead without benefit.

---

## Open Questions

- [ ] What encryption library/pattern should be used for DocumentDB at-rest encryption? Should we reuse navigator-auth's vault encryption or implement a standalone Fernet-based approach? — *Owner: Jesus*
- [ ] Should the `user_credentials` collection have a TTL or should credentials persist indefinitely? — *Owner: Jesus*
- [ ] Should there be a maximum number of credentials per user? — *Owner: Jesus*
- [ ] What is the exact URL prefix — `/api/v1/credentials` or another path convention used in the project? — *Owner: Jesus*
