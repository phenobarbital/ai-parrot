# Feature Specification: API Bot Creation — Normalization & Provisioning

**Feature ID**: FEAT-049
**Date**: 2026-03-17
**Author**: Jesus Lara
**Status**: approved
**Target version**: next
**Brainstorm**: `sdd/proposals/new-api-bot-creation.brainstorm.md`

---

## 1. Motivation & Business Requirements

> Harden the `/api/v1/bots` PUT endpoint with name slugification, de-duplication, registry encapsulation, and eager PgVector table provisioning.

### Problem Statement

The `ChatbotHandler` (`parrot/handlers/bots.py`) manages agent CRUD via `/api/v1/bots` but has three deficiencies:

1. **No name sanitization** — Agent names are stored verbatim. Spaces, mixed casing, and special characters break URL routing (`/api/v1/bots/{name}`) and cause inconsistent lookups between DB and registry.
2. **Direct registry internals access** — The handler reads/writes `registry._registered_agents[name]` (a protected dict) instead of using the public `registry.get_metadata(name)` method.
3. **No vector store provisioning at creation time** — When a user creates an agent with `vector_store_config`, the PgVector table is NOT created until first use, causing confusing errors (`public.None` table name).

### Goals

1. **Slugify agent names** — Automatically convert user-provided names to URL-safe slugs during database agent creation.
2. **De-duplicate slugs** — When a slug collision occurs, append a numeric suffix (`-2`, `-3`, ...) instead of rejecting the request.
3. **Replace registry internals access** — All `registry._registered_agents` usage in the handler replaced with `registry.get_metadata()`.
4. **Eager vector store provisioning** — When the user provides `table` and `schema` in `vector_store_config`, create the PgVector table immediately during bot creation.
5. **Preserve original name** — Store the original user-provided name in the `description` field for UI display.

### Non-Goals (explicitly out of scope)

- Retroactively normalizing existing agent names in the database or registry.
- Modifying the registry/YAML creation path (`_put_registry`) — only the database path is affected.
- Adding new columns (`display_name`, `vector_store_status`) to the DB schema — no migrations.
- Changing how `chatbot_id` (UUID) works — it remains the primary key.
- Defaulting vector store table names — if the user doesn't provide `table`/`schema`, no provisioning occurs.

---

## 2. Architectural Design

### Overview

The design follows **Option B** from the brainstorm: a reusable utility layer (`parrot/utils/naming.py`) combined with a handler refactor.

```
PUT /api/v1/bots
    │
    ▼
ChatbotHandler._put_database()
    │
    ├─ 1. slugify_name(payload.name)          ← parrot/utils/naming.py
    ├─ 2. deduplicate_name(slug, _check_dup)  ← parrot/utils/naming.py
    ├─ 3. Preserve original name in description
    ├─ 4. Create BotModel + insert into DB
    ├─ 5. Register into BotManager
    ├─ 6. _provision_vector_store(bot, config) ← new handler method
    │       ├─ Extract table/schema from config
    │       ├─ define_store() → configure_store()
    │       ├─ store.connection() → store.create_collection()
    │       └─ On failure: log error, return "pending"
    └─ 7. Return response with final name + vector store status
```

### Integration Points

| Component | Role | Change Type |
|---|---|---|
| `parrot/utils/naming.py` | Slug generation + dedup utilities | **New file** |
| `parrot/handlers/bots.py` | Handler refactored for normalization + provisioning | **Modified** |
| `parrot/registry/registry.py` | `get_metadata()` used (already exists) | **No change** |
| `parrot/stores/postgres.py` | `create_collection()` called (already exists) | **No change** |
| `parrot/interfaces/vector.py` | `define_store()`, `configure_store()` called | **No change** |
| `parrot/handlers/models.py` | `description` field used for original name | **No change** |

---

## 3. Module Breakdown

### Module 1: `parrot/utils/naming.py` (New)

**Purpose**: Reusable name normalization utilities.

**Functions:**

- `slugify_name(name: str) -> str`
  - Strip leading/trailing whitespace.
  - Lowercase the string.
  - Replace any non-alphanumeric character (except hyphens) with a hyphen.
  - Collapse consecutive hyphens into one.
  - Strip leading/trailing hyphens.
  - Raise `ValueError` if the result is empty.

- `deduplicate_name(slug: str, exists_fn: Callable[[str], Awaitable[bool]]) -> str`
  - Call `exists_fn(slug)`. If falsy, return slug.
  - Otherwise try `slug-2`, `slug-3`, ... up to `slug-99`.
  - If all taken, raise `ValueError`.
  - `exists_fn` signature: `async (name: str) -> str | None` (returns source string if exists, None if free).

**Dependencies**: `re` (stdlib only — no external slug library needed for the primary use case of spaces/special chars → hyphens).

### Module 2: `parrot/handlers/bots.py` — Handler Refactor (Modified)

**Changes:**

1. **`_put_database()` method** — Add name normalization flow:
   - Import and call `slugify_name()` on the incoming name.
   - Call `deduplicate_name()` with `_check_duplicate` as the exists function.
   - If original name differs from slug, prepend `"Display name: {original}. "` to the description field.
   - After bot creation and registration, call new `_provision_vector_store()`.
   - Include `vector_store_status` in response.

2. **`_provision_vector_store()` method** (New private method):
   - Accepts bot instance and `vector_store_config` dict.
   - Extracts `table` and `schema`. If either is missing, returns `{"status": "none"}`.
   - Calls `bot.define_store(vector_store=store_type, table=table, schema=schema, ...)`.
   - Calls `bot.configure_store()`.
   - Calls `await bot.store.connection()`.
   - Calls `await bot.store.create_collection(table=table, schema=schema, dimension=dimension)`.
   - On success: returns `{"status": "ready"}`.
   - On exception: logs error, returns `{"status": "pending", "error": str(e)}`.

3. **Registry access cleanup** — All occurrences of:
   - `registry._registered_agents.get(name)` → `registry.get_metadata(name)`
   - `registry._registered_agents[name]` (reads) → `registry.get_metadata(name)`

### Module 3: Unit Tests (New)

**File**: `tests/test_naming.py`

- `test_slugify_name_basic` — `"My Cool Bot"` → `"my-cool-bot"`
- `test_slugify_name_special_chars` — `"Bot @#$ Test!"` → `"bot-test"`
- `test_slugify_name_consecutive_hyphens` — `"Bot - - Test"` → `"bot-test"`
- `test_slugify_name_trim` — `"  My Bot  "` → `"my-bot"`
- `test_slugify_name_empty_raises` — `"@#$"` → `ValueError`
- `test_slugify_name_already_slug` — `"my-bot"` → `"my-bot"` (idempotent)
- `test_deduplicate_name_no_conflict` — returns slug unchanged
- `test_deduplicate_name_one_conflict` — returns `"my-bot-2"`
- `test_deduplicate_name_multiple_conflicts` — returns `"my-bot-4"` when 1-3 taken
- `test_deduplicate_name_exhaustion` — raises `ValueError` after 99 attempts

---

## 4. API Contract

### PUT `/api/v1/bots` — Create Agent (Database Path)

**Request** (unchanged payload structure):
```json
{
  "name": "My Cool Bot",
  "description": "A helpful assistant",
  "operation_mode": "conversational",
  "vector_store_config": {
    "name": "postgres",
    "table": "my_cool_bot_docs",
    "schema": "public",
    "embedding_model": "sentence-transformers/all-MiniLM-L12-v2",
    "dimension": 384
  }
}
```

**Response** (augmented):
```json
{
  "chatbot_id": "a1b2c3d4-...",
  "name": "my-cool-bot",
  "source": "database",
  "vector_store_status": "ready"
}
```

**Possible `vector_store_status` values:**
- `"none"` — No vector store config provided, or `table`/`schema` missing.
- `"ready"` — PgVector table created successfully.
- `"pending"` — Creation failed; `vector_store_error` field contains the reason.

**New error responses:**
- `400` — Name is empty after slugification.
- `409` — Slug exhaustion (all suffixes up to `-99` are taken).

---

## 5. Acceptance Criteria

1. **Name slugification**: `PUT /api/v1/bots` with `name: "My Cool Bot"` creates an agent with `name: "my-cool-bot"`.
2. **Idempotent slugs**: `name: "my-cool-bot"` passes through unchanged.
3. **Dedup with suffix**: Creating two agents with `name: "My Bot"` results in `"my-bot"` and `"my-bot-2"`.
4. **Empty slug rejection**: `name: "!@#$%"` returns 400 with a descriptive error.
5. **Original name in description**: When slug differs from input, description starts with `"Display name: {original}."`.
6. **Vector store provisioned**: When `vector_store_config` includes `table` and `schema`, the PgVector table exists after the PUT returns.
7. **Vector store graceful failure**: If PgVector is unreachable, the bot is created with `vector_store_status: "pending"` and the error is logged.
8. **No vector store without table**: When `vector_store_config` lacks `table` or `schema`, no provisioning is attempted.
9. **Registry encapsulation**: Zero occurrences of `_registered_agents` in `parrot/handlers/bots.py` after the change.
10. **Unit tests pass**: All `test_naming.py` tests pass with `pytest`.
11. **Existing agents unaffected**: GET requests for pre-existing agents with non-slug names still work.

---

## 6. External Dependencies

| Dependency | Purpose | Version | Notes |
|---|---|---|---|
| `re` (stdlib) | Slug implementation | N/A | No new dependency needed |
| `asyncpg` (existing) | PgVector table creation | Already installed | Used by `PgVectorStore.create_collection()` |

No new external dependencies required. The stdlib `re` module handles the slug use case (spaces, special chars → hyphens, lowercase). If Unicode edge cases (accents, CJK) become a requirement later, `python-slugify` can be added as a drop-in replacement.

---

## 7. Open Questions

| # | Question | Status | Resolution |
|---|---|---|---|
| 1 | Should `_put_registry` path also get basic name trimming? | Deferred | Out of scope for this feature; can be a follow-up |
| 2 | Should `registry.register()` replace direct `_registered_agents[name] = ...` writes? | Open | Needs review of `register()` signature to confirm compatibility |

---

## 8. Worktree Strategy

- **Isolation**: `per-spec` — All tasks run sequentially in one worktree.
- **Rationale**: Three of the four tasks modify the same file (`bots.py`). Sequential execution avoids merge conflicts.
- **Cross-feature dependencies**: None — `bots.py` is not touched by any in-flight specs.

**Task execution order:**
1. Create `parrot/utils/naming.py` + unit tests (independent)
2. Registry access cleanup in `bots.py` (mechanical replacement)
3. Name normalization integration in `_put_database()` (uses Module 1)
4. Vector store provisioning in `_put_database()` (uses existing store APIs)
