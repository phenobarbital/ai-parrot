# Brainstorm: New API Bot Creation

**Date**: 2026-03-17
**Author**: Claude
**Status**: exploration
**Recommended Option**: Option B

---

## Problem Statement

The `/api/v1/bots` endpoint (`ChatbotHandler`) manages agent CRUD but lacks input normalization and provisioning capabilities:

1. **No name sanitization** — Agent names are stored as-is from the payload. Spaces, mixed casing, and special characters are allowed, which breaks URL routing (names are used in URLs like `/api/v1/bots/{name}`) and causes inconsistencies between DB and registry lookups.

2. **Direct registry internals access** — The handler accesses `registry._registered_agents[name]` (a protected dict) in multiple places instead of using the public `registry.get_metadata(name)` method. This couples the handler to the registry's internal structure.

3. **No vector store provisioning at creation time** — When a user creates an agent with a vector store config, the PgVector table is NOT created until the first document upload or similarity search. This leads to confusing "table not found" errors and the `public.None` table name bug.

**Who is affected:**
- **API consumers** — Must guess how names are stored; URLs with spaces require encoding.
- **Developers** — Direct registry access is fragile and violates encapsulation.
- **End users** — Vector store errors appear only at query time, far from the creation step where the config was set.

## Constraints & Requirements

- **New agents only** — Normalization applies to agents created via the API going forward; existing agents are not retroactively modified.
- **Database path only** — Slug enforcement applies to the database creation path (`_put_database`), not the registry/YAML path.
- **UUID chatbot_id preserved** — The `chatbot_id` field remains a UUID primary key; `name` is the field that gets slugified.
- **Vector store table = user-provided** — The PgVector table and schema come from the user's `vector_store_config`. If not provided, no table is created (no defaulting).
- **Graceful vector store failure** — If table creation fails during bot creation, the bot is still created but the vector store is marked as "pending" with the error logged.
- **De-duplicated names** — If slugification produces a collision (e.g., `"My Bot"` and `"my bot"` both → `"my-bot"`), append a numeric suffix (`"my-bot-2"`) instead of rejecting.

---

## Options Explored

### Option A: Minimal Patch — Inline Fixes in ChatbotHandler

Add name trimming, slug generation, and vector store init directly inside the existing `_put_database` method. Replace `_registered_agents` access with `get_metadata()` calls inline.

**Approach:**
- Add `name = slugify(name.strip())` at the top of `_put_database`.
- Add a dedup loop: query DB/registry, append `-2`, `-3`, etc. until unique.
- After bot creation, if `vector_store_config` has `table` and `schema`, call `store.create_collection()`.
- Find-and-replace all `registry._registered_agents.get(name)` → `registry.get_metadata(name)`.

**Pros:**
- Smallest diff — changes contained to `bots.py`.
- No new modules or abstractions.
- Fast to implement.

**Cons:**
- Slug logic, dedup logic, and vector store provisioning all mixed into the handler.
- No reuse — if another handler needs slugification or dedup, it must duplicate the code.
- Testing requires spinning up the full handler + DB.
- Harder to extend (e.g., adding display_name to description later).

| Library / Tool | Purpose | Notes |
|---|---|---|
| `python-slugify` (6.x) | Unicode-safe slug generation | pip: `python-slugify`; handles accents, CJK, etc. |
| `re` (stdlib) | Fallback slug if no external dep wanted | `re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')` |

**Existing code to reuse:**
- `parrot/handlers/bots.py:349-362` — `_check_duplicate()` (extend for dedup loop)
- `parrot/stores/postgres.py:2800-2868` — `create_collection()` (call directly)
- `parrot/registry/registry.py:294-295` — `get_metadata()` (replace direct dict access)

**Effort:** Low

---

### Option B: Utility Layer + Handler Refactor

Extract name normalization and dedup into a reusable utility module. Add a vector store provisioning helper. Refactor the handler to use these utilities and `get_metadata()`.

**Approach:**
- Create `parrot/utils/naming.py` with `slugify_name(name: str) -> str` and `deduplicate_name(name: str, exists_fn: Callable) -> str`.
- Add `_provision_vector_store()` helper method to `ChatbotHandler` that creates the PgVector table using the user's config and returns a status dict.
- Replace all `registry._registered_agents` access with `registry.get_metadata()`.
- Store original name in `description` field (prepend `"Display: {original_name}. "` if description exists, or set as description if empty).
- Return the final slugified name in the creation response.

**Pros:**
- Reusable naming utilities — other handlers (BotManagement, future endpoints) can use them.
- Clean separation: handler orchestrates, utilities do the work.
- Testable in isolation (unit test `slugify_name`, `deduplicate_name` without DB).
- Vector store provisioning is a discrete, testable step.
- Original name preserved in description for UI display.

**Cons:**
- Slightly larger diff — new utility file + handler changes.
- Need to decide on slug library (python-slugify vs. stdlib regex).

| Library / Tool | Purpose | Notes |
|---|---|---|
| `python-slugify` (6.x) | Unicode-safe slug generation | Already handles edge cases (accents, CJK, emoji). Adds ~50KB dep. |
| `re` (stdlib) | Alternative slug implementation | Zero deps but less robust for Unicode edge cases. |

**Existing code to reuse:**
- `parrot/handlers/bots.py:349-362` — `_check_duplicate()` as the `exists_fn` for dedup.
- `parrot/stores/postgres.py:2800-2868` — `create_collection()` for eager provisioning.
- `parrot/stores/postgres.py:269-316` — `connection()` to establish pool before creating table.
- `parrot/registry/registry.py:294-295` — `get_metadata()` to replace all direct dict access.
- `parrot/interfaces/vector.py:25-40` — `_apply_store_config()` pattern for store initialization.
- `parrot/handlers/models.py:27-285` — `BotModel` to add original name to description.

**Effort:** Medium

---

### Option C: BotModel Validation Layer with Pydantic

Add Pydantic validators directly to `BotModel` (or a creation-specific schema) that enforce slugification at the model level. Vector store provisioning via a post-creation hook.

**Approach:**
- Create `BotCreatePayload(BaseModel)` with Pydantic `field_validator` on `name` that auto-slugifies.
- Add a `vector_store_status` field to `BotModel` (enum: `none`, `pending`, `ready`, `error`).
- Add a `display_name` field to `BotModel` (stores original pre-slug name).
- Register a post-insert hook that provisions the vector store table.
- Replace `_registered_agents` access with `get_metadata()`.

**Pros:**
- Validation happens at the model layer — impossible to bypass even from other code paths.
- `vector_store_status` field gives clear observability.
- `display_name` is a proper field, not overloaded into description.
- Pydantic validators are declarative and self-documenting.

**Cons:**
- Requires DB schema migration (new `display_name` and `vector_store_status` columns).
- `BotModel` uses DataModel (not pure Pydantic) — need to verify validator compatibility.
- Higher effort and migration risk for what is fundamentally a handler-level concern.
- Over-engineers the solution for the current scope.

| Library / Tool | Purpose | Notes |
|---|---|---|
| `python-slugify` (6.x) | Unicode-safe slug generation | Same as Options A/B. |
| `DataModel` validators | Model-level slug enforcement | Need to verify `field_validator` support in DataModel. |
| Alembic / manual DDL | Schema migration for new columns | Adding `display_name`, `vector_store_status` to `ai_bots`. |

**Existing code to reuse:**
- Same as Option B, plus:
- `parrot/handlers/models.py` — `BotModel` (extend with new fields)

**Effort:** High

---

## Recommendation

**Option B — Utility Layer + Handler Refactor** is the best balance of correctness, reusability, and effort.

**Rationale:**
- Option A is fast but buries logic in the handler, making it untestable and non-reusable.
- Option C is the "right" model-layer approach but requires a DB migration and over-engineers the scope — we don't need a `display_name` column since description works.
- Option B gives us reusable `slugify_name()` / `deduplicate_name()` utilities (useful for future endpoints), a clean provisioning helper, and keeps changes scoped to the handler + one new utility file.

**Tradeoff accepted:** We store the original name in the `description` field rather than adding a dedicated `display_name` column. This avoids a DB migration while preserving the information for UI display.

**Slug library decision:** Use `python-slugify` if it's acceptable to add a small dependency (robust Unicode handling). Otherwise, a stdlib `re`-based implementation covers the primary use case (spaces → hyphens, lowercase, strip special chars).

---

## Feature Description

### User-Facing Behavior

**Creating a bot via `PUT /api/v1/bots`:**

1. User sends payload with `name: "My Cool Bot"`.
2. API slugifies: `"my-cool-bot"`.
3. API checks for duplicates. If `"my-cool-bot"` exists, tries `"my-cool-bot-2"`, `"my-cool-bot-3"`, etc.
4. If payload includes `vector_store_config` with `table` and `schema`, API eagerly creates the PgVector table.
5. Response includes:
   ```json
   {
     "chatbot_id": "uuid-...",
     "name": "my-cool-bot",
     "source": "database",
     "vector_store_status": "ready"
   }
   ```
   Or if vector store creation failed:
   ```json
   {
     "name": "my-cool-bot",
     "vector_store_status": "pending",
     "vector_store_error": "Connection refused"
   }
   ```

**Reading bots via `GET /api/v1/bots/{name}`:**
- Names in URLs are already slugified, so routing works cleanly.

### Internal Behavior

1. **Name normalization** (`parrot/utils/naming.py`):
   - `slugify_name(name)` → strip, lowercase, replace non-alnum with hyphens, collapse consecutive hyphens, strip leading/trailing hyphens.
   - `deduplicate_name(slug, exists_fn)` → call `exists_fn(slug)`, if truthy append `-2`, `-3`, etc. until unique.

2. **Registry access cleanup** (`parrot/handlers/bots.py`):
   - All `registry._registered_agents.get(name)` → `registry.get_metadata(name)`.
   - All `registry._registered_agents[name] = ...` → use existing `registry.register()` or a new public setter if needed.

3. **Vector store provisioning** (`parrot/handlers/bots.py`):
   - New `_provision_vector_store(bot_instance, vector_store_config)` method.
   - Extracts `table` and `schema` from config. If either is missing, skips provisioning.
   - Calls `bot.define_store(...)` → `bot.configure_store()` → `bot.store.connection()` → `bot.store.create_collection(table, schema, dimension)`.
   - Catches exceptions, logs error, returns `{"status": "pending", "error": str(e)}`.

4. **Original name preservation**:
   - If the original name differs from the slug, prepend to description: `"Display name: My Cool Bot. {existing_description}"`.

### Edge Cases & Error Handling

- **Empty name after slugification** (e.g., name was all special characters) → return 400 with clear message.
- **Dedup exhaustion** — Unlikely but cap at suffix `-99`; return 409 if all taken.
- **Vector store config without table/schema** — No provisioning attempted; bot created normally without vector store.
- **PgVector connection failure during provisioning** — Bot is created, vector store status = `"pending"`, error logged. User can retry provisioning later via BotManagement.
- **Concurrent creation race** — DB UNIQUE constraint on `name` is the final guard; if dedup passed but a concurrent insert beats us, catch `IntegrityError` and retry with next suffix.

---

## Capabilities

### New Capabilities

- `bot-name-slugification` — Automatic slug generation from user-provided names.
- `bot-name-deduplication` — Numeric-suffix dedup when slug collides.
- `vector-store-eager-provisioning` — PgVector table creation at bot creation time.

### Modified Capabilities

- `bot-crud-api` — `ChatbotHandler` PUT method updated with normalization and provisioning.
- `registry-access-pattern` — Replace all `_registered_agents` direct access with `get_metadata()`.

---

## Impact & Integration

| Component | Impact | Description |
|---|---|---|
| `parrot/handlers/bots.py` | **Modified** | Handler refactored: name normalization, dedup, vector store provisioning, registry access cleanup. |
| `parrot/utils/naming.py` | **New** | Slug generation and dedup utilities. |
| `parrot/stores/postgres.py` | **Used** | `create_collection()` called during provisioning. No changes needed. |
| `parrot/registry/registry.py` | **Used** | `get_metadata()` used instead of direct dict access. No changes needed. |
| `parrot/handlers/models.py` | **Minor** | Description field usage for original name. No schema change. |
| `pyproject.toml` | **Optional** | Add `python-slugify` dependency if chosen over stdlib regex. |

---

## Open Questions

| # | Question | Owner | Impact |
|---|---|---|---|
| 1 | Use `python-slugify` or stdlib `re`-based slug? | User | Dependency footprint vs. Unicode robustness |
| 2 | Should the `_put_registry` path also get name trimming (even if not full slugification)? | User | Consistency between DB and YAML agent names |
| 3 | Should `registry.register()` be used to replace the direct `_registered_agents[name] = BotMetadata(...)` write, or just the reads? | User | Encapsulation of writes vs. reads |

---

## Parallelism Assessment

- **Internal parallelism**: Yes — three independent workstreams:
  1. `parrot/utils/naming.py` (new file, no dependencies)
  2. Registry access cleanup in `bots.py` (find-and-replace, no logic change)
  3. Vector store provisioning helper (depends on existing `create_collection`)

- **Cross-feature independence**: No conflicts with in-flight specs. `bots.py` is not being modified by other features.

- **Recommended isolation**: `per-spec` — All tasks are small and touch the same handler file, so a single worktree is simpler than coordination overhead.

- **Rationale**: Tasks 1 and 2 could technically run in parallel, but task 3 (provisioning) needs to integrate with the same PUT method that tasks 1 and 2 modify. Sequential execution in one worktree avoids merge conflicts.
