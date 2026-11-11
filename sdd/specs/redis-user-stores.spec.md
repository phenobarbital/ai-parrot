---
type: feature
base_branch: dev
projects: [ai-parrot, ai-parrot-server, ai-parrot-integrations]
tags: [redis, storage, vault, credentials, local-dev]
docs:
  policy: required
  pages:
    - wiki/stores/user-stores.md
    - wiki/bots/agentstudio/db-storage.md
    - wiki/stores/documentdb_interface.md
    - wiki/bots/orchestration/crew-definition-storage.md
  api_modules:
    - parrot.userstore
    - parrot.security.vault_utils
---

# Feature Specification: Redis user stores (MongoDB-free local installs)

**Feature ID**: FEAT-878
**Date**: 2026-11-11
**Author**: Jesus Lara
**Status**: approved
**Target version**: next minor (breaking default — see §7)

---

## 1. Motivation & Business Requirements

### Problem Statement

Every per-user store in ai-parrot is hard-wired to MongoDB/AWS DocumentDB through
`parrot.interfaces.documentdb.DocumentDb` (asyncdb `mongo` driver, `localhost:27017` by default):

| Collection | Owner | What it holds |
|---|---|---|
| `user_credentials` | `parrot.security.vault_utils`, `CredentialsHandler`, `AgentTalk` MCP restore | Vault: AES-GCM sealed credentials |
| `user_llm_keys` | Studio BYOK (`StudioKeysHandler`, `_UserLLMKeyResolver`) | sealed per-user LLM API keys |
| `user_toolkit_configs` | `ToolkitConfigService` | per-user toolkit overrides |
| `user_mcp_configs` | `MCPPersistenceService` | per-user activated MCP servers |
| `telegram_user_mcp_configs` | `TelegramMCPPersistenceService` | Telegram `/add_mcp` servers |
| `users_integrations` | `parrot.auth.oauth2.persistence` | OAuth2 connection records |
| `dashboards`, `dashboard_tabs` | `DashboardHandler`, `DashboardTabHandler` | saved dashboards |

A developer (or a small installation) without a MongoDB server pays for it on every request:
`AgentTalk` hydrates OAuth toolkits (`list_users_integrations`) and applies toolkit overrides
(`ToolkitConfigService.load`) per call, each one waiting the full 10 s `DOCUMENTDB_TIMEOUT` before
failing — about 20 s of added latency per agent call, plus error logs, and the features silently
degrade. Observed on 2026-11-10 with agent `pokemon_finance`.

FEAT-621 added a Postgres alternative for three of these collections (`VAULT_STORE`,
`TOOLKIT_OVERRIDES_STORE`, `BYOK_STORE`), but it is off by default, requires the Studio Postgres
schema, and is **incomplete for the vault**: only the `vault_utils` helpers honour `VAULT_STORE`.
`CredentialsHandler` (`/api/v1/users/credentials`) and the per-user MCP restore in
`AgentTalk._restore_user_mcp_servers` still read and write `user_credentials` in DocumentDB directly,
so `VAULT_STORE=postgres` splits credentials across two stores. In addition, `CredentialsHandler.put`
persists with `DocumentDb.save_background`, which is an INSERT: every update leaves a duplicate
document, and `read_one` may keep returning the stale one.

### Goals
- G1: Run ai-parrot (core, server, Telegram integration) with **no MongoDB server**: every
  collection in the table above can live in Redis, and crew/flow results default to Redis too
  when `CREW_RESULT_STORAGE` is unset.
- G2: **Redis is the default** for all user stores. DocumentDB (and Postgres where FEAT-621 provides
  it) stays available by explicit configuration.
- G3: One switch for the whole installation (`PARROT_USER_STORE`), overridable per store.
- G4: Every access to `user_credentials` goes through `parrot.security.vault_utils`, so the store
  switch is honoured everywhere (fixes the FEAT-621 bypass for Postgres too) and the
  duplicate-on-update bug disappears.
- G5: Sealed values keep their format and AAD context in every backend, so data copies verbatim:
  a one-shot DocumentDB → Redis copy CLI ships with the feature.
- G6: navigator-vault keyring rotation covers credentials and BYOK keys stored in Redis.
- G7: Misconfiguration fails closed at startup — including an implicit Redis default on an
  installation that has DocumentDB configured (the upgrade case); risky Redis setups (evicting
  policy, no persistence) are reported in the startup log.

### Non-Goals (explicitly out of scope)
- Changing the crew/flow result backends themselves (FEAT-147) or the 7-day TTL of
  `RedisResultStorage`; only the default selection changes (M14).
- Conversation memory, artifacts, chat storage (FEAT-116) — already pluggable.
- A Redis → DocumentDB or Redis → Postgres copy path; and Postgres backends for the four collections
  FEAT-621 did not cover.
- Cross-tenant partitioning of user stores (none exists in DocumentDB either).
- Adding `fakeredis` as a dependency (tests use the real local Redis, db 15).
- Changing `DocumentDb` itself, the Studio Postgres schema, or `navigator-session` vault crypto.

---

## Governing Decisions

<!-- decision-audit: input_digest=sha256:42f6d1a0bdd44f3fb52b7b602f1e4421134c886c5020ec83c91af28787d09671 evaluation_digest=sha256:2f2d4f51f2fc6e2ec9411244a2a4db4b2c75a5aa6b1e51ee529888092da41d88 rules_version=1 status=pass -->

## 2. Architectural Design

### Overview

**Backend selection (core, `parrot.userstore`).** Each user store has a switch. Resolution order,
read at call time through `navconfig.config` (so tests can `monkeypatch.setenv`):

1. the per-store switch (`VAULT_STORE`, `BYOK_STORE`, `TOOLKIT_OVERRIDES_STORE`, `MCP_CONFIGS_STORE`,
   `TELEGRAM_MCP_STORE`, `INTEGRATIONS_STORE`, `DASHBOARDS_STORE`);
2. the global switch `PARROT_USER_STORE`;
3. the default, `redis`.

Allowed values: the global switch accepts `redis | documentdb`. `VAULT_STORE`, `BYOK_STORE` and
`TOOLKIT_OVERRIDES_STORE` accept `redis | documentdb | postgres`; the four new switches accept
`redis | documentdb`. Any other value raises `UserStoreMisconfigured` — at server startup
(validation step) and at call time — never a silent fallback. Values are case-insensitive and
stripped. `postgres` keeps FEAT-621 semantics: the store is registered by the Studio backend at
startup, and the Studio backend must resolve to `database` or startup fails.

**Redis primitive.** `RedisDocumentStore` is a small keyed-document store over `redis.asyncio`
(already installed through `navigator-session`, redis 5.2.1). One instance per `CollectionSpec`
(collection name, key fields, index fields). Layout under a configurable prefix
(`PARROT_USER_STORE_REDIS_PREFIX`, default `parrot:us`):

- document: `{prefix}:{collection}:d:{k1}:{k2}…` → JSON string (one per document, no TTL);
- index:    `{prefix}:{collection}:i:{field}:{value}` → SET of document ids;
- all:      `{prefix}:{collection}:all` → SET of document ids.

Key and index values are `urllib.parse.quote(str(v), safe="")`-encoded and compared as strings, so
`user_id=35` and `user_id="35"` address the same document. Writes that touch indexes run in one
`WATCH`/`MULTI`/`EXEC` transaction with a bounded retry, so indexes never point at a stale field
value. `find(where)` intersects the index sets of the indexed fields present in `where` (falling back
to `all`), loads the documents with `MGET`, then applies every equality condition in Python.
Only equality filters exist; sorting is done by callers. The client is
`redis.asyncio.from_url(PARROT_USER_STORE_REDIS_URL, decode_responses=True)`, one per running event
loop, closed by `close_user_store_redis()` on server cleanup. Default URL:
`redis://{REDIS_HOST}:{REDIS_PORT}/{PARROT_USER_STORE_REDIS_DB}` with `PARROT_USER_STORE_REDIS_DB`
defaulting to `6` — a dedicated logical DB, so a `FLUSHDB` of the cache/job DBs never wipes secrets.
Redis Cluster (DB 0 only) and similar managed services set `PARROT_USER_STORE_REDIS_URL` explicitly.

**Document shape rule.** A Redis document mirrors the DocumentDB document of the same collection
field for field (without `_id`), with datetimes as ISO-8601 strings. Sealed fields (`credential`,
`api_key`) hold exactly what `encrypt_credential` returns. This is what makes the copy CLI verbatim,
lets the rotation target reuse `DocumentDbTarget` logic, and keeps AAD contexts
(`credential_context(user_id, name)`, `llm_key_context(user_id, provider)`) valid across backends.

**Per-domain Redis stores**, each next to the service it serves (dependency direction: core never
imports server or integrations code):

| Store | Package | API (same as the Postgres twin where one exists) |
|---|---|---|
| `RedisVaultCredentialStore` | core `parrot.security` | `store` / `retrieve` / `delete` / `list_credentials` / `exists` |
| `RedisUserLLMKeyStore` | core `parrot.auth.broker` | `get` / `put` / `delete` / `list_masked` |
| `RedisUsersIntegrationStore` | core `parrot.auth.oauth2` | `upsert` / `get` / `delete` / `list` |
| `RedisToolkitOverrideStore` | server `parrot.handlers` | `save` / `load` / `remove` / `purge_agent` / `revision` |
| `RedisMCPConfigStore` | server `parrot.handlers` | `save` / `load` / `remove` (soft delete) |
| `RedisTelegramMCPStore` | integrations `parrot.integrations.telegram` | `save` / `list` / `read_one` / `remove` (soft delete) |
| `RedisDashboardStore` | server `parrot.handlers` | the `DashboardStore` protocol (§3 M11) |

Each service keeps its public API and dispatches at call time: a registered Postgres store
(FEAT-621) wins; otherwise the resolved switch picks Redis (lazily built module-level store) or the
existing inline DocumentDB code, which is left untouched. A switch resolved to `postgres` with no
registered store raises `RuntimeError` (fail closed) — today `vault_utils` silently falls back to
DocumentDB in that case.

**Vault access is centralised.** `vault_utils` gains `list_vault_credentials(user_id)` and
`vault_credential_exists(user_id, name)`; `PgVaultCredentialStore` gains the same two operations.
`CredentialsHandler` and `AgentTalk._restore_user_mcp_servers` stop importing `DocumentDb` and call
`vault_utils` only. HTTP contracts are unchanged (status codes, bodies); the only behavioural change
is that POST/PUT now await the durable write instead of scheduling a background insert, which also
removes the duplicate-document bug.

**Telegram gate.** `TelegramMCPPersistenceService` persists when its switch resolves to `redis`, or
when it resolves to `documentdb` **and** `USE_DOCUMENTDB` is true (today's opt-in, unchanged).
`persistence_enabled()` replaces `documentdb_enabled()` in `mcp_commands.py`; the old name stays as
an alias.

**Dashboards.** The inline DocumentDB code in `DashboardHandler` / `DashboardTabHandler` moves
verbatim into `DocumentDbDashboardStore`; handlers call a `DashboardStore` chosen by
`DASHBOARDS_STORE`. `_ensure_dashboard_indexes` delegates to `store.ensure_indexes()` (a no-op for
Redis), so startup no longer contacts MongoDB when dashboards live in Redis. Creating a dashboard or
tab whose id already exists answers `409` in both backends.

**Startup (server).** `BotManager.setup()` validates every switch and raises
`UserStoreMisconfigured` on an invalid value **or on an implicit Redis default on a DocumentDB
installation**: when `DOCUMENTDB_HOSTNAME` or `DOCUMENTDB_DBNAME` is set (the rule
`vault_targets._default_docdb_factory` already uses) and some store — or an unset
`CREW_RESULT_STORAGE` — resolves to Redis only because nothing was configured, startup stops with
one error that lists those stores and both fixes: `PARROT_USER_STORE=documentdb` (keep MongoDB) or
`PARROT_USER_STORE=redis` (move; run the copy CLI first). Setting the global switch to either value
clears the guard; setting every per-store switch clears it only when `CREW_RESULT_STORAGE` is also set
(an unset `CREW_RESULT_STORAGE` still counts as an implicit Redis default); an installation with neither DocumentDB
variable is never affected. `setup()` then adds an `on_startup` diagnostic and an `on_cleanup` that
closes the Redis client. The diagnostic runs only when some store resolves to `redis` and never
fails startup: `PING` (warn when unreachable), `CONFIG GET maxmemory-policy` (warn on any
`allkeys-*` policy — it can evict secrets), `CONFIG GET appendonly` / `save` (warn when both
persistence modes are off); `CONFIG` errors (managed Redis) are logged at debug and skipped.
The Studio backend computes its `postgres` switches through the same resolver.

**Crew/flow results.** `CREW_RESULT_STORAGE` loses its hard-coded `documentdb` fallback: when it is
unset, `get_result_storage()` uses `default_result_storage()` — the value of `PARROT_USER_STORE`,
else `redis`. An explicit `CREW_RESULT_STORAGE` (including `postgres`) is unchanged. Results keep
their own Redis URL (`CREW_RESULT_STORAGE_REDIS_URL`, default `REDIS_URL`) and 7-day TTL; they are
not secrets and do not move to db 6.

**Copy CLI.** `python -m parrot.userstore.copy` copies DocumentDB documents into Redis for the
selected collections: insert-only by default (an existing Redis document is `skipped`),
`--overwrite` replaces only when the source `updated_at` is strictly newer, `--dry-run` writes
nothing. Duplicate DocumentDB documents for one key (left by the PUT bug) collapse to the newest by
`updated_at`; the rest count as `duplicates`. Ciphertexts are copied verbatim, so no keyring is
needed. Output: counts per collection; exit code 1 when any document failed. Logs carry identities
and exception classes only — never values, ciphertexts or URLs with credentials.

**Rotation.** `parrot.vault_targets` gains `RedisDocumentTarget` (a `DocumentDbTarget` whose I/O
goes through `RedisDocumentStore`) with `redis:user_credentials` and `redis:user_llm_keys` targets,
registered as `navigator_session.vault_targets` entry points. A factory returns a target only when
its switch (`VAULT_STORE` / `BYOK_STORE`) resolves to `redis`, else `None` (as the DocumentDB
factories do when DocumentDB is not configured). Quarantine moves a document to
`{collection}_quarantine` in the same Redis keyspace.

### Component Diagram
```
             navconfig  ──→  parrot.userstore.settings.resolve_store_backend(switch)
                                      │ redis | documentdb | postgres
          ┌───────────────────────────┼──────────────────────────────┐
          ▼                           ▼                              ▼
  Redis* domain stores        inline DocumentDB code          FEAT-621 Pg stores
  (vault, byok, oauth2,       (unchanged, legacy)             (registered at startup
   overrides, mcp, telegram,                                   by Studio backend)
   dashboards)
          │
          ▼
  RedisDocumentStore(CollectionSpec) ──→ redis.asyncio client (per loop, PARROT_USER_STORE_REDIS_URL)

  vault_utils ◀── CredentialsHandler, AgentTalk MCP restore, ToolkitConfig secrets, OAuth2 vault names
  userstore.copy:  DocumentDb ──read──▶ RedisDocumentStore (verbatim)
  vault_targets:   RedisDocumentTarget ◀── navigator-vault rotation (entry points)
  BotManager.setup: validate (+ implicit-default guard) → on_startup diagnostics → on_cleanup close client
  get_result_storage(): CREW_RESULT_STORAGE → default_result_storage() (PARROT_USER_STORE → redis)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot.security.vault_utils` | modifies | store dispatch, `list_vault_credentials`, `vault_credential_exists`, fail-closed postgres |
| `CredentialsHandler` | modifies | all four verbs through `vault_utils`; no `DocumentDb` import |
| `AgentTalk._restore_user_mcp_servers` | modifies | secret lookup through `retrieve_vault_credential` |
| `PgVaultCredentialStore` | extends | `list_credentials`, `exists` |
| `ToolkitConfigService` | modifies | Redis dispatch beside the registered Postgres store |
| `MCPPersistenceService` | modifies | `MCP_CONFIGS_STORE` dispatch |
| `TelegramMCPPersistenceService` | modifies | `TELEGRAM_MCP_STORE` dispatch, `persistence_enabled()` gate |
| `parrot.auth.oauth2.persistence` | modifies | `INTEGRATIONS_STORE` dispatch |
| `byok_store_setting`, `_UserLLMKeyResolver`, `StudioKeysHandler`, `user_byok_providers` | modifies | `redis` value, one store accessor instead of `== "postgres"` branches |
| `DashboardHandler`, `DashboardTabHandler`, `_ensure_dashboard_indexes` | modifies | go through `DashboardStore` |
| Studio `backend._postgres_switches` | modifies | uses the resolver |
| `BotManager.setup` | modifies | validation, diagnostics hook, cleanup hook |
| `parrot.vault_targets` + `pyproject.toml` entry points | extends | Redis rotation targets |
| `get_result_storage` (FEAT-147) | modifies | an unset `CREW_RESULT_STORAGE` follows `PARROT_USER_STORE` |

### Data Models
```python
StoreBackend = Literal["redis", "documentdb", "postgres"]

@dataclass(frozen=True)
class StoreSwitch:
    name: str                    # env key, e.g. "VAULT_STORE"
    collections: tuple[str, ...]
    allowed: frozenset[str]      # subset of {"redis", "documentdb", "postgres"}

@dataclass(frozen=True)
class CollectionSpec:
    name: str
    key_fields: tuple[str, ...]
    index_fields: tuple[str, ...] = ()
```

Collection registry (`parrot.userstore.collections`):

| Spec | key_fields | index_fields | Switch |
|---|---|---|---|
| `user_credentials` | `user_id, name` | `user_id` | `VAULT_STORE` |
| `user_llm_keys` | `user_id, provider` | `user_id` | `BYOK_STORE` |
| `user_toolkit_configs` | `user_id, agent_id, slug` | `user_id, agent_id` | `TOOLKIT_OVERRIDES_STORE` |
| `user_mcp_configs` | `user_id, agent_id, server_name` | `user_id, agent_id` | `MCP_CONFIGS_STORE` |
| `telegram_user_mcp_configs` | `user_id, name` | `user_id` | `TELEGRAM_MCP_STORE` |
| `users_integrations` | `user_id, provider` | `user_id` | `INTEGRATIONS_STORE` |
| `dashboards` | `dashboard_id` | `module_id, user_id` | `DASHBOARDS_STORE` |
| `dashboard_tabs` | `dashboard_id, tab_id` | `dashboard_id` | `DASHBOARDS_STORE` |

### New Public Interfaces
```python
# parrot.userstore
def resolve_store_backend(switch: str) -> StoreBackend: ...
def store_backend_source(switch: str) -> Literal["switch", "global", "default"]: ...
def validate_user_store_settings() -> dict[str, StoreBackend]: ...
def implicit_redis_stores() -> list[str]: ...
def default_result_storage() -> Literal["redis", "documentdb"]: ...
class UserStoreMisconfigured(RuntimeError): ...
def get_user_store_redis() -> "redis.asyncio.Redis": ...
async def close_user_store_redis() -> None: ...
class RedisDocumentStore: ...

# parrot.security.vault_utils (additions)
async def list_vault_credentials(user_id: str) -> dict[str, dict[str, Any]]: ...
async def vault_credential_exists(user_id: str, vault_name: str) -> bool: ...
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: userstore settings | yes | resolution order, allowed sets, error type, env keys fixed in §2 | — |
| M2: RedisDocumentStore + registry | no | layout fixed, but WATCH/MULTI index maintenance needs care | concurrency of index updates |
| M3: vault Redis store + vault_utils | yes | dispatch order and new functions fixed | — |
| M4: CredentialsHandler + MCP restore | yes | status codes and bodies unchanged; calls fixed | — |
| M5: OAuth2 integrations Redis | yes | mirrors persistence.py API | — |
| M6: BYOK Redis | yes | mirrors `PgUserLLMKeyStore` API | — |
| M7: toolkit overrides Redis | yes | mirrors `PgToolkitOverrideStore` API | — |
| M8: MCP configs Redis | yes | soft delete + created_at-on-insert preserved | — |
| M9: Telegram MCP Redis | yes | gate rule fixed in §2 | — |
| M10: dashboards store | no | — | moving 13 inline blocks behind a protocol needs judgement on handler flow |
| M11: server startup wiring | yes | checks and messages fixed in §2 | — |
| M12: copy CLI | yes | flags, counts, exit code fixed in §2 | — |
| M13: Redis rotation targets | yes | subclass of `DocumentDbTarget`, factories fixed | — |
| M14: crew result default | yes | conf fallback `None` + factory call fixed | — |

### Module 1: User store settings and resolver
- **Path**: `packages/ai-parrot/src/parrot/userstore/__init__.py`, `packages/ai-parrot/src/parrot/userstore/settings.py`
- **Responsibility**: switch registry, resolution order, validation, Redis URL/prefix settings, per-loop Redis client.
- **Depends on**: `navconfig.config`, `redis.asyncio`.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/userstore/settings.py  (new)
  GLOBAL_SWITCH: str = "PARROT_USER_STORE"
  DEFAULT_BACKEND: StoreBackend = "redis"
  SWITCHES: dict[str, StoreSwitch]  # the 7 per-store switches of §2 Data Models

  class UserStoreMisconfigured(RuntimeError):
      """A store switch (or PARROT_USER_STORE) holds a value outside its allowed set."""

  def resolve_store_backend(switch: str) -> StoreBackend:
      """Per-store value → PARROT_USER_STORE → "redis". Raises UserStoreMisconfigured on an invalid
      value and KeyError on an unknown switch name."""

  def store_backend_source(switch: str) -> Literal["switch", "global", "default"]:
      """Which level decided ``resolve_store_backend(switch)`` (used by the startup warning)."""

  def validate_user_store_settings() -> dict[str, StoreBackend]:
      """Resolve every switch; raise UserStoreMisconfigured on the first invalid value, or when
      documentdb_configured() and implicit_redis_stores() is non-empty (the message lists those
      stores and the two PARROT_USER_STORE fixes). Returns {switch: backend}."""

  def documentdb_configured() -> bool:
      """DOCUMENTDB_HOSTNAME or DOCUMENTDB_DBNAME is set (same rule as vault_targets._default_docdb_factory)."""

  def implicit_redis_stores() -> list[str]:
      """Switch names resolving to redis with store_backend_source() == "default", plus
      "CREW_RESULT_STORAGE" when it is unset and PARROT_USER_STORE is unset."""

  def default_result_storage() -> Literal["redis", "documentdb"]:
      """Crew/flow result backend when CREW_RESULT_STORAGE is unset: PARROT_USER_STORE, else "redis"."""

  def redis_url() -> str:
      """PARROT_USER_STORE_REDIS_URL, else redis://{REDIS_HOST}:{REDIS_PORT}/{PARROT_USER_STORE_REDIS_DB} (db 6)."""

  def key_prefix() -> str:
      """PARROT_USER_STORE_REDIS_PREFIX, default "parrot:us" (no trailing colon)."""

  def get_user_store_redis() -> "redis.asyncio.Redis":
      """One lazily created client per running event loop (decode_responses=True)."""

  async def close_user_store_redis() -> None:
      """Close and forget the current loop's client; no-op when none was created."""
  ```

### Module 2: Redis document store and collection registry
- **Path**: `packages/ai-parrot/src/parrot/userstore/redis_documents.py`, `packages/ai-parrot/src/parrot/userstore/collections.py`, `packages/ai-parrot/src/parrot/userstore/testing.py`
- **Responsibility**: keyed JSON documents with secondary indexes (layout in §2); the 8 `CollectionSpec`s and `COLLECTION_SWITCH`; a test helper that points the store at db 15 with a unique prefix and deletes only that prefix.
- **Depends on**: M1.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/userstore/redis_documents.py  (new)
  class RedisDocumentStore:
      """Keyed JSON documents for one CollectionSpec. Equality filters only; no TTL."""
      def __init__(self, spec: CollectionSpec, *, client: "redis.asyncio.Redis | None" = None,
                   prefix: str | None = None) -> None: ...
      async def get(self, key: Mapping[str, Any]) -> dict[str, Any] | None:
          """Document for the full key, or None. ValueError when a key field is missing/None."""
      async def put(self, document: Mapping[str, Any]) -> None:
          """Replace the whole document (key taken from the document); indexes updated atomically."""
      async def upsert(self, key: Mapping[str, Any], set_fields: Mapping[str, Any], *,
                       on_insert: Mapping[str, Any] | None = None) -> dict[str, Any]:
          """$set/$setOnInsert semantics: merge set_fields; on_insert applies only on creation.
          Returns the stored document."""
      async def update(self, key: Mapping[str, Any], set_fields: Mapping[str, Any]) -> bool:
          """Merge into an existing document; False (and no write) when absent."""
      async def delete(self, key: Mapping[str, Any]) -> bool:
          """True when a document was removed."""
      async def exists(self, key: Mapping[str, Any]) -> bool: ...
      async def find(self, where: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
          """Documents matching every equality in ``where`` (all documents when None/empty)."""
      async def delete_where(self, where: Mapping[str, Any]) -> list[dict[str, Any]]:
          """Delete and return every matching document."""
      async def scan(self) -> AsyncIterator[dict[str, Any]]:
          """Every document, ordered by its encoded key."""

  # packages/ai-parrot/src/parrot/userstore/collections.py  (new)
  USER_CREDENTIALS: CollectionSpec  # … one constant per row of the §2 registry table
  USER_STORE_COLLECTIONS: dict[str, CollectionSpec]
  COLLECTION_SWITCH: dict[str, str]  # collection name → switch name

  # packages/ai-parrot/src/parrot/userstore/testing.py  (new)
  @asynccontextmanager
  async def redis_test_settings(monkeypatch: Any) -> AsyncIterator[str]:
      """Set PARROT_USER_STORE_REDIS_URL=redis://localhost:6379/15 and a unique prefix; yield the
      prefix; delete only keys under it (SCAN + DEL, never FLUSHDB); pytest.skip when unreachable."""
  ```

### Module 3: Vault credentials — Redis store and `vault_utils` dispatch
- **Path**: `packages/ai-parrot/src/parrot/security/vault_store_redis.py` (new); modifies `packages/ai-parrot/src/parrot/security/vault_utils.py`, `packages/ai-parrot/src/parrot/security/__init__.py`
- **Responsibility**: Redis vault store; `vault_utils` picks registered store → switch (`redis` → Redis store, `documentdb` → existing inline code, `postgres` without registration → `RuntimeError`); two new helpers.
- **Depends on**: M1, M2.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/security/vault_store_redis.py  (new)
  class RedisVaultCredentialStore:
      """``user_credentials`` in Redis; document shape {user_id, name, credential, created_at, updated_at}."""
      def __init__(self, documents: RedisDocumentStore | None = None) -> None: ...
      async def store(self, user_id: Any, vault_name: str, secret_params: dict[str, Any]) -> None:
          """Seal with credential_context(user_id, vault_name); created_at kept on rewrite."""
      async def retrieve(self, user_id: Any, vault_name: str) -> dict[str, Any]:
          """Open the credential. KeyError when absent (same message as the DocumentDB path)."""
      async def delete(self, user_id: Any, vault_name: str) -> None: ...
      async def list_credentials(self, user_id: Any) -> dict[str, dict[str, Any]]:
          """{name: decrypted dict}; undecryptable entries are skipped with a warning (no value logged)."""
      async def exists(self, user_id: Any, vault_name: str) -> bool: ...

  # modifies packages/ai-parrot/src/parrot/security/vault_utils.py
  _PG_VAULT_STORE: Any = None  # verified: vault_utils.py:43 — kept, still set by set_vault_credential_store (:46)
  class VaultCredentialStore(Protocol):
      """store / retrieve / delete / list_credentials / exists — implemented by Redis and Postgres stores."""
  def get_vault_credential_store() -> "VaultCredentialStore | None":
      """Registered store → it; VAULT_STORE=redis → module-level RedisVaultCredentialStore;
      documentdb → None (inline path); postgres with nothing registered → RuntimeError."""
  async def store_vault_credential(...) -> None:     # verified: vault_utils.py:92 — dispatch via get_vault_credential_store()
  async def retrieve_vault_credential(...) -> dict:  # verified: vault_utils.py:145
  async def delete_vault_credential(...) -> None:    # verified: vault_utils.py:184
  async def list_vault_credentials(user_id: str) -> dict[str, dict[str, Any]]:
      """All of a user's credentials, decrypted; undecryptable ones skipped."""
  async def vault_credential_exists(user_id: str, vault_name: str) -> bool: ...
  ```

### Module 4: `CredentialsHandler` and MCP restore through `vault_utils`
- **Path**: modifies `packages/ai-parrot-server/src/parrot/handlers/credentials.py`, `packages/ai-parrot-server/src/parrot/handlers/agent.py`, `packages/ai-parrot-server/src/parrot/handlers/studio/storage/vault_store.py`
- **Responsibility**: remove every direct `user_credentials` DocumentDB access; Postgres store gains the two operations the handler needs.
- **Depends on**: M3.
- **Interface Skeleton**:
  ```python
  # modifies credentials.py — class CredentialsHandler (COLLECTION at :71 stays for compatibility)
  async def get(self) -> web.Response:     # verified: credentials.py:152 — retrieve / list_vault_credentials
  async def post(self) -> web.Response:    # verified: credentials.py:229 — exists → 409, else await store
  async def put(self) -> web.Response:     # verified: credentials.py:330 — not exists → 404, else await store
  async def delete(self) -> web.Response:  # verified: credentials.py:436 — not exists → 404, else delete
  # Session-vault calls (_set_session_credential :110, _remove_session_credential :121) unchanged.

  # modifies agent.py — AgentTalk._restore_user_mcp_servers (verified: agent.py:1127)
  #   the `async with DocumentDb() as db:` block at :1217 becomes
  #   `secret_params = await retrieve_vault_credential(user_id, config.vault_credential_name)`
  #   (KeyError → the existing "Vault credential … missing" warning + continue).

  # modifies studio/storage/vault_store.py — class PgVaultCredentialStore (verified: vault_store.py:23)
  async def list_credentials(self, user_id: Any) -> dict[str, dict[str, Any]]: ...
  async def exists(self, user_id: Any, vault_name: str) -> bool: ...
  ```

### Module 5: OAuth2 `users_integrations` in Redis
- **Path**: `packages/ai-parrot/src/parrot/auth/oauth2/persistence_redis.py` (new); modifies `packages/ai-parrot/src/parrot/auth/oauth2/persistence.py`
- **Responsibility**: `INTEGRATIONS_STORE` dispatch for the four module functions; documents are `row.model_dump(mode="json")`.
- **Depends on**: M1, M2.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/auth/oauth2/persistence_redis.py  (new)
  class RedisUsersIntegrationStore:
      async def upsert(self, row: UsersIntegrationRow) -> None: ...
      async def get(self, user_id: str, provider: str) -> UsersIntegrationRow | None: ...
      async def delete(self, user_id: str, provider: str) -> None: ...
      async def list(self, user_id: str) -> list[UsersIntegrationRow]:
          """Invalid documents logged and skipped (same rule as the DocumentDB path)."""

  # modifies persistence.py — each function first dispatches when INTEGRATIONS_STORE resolves redis
  async def upsert_users_integration(row: UsersIntegrationRow) -> None:                 # verified: persistence.py:35
  async def get_users_integration(user_id: str, provider: str) -> Optional[UsersIntegrationRow]:  # :60
  async def delete_users_integration(user_id: str, provider: str) -> None:              # verified: persistence.py:82
  async def list_users_integrations(user_id: str) -> List[UsersIntegrationRow]:         # verified: persistence.py:101
  ```

### Module 6: BYOK `user_llm_keys` in Redis
- **Path**: `packages/ai-parrot/src/parrot/auth/broker/byok_redis.py` (new); modifies `packages/ai-parrot/src/parrot/auth/broker/__init__.py`, `packages/ai-parrot/src/parrot/auth/broker/byok.py`, `packages/ai-parrot-server/src/parrot/handlers/studio/byok.py`, `packages/ai-parrot-server/src/parrot/handlers/studio/key_source.py`
- **Responsibility**: `BYOK_STORE=redis`; one accessor replaces the four `byok_store_setting() == "postgres"` branches.
- **Depends on**: M1, M2.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/auth/broker/byok_redis.py  (new)
  def mask_api_key(api_key: str) -> str:
      """First 3 + last 4 chars; all '*' when len <= 7 (moved from studio/byok.py:_mask, which delegates)."""
  class RedisUserLLMKeyStore:
      """Document shape {user_id, provider, api_key (sealed), key_id, masked, created_at, updated_at}."""
      async def get(self, user_id: Any, provider: str) -> str | None: ...
      async def put(self, user_id: Any, provider: str, api_key: str) -> None: ...
      async def delete(self, user_id: Any, provider: str) -> bool: ...
      async def list_masked(self, user_id: Any) -> list[dict[str, Any]]:
          """[{provider, masked, created_at}] sorted by provider; decrypts to mask only when a copied
          document lacks ``masked``; quarantined documents live in the separate `user_llm_keys_quarantine` collection, so nothing needs skipping here."""

  # modifies auth/broker/__init__.py
  def byok_store_setting() -> str:  # verified: __init__.py:53 — now resolve_store_backend("BYOK_STORE")
  def get_user_llm_key_store() -> Any | None:
      """Registered Postgres store (_PG_STORE, :41) when BYOK_STORE=postgres; RedisUserLLMKeyStore when
      redis; None for documentdb."""

  # modifies auth/broker/byok.py — _UserLLMKeyResolver.resolve (branch at :49) uses get_user_llm_key_store();
  #   _resolve_postgres (:98) generalised to any registered/Redis store; fails closed (None) as today.

  # modifies studio/byok.py
  def active_byok_store(app: Any) -> Any | None:
      """get_byok_store(app) when postgres, the core Redis store when redis, None for documentdb."""
  #   _list_keys (:120), _persist_key (:217), _remove_key (:250) use active_byok_store(self.request.app)
  # modifies studio/key_source.py — user_byok_providers (:75) uses active_byok_store(app)
  ```

### Module 7: Toolkit overrides in Redis
- **Path**: `packages/ai-parrot-server/src/parrot/handlers/toolkit_persistence_redis.py` (new); modifies `packages/ai-parrot-server/src/parrot/handlers/toolkit_persistence.py`
- **Responsibility**: `TOOLKIT_OVERRIDES_STORE=redis`; documents are `UserToolkitOverride.model_dump(mode="json")`.
- **Depends on**: M1, M2.
- **Interface Skeleton**:
  ```python
  # toolkit_persistence_redis.py  (new)
  class RedisToolkitOverrideStore:
      async def save(self, override: UserToolkitOverride) -> None: ...
      async def load(self, user_id: str, agent_id: str) -> list[UserToolkitOverride]: ...
      async def remove(self, user_id: str, agent_id: str, slug: str) -> bool: ...
      async def purge_agent(self, agent_ref: str) -> list[UserToolkitOverride]:
          """delete_where({"agent_id": agent_ref}) — atomic per document, returns what was deleted."""
      async def revision(self, user_id: str, agent_id: str) -> str: ...

  # modifies toolkit_persistence.py
  _PG_OVERRIDES: Any = None  # verified: toolkit_persistence.py:29 — kept
  def _active_override_store() -> Any | None:
      """Registered store → it; redis → module-level RedisToolkitOverrideStore; documentdb → None;
      postgres without registration → RuntimeError."""
  #   the five `if _PG_OVERRIDES is not None:` checks (:43, :51, :69, :81, :109) use _active_override_store()
  ```

### Module 8: MCP configs in Redis
- **Path**: `packages/ai-parrot-server/src/parrot/handlers/mcp_persistence_redis.py` (new); modifies `packages/ai-parrot-server/src/parrot/handlers/mcp_persistence.py`
- **Responsibility**: `MCP_CONFIGS_STORE`; soft delete (`active=False`), `created_at` on insert only.
- **Depends on**: M1, M2.
- **Interface Skeleton**:
  ```python
  # mcp_persistence_redis.py  (new)
  class RedisMCPConfigStore:
      async def save(self, config: UserMCPServerConfig) -> None: ...
      async def load(self, user_id: str, agent_id: str) -> list[UserMCPServerConfig]:
          """Active configs only; malformed documents skipped with a warning."""
      async def remove(self, user_id: str, agent_id: str, server_name: str) -> bool: ...

  # modifies mcp_persistence.py — MCPPersistenceService methods dispatch when MCP_CONFIGS_STORE resolves redis
  async def save_user_mcp_config(self, config: UserMCPServerConfig) -> None:  # verified: mcp_persistence.py:49
  async def load_user_mcp_configs(self, user_id: str, agent_id: str) -> List[UserMCPServerConfig]:  # :94
  async def remove_user_mcp_config(self, user_id: str, agent_id: str, server_name: str) -> bool:    # :136
  ```

### Module 9: Telegram MCP configs in Redis
- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/telegram/mcp_persistence_redis.py` (new); modifies `packages/ai-parrot-integrations/src/parrot/integrations/telegram/mcp_persistence.py`, `packages/ai-parrot-integrations/src/parrot/integrations/telegram/mcp_commands.py`
- **Responsibility**: `TELEGRAM_MCP_STORE`; the persistence gate of §2.
- **Depends on**: M1, M2.
- **Interface Skeleton**:
  ```python
  # mcp_persistence_redis.py  (new)
  class RedisTelegramMCPStore:
      async def save(self, user_id: str, name: str, params: TelegramMCPPublicParams,
                     vault_credential_name: Optional[str]) -> None: ...
      async def list(self, user_id: str) -> List[UserTelegramMCPConfig]: ...
      async def read_one(self, user_id: str, name: str) -> Optional[UserTelegramMCPConfig]: ...
      async def remove(self, user_id: str, name: str) -> tuple[bool, Optional[str]]: ...

  # modifies mcp_persistence.py
  def persistence_enabled() -> bool:
      """True when TELEGRAM_MCP_STORE resolves redis, or resolves documentdb and USE_DOCUMENTDB is true."""
  def documentdb_enabled() -> bool:  # verified: mcp_persistence.py:44 — kept as an alias of persistence_enabled()
  #   TelegramMCPPersistenceService (:134) methods dispatch to RedisTelegramMCPStore when redis;
  #   _documentdb() (:57) keeps the documentdb path.
  # modifies mcp_commands.py — the 4 `documentdb_enabled` uses (:53 import, :262, :383, :449) → persistence_enabled
  ```

### Module 10: Dashboards store
- **Path**: `packages/ai-parrot-server/src/parrot/handlers/dashboard_store.py` (new); modifies `packages/ai-parrot-server/src/parrot/handlers/dashboard_handler.py`
- **Responsibility**: `DashboardStore` protocol, `DocumentDbDashboardStore` (today's inline code, moved verbatim), `RedisDashboardStore`, `get_dashboard_store()`; handlers keep URLs, bodies and status codes, plus `409` on duplicate create.
- **Depends on**: M1, M2.
- **Interface Skeleton**:
  ```python
  # dashboard_store.py  (new)
  class DashboardStore(Protocol):
      async def ensure_indexes(self) -> None: ...
      async def get_dashboard(self, dashboard_id: str) -> dict[str, Any] | None: ...
      async def list_dashboards(self, *, module_id: str | None = None,
                                user_id: str | None = None) -> list[dict[str, Any]]:
          """Newest first by created_at."""
      async def create_dashboard(self, doc: dict[str, Any]) -> bool:
          """False when dashboard_id already exists."""
      async def dashboard_exists(self, dashboard_id: str) -> bool: ...
      async def update_dashboard(self, dashboard_id: str, fields: dict[str, Any]) -> bool: ...
      async def delete_dashboard(self, dashboard_id: str) -> bool:
          """Deletes its tabs first."""
      async def get_tab(self, dashboard_id: str, tab_id: str) -> dict[str, Any] | None: ...
      async def list_tabs(self, dashboard_id: str) -> list[dict[str, Any]]:
          """Ascending by ``index``."""
      async def create_tab(self, doc: dict[str, Any]) -> bool: ...
      async def tab_exists(self, dashboard_id: str, tab_id: str) -> bool: ...
      async def update_tab(self, dashboard_id: str, tab_id: str, fields: dict[str, Any]) -> bool: ...
      async def delete_tab(self, dashboard_id: str, tab_id: str) -> bool: ...
  def get_dashboard_store() -> DashboardStore: ...

  # modifies dashboard_handler.py
  async def _ensure_dashboard_indexes(app: web.Application) -> None:  # verified: dashboard_handler.py:37 — store.ensure_indexes()
  class DashboardHandler(BaseView):     # verified: :74 — 13 `async with DocumentDb() as db:` blocks (:45, :113, :148, :198, …) removed
  class DashboardTabHandler(BaseView):  # verified: :341
  ```

### Module 11: Server startup wiring and diagnostics
- **Path**: `packages/ai-parrot/src/parrot/userstore/checks.py` (new); modifies `packages/ai-parrot-server/src/parrot/manager/manager.py`, `packages/ai-parrot-server/src/parrot/handlers/studio/storage/backend.py`
- **Responsibility**: validation in `setup()`, `on_startup` diagnostics, `on_cleanup` close, Studio `postgres` switches through the resolver.
- **Depends on**: M1, M2.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/userstore/checks.py  (new)
  async def run_user_store_diagnostics(logger: logging.Logger | None = None) -> list[str]:
      """Never raises. Returns the warning lines it logged (ping, eviction policy, persistence).
      Skipped entirely when no switch resolves to redis. The implicit-default guard is NOT here:
      it lives in validate_user_store_settings() and does stop startup."""

  # modifies manager.py — BotManager.setup(), after `self._register_shared_redis()` (verified: manager.py:2422)
  #   validate_user_store_settings(); app.on_startup.append(<diagnostics hook>);
  #   app.on_cleanup.append(<close_user_store_redis hook>)

  # modifies studio/storage/backend.py
  def _postgres_switches() -> list[str]:  # verified: backend.py:75 — [k for k in _STORE_SWITCHES if resolve_store_backend(k) == "postgres"]
  ```

### Module 12: DocumentDB → Redis copy CLI
- **Path**: `packages/ai-parrot/src/parrot/userstore/copy.py` (new)
- **Responsibility**: the copy behaviour of §2 (`python -m parrot.userstore.copy`).
- **Depends on**: M2.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/userstore/copy.py  (new)
  @dataclass
  class CopyReport:
      copied: dict[str, int]; skipped: dict[str, int]; duplicates: dict[str, int]; failed: dict[str, int]
  async def copy_to_redis(collections: Sequence[str] | None = None, *, dry_run: bool = False,
                          overwrite: bool = False) -> CopyReport:
      """Read each DocumentDB collection with DocumentDb, write with RedisDocumentStore. Collections
      default to all of USER_STORE_COLLECTIONS; quarantine collections are never copied."""
  def main(argv: list[str] | None = None) -> int:
      """Flags: --dry-run, --overwrite, --collections a,b. Exit 1 when any document failed."""
  ```

### Module 13: Redis vault rotation targets
- **Path**: modifies `packages/ai-parrot/src/parrot/vault_targets.py`, `packages/ai-parrot/pyproject.toml`
- **Responsibility**: `redis:user_credentials`, `redis:user_llm_keys` targets and their entry points.
- **Depends on**: M2.
- **Interface Skeleton**:
  ```python
  # modifies vault_targets.py
  class RedisDocumentTarget(DocumentDbTarget):  # DocumentDbTarget verified: vault_targets.py:46
      """Same ProtectedTarget contract; I/O through RedisDocumentStore (iter_batches, write,
      quarantine, restore_raw). write() raises LookupError when the document is gone."""
      def __init__(self, documents: RedisDocumentStore, quarantine: RedisDocumentStore) -> None: ...
  class RedisUserCredentialsTarget(RedisDocumentTarget): name = "redis:user_credentials"
  class RedisUserLlmKeysTarget(RedisDocumentTarget): name = "redis:user_llm_keys"
  def redis_user_credentials_factory(resources: Mapping[str, Any]) -> Optional[RedisUserCredentialsTarget]:
      """Target when VAULT_STORE resolves redis, else None."""
  def redis_user_llm_keys_factory(resources: Mapping[str, Any]) -> Optional[RedisUserLlmKeysTarget]:
      """Target when BYOK_STORE resolves redis, else None."""

  # modifies pyproject.toml [project.entry-points."navigator_session.vault_targets"] (after line 958)
  # parrot_redis_user_credentials = "parrot.vault_targets:redis_user_credentials_factory"
  # parrot_redis_user_llm_keys = "parrot.vault_targets:redis_user_llm_keys_factory"
  ```

### Module 14: Crew/flow result storage follows the global switch
- **Path**: modifies `packages/ai-parrot/src/parrot/conf.py`, `packages/ai-parrot/src/parrot/bots/flows/core/storage/backends/factory.py`
- **Responsibility**: an unset `CREW_RESULT_STORAGE` resolves through `default_result_storage()`; explicit values are unchanged.
- **Depends on**: M1.
- **Interface Skeleton**:
  ```python
  # modifies conf.py
  CREW_RESULT_STORAGE = config.get("CREW_RESULT_STORAGE", fallback=None)  # verified: conf.py:313 (was fallback="documentdb"); only reader: factory.py:7
  # modifies factory.py — get_result_storage() (verified: factory.py:34)
  name = name_or_instance or CREW_RESULT_STORAGE or default_result_storage()  # verified: factory.py:58 (was `or "documentdb"`)
  #   docstring precedence step 3 (factory.py:42) updated to match
  ```

### Legacy tests that must pin `documentdb`

With Redis as the default, tests that mock `DocumentDb` inside a service take the Redis path. The
task that changes a service adds an autouse fixture (`monkeypatch.setenv("<SWITCH>", "documentdb")`)
to that service's existing test modules — never a package-wide default:

| Module | Existing test modules to pin |
|---|---|
| M3/M4 | `packages/ai-parrot/tests/handlers/test_credentials_handler.py`, `.../test_credentials_integration.py`, `.../test_credential_routes.py`, `packages/ai-parrot/tests/unit/test_mcp_restore_hook.py` |
| M5 | `tests/unit/integrations/oauth2/test_persistence.py`, `packages/ai-parrot-server/tests/unit/test_user_objects_hydration.py`, `packages/ai-parrot-server/tests/unit/test_agenttalk_oauth_hydration.py` |
| M6 | `packages/ai-parrot/tests/unit/test_user_llm_key_resolver.py`, `packages/ai-parrot-server/tests/studio/test_byok.py`, `.../test_key_source_pa2.py`, `.../test_keys_empty_api_key.py` |
| M7 | `packages/ai-parrot-server/tests/studio/test_toolkit_overrides.py`, `packages/ai-parrot-server/tests/test_agenttalk_toolkit_overrides.py` |
| M8 | `packages/ai-parrot/tests/unit/test_mcp_persistence.py`, `packages/ai-parrot/tests/unit/test_mcp_helper_handler.py` |
| M9 | `packages/ai-parrot-integrations/tests/integrations/telegram/test_mcp_documentdb_gate.py`, `.../test_mcp_commands.py` |
| M14 | `tests/bots/flows/core/storage/test_factory.py` — `test_factory_defaults_to_documentdb` (line 48) becomes "defaults follow `PARROT_USER_STORE`" |
| M11 | every test that runs `BotManager.setup()` while the loaded env sets `DOCUMENTDB_HOSTNAME`/`DOCUMENTDB_DBNAME` (the implicit-default guard): set `PARROT_USER_STORE` in its fixture |

The task re-runs each listed module to confirm which ones actually need the pin; a module that does
not reach DocumentDB is left untouched.

---

## 4. Test Specification

Redis-backed tests use the real local Redis on db 15 through `parrot.userstore.testing.redis_test_settings`
(unique prefix, prefix-only cleanup, `pytest.skip` when unreachable). `fakeredis` is not available.

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_resolve_default_is_redis` | M1 | no switch, no global → `redis` |
| `test_resolve_precedence` | M1 | per-store beats global beats default; `store_backend_source` matches |
| `test_resolve_invalid_value_raises` | M1 | `VAULT_STORE=mongo` / `PARROT_USER_STORE=postgres` → `UserStoreMisconfigured` |
| `test_postgres_only_where_allowed` | M1 | `MCP_CONFIGS_STORE=postgres` raises; `VAULT_STORE=postgres` resolves |
| `test_redis_url_default_db6` | M1 | URL built from `REDIS_HOST`/`REDIS_PORT` and db 6 |
| `test_client_per_event_loop` | M1 | two loops get two clients; close forgets the current one |
| `test_put_get_delete_roundtrip` | M2 | key encoding with `:` and `/` in values; `str` key comparison (`35` vs `"35"`) |
| `test_upsert_on_insert_only_once` | M2 | `on_insert` fields survive a second upsert |
| `test_index_follows_field_change` | M2 | changing an indexed field moves the id between index sets |
| `test_find_intersects_indexes` | M2 | filters by indexed + non-indexed fields; no-filter returns all |
| `test_delete_where_returns_docs` | M2 | returns exactly what it deleted |
| `test_concurrent_upserts_keep_indexes` | M2 | 20 concurrent upserts on one key leave one id per index set |
| `test_vault_redis_roundtrip` | M3 | store → retrieve → list → exists → delete; `created_at` kept |
| `test_vault_postgres_unregistered_fails_closed` | M3 | `VAULT_STORE=postgres` with no store → `RuntimeError`, DocumentDB not touched |
| `test_vault_documentdb_path_unchanged` | M3 | `documentdb` still uses the inline code (mocked `DocumentDb`) |
| `test_credentials_handler_uses_vault_utils` | M4 | four verbs with `VAULT_STORE=redis`; same status codes/bodies as today |
| `test_credentials_put_no_duplicate` | M4 | two PUTs leave one stored credential with the latest value |
| `test_mcp_restore_reads_vault_utils` | M4 | restore decrypts via `retrieve_vault_credential`; missing → skipped |
| `test_pg_vault_list_and_exists` | M4 | new `PgVaultCredentialStore` methods (asyncpg mock as in `test_vault_store.py`) |
| `test_integrations_redis_roundtrip` | M5 | upsert/get/list/delete; invalid document skipped |
| `test_byok_redis_store` | M6 | put/get/list_masked/delete; masked fallback for copied docs |
| `test_byok_resolver_redis` | M6 | `_UserLLMKeyResolver` returns the key; returns None on decrypt failure |
| `test_studio_keys_redis` | M6 | `StudioKeysHandler` GET/POST/DELETE with `BYOK_STORE=redis` |
| `test_overrides_redis_store` | M7 | save/load/remove/purge_agent/revision |
| `test_mcp_configs_redis_soft_delete` | M8 | remove sets `active=False`; load hides it; save reactivates, keeps `created_at` |
| `test_telegram_gate` | M9 | redis → enabled regardless of `USE_DOCUMENTDB`; documentdb follows `USE_DOCUMENTDB` |
| `test_telegram_redis_roundtrip` | M9 | save/list/read_one/remove returns the vault name |
| `test_dashboard_store_contract` | M10 | same assertions run against Redis and a mocked DocumentDB store |
| `test_dashboard_duplicate_create_409` | M10 | both backends |
| `test_dashboard_delete_cascades_tabs` | M10 | tabs gone after dashboard delete |
| `test_startup_rejects_invalid_switch` | M11 | `BotManager.setup` raises `UserStoreMisconfigured` |
| `test_guard_implicit_redis_with_documentdb` | M1/M11 | `DOCUMENTDB_HOSTNAME` set, no switches → `UserStoreMisconfigured` listing every store + `CREW_RESULT_STORAGE`, message names both fixes |
| `test_guard_cleared_by_explicit_switch` | M1 | `PARROT_USER_STORE=redis` or `=documentdb` (or all per-store switches + `CREW_RESULT_STORAGE`) → no error |
| `test_guard_absent_without_documentdb_config` | M1 | neither `DOCUMENTDB_HOSTNAME` nor `DOCUMENTDB_DBNAME` → default redis, no error |
| `test_diagnostics_warnings` | M11 | allkeys policy, persistence off; `CONFIG` error skipped; never raises |
| `test_studio_postgres_switches_resolver` | M11 | `PARROT_USER_STORE=documentdb` + `VAULT_STORE=postgres` → `["VAULT_STORE"]` |
| `test_copy_insert_only_and_overwrite` | M12 | skip existing; `--overwrite` newer-wins; dry-run writes nothing |
| `test_copy_collapses_duplicates` | M12 | duplicate DocumentDB docs → newest copied, `duplicates` counted |
| `test_copy_no_secret_in_logs` | M12 | caplog contains no ciphertext |
| `test_redis_target_rotation_cycle` | M13 | iter_batches → write with new key_version → quarantine → restore_raw |
| `test_redis_target_factories` | M13 | factory returns None unless the switch resolves redis |
| `test_result_storage_default_follows_global` | M14 | unset → `RedisResultStorage`; `PARROT_USER_STORE=documentdb` → `DocumentDbResultStorage` |
| `test_result_storage_explicit_value_wins` | M14 | `CREW_RESULT_STORAGE=postgres` → `PostgresResultStorage` whatever the global switch |

### Integration Tests
| Test | Description |
|---|---|
| `test_agenttalk_without_mongodb` | `PARROT_USER_STORE=redis`, `DOCUMENTDB_HOSTNAME` pointing at a closed port: OAuth hydration and toolkit-override loading complete without any `DocumentDb` connection attempt (patch `DocumentDb.documentdb_connect` to fail the test if called) |
| `test_copy_then_read_through_services` | seed mocked DocumentDB docs for all 8 collections, run `copy_to_redis`, read each back through its service with `redis` switches; sealed credential decrypts with the same keyring |

### Validation Contract

tests:
- packages/ai-parrot/tests/userstore/test_settings.py
- packages/ai-parrot/tests/userstore/test_redis_documents.py
- packages/ai-parrot/tests/userstore/test_copy.py
- packages/ai-parrot/tests/security/test_vault_store_redis.py
- packages/ai-parrot/tests/security/test_vault_targets_redis.py
- packages/ai-parrot/tests/security/test_vault_targets.py
- packages/ai-parrot/tests/auth/test_integrations_store_redis.py
- packages/ai-parrot/tests/auth/test_byok_store_redis.py
- packages/ai-parrot/tests/handlers/test_credentials_handler.py
- packages/ai-parrot/tests/unit/test_mcp_persistence.py
- packages/ai-parrot/tests/unit/test_mcp_restore_hook.py
- packages/ai-parrot/tests/unit/test_user_llm_key_resolver.py
- packages/ai-parrot-server/tests/unit/test_credentials_store_dispatch.py
- packages/ai-parrot-server/tests/unit/test_toolkit_overrides_redis.py
- packages/ai-parrot-server/tests/unit/test_mcp_persistence_redis.py
- packages/ai-parrot-server/tests/unit/test_dashboard_store.py
- packages/ai-parrot-server/tests/unit/test_user_store_startup.py
- packages/ai-parrot-server/tests/unit/test_agenttalk_without_mongodb.py
- packages/ai-parrot-server/tests/studio/storage/test_vault_store.py
- packages/ai-parrot-server/tests/studio/storage/test_store_registration.py
- packages/ai-parrot-server/tests/studio/test_byok.py
- packages/ai-parrot-server/tests/studio/test_toolkit_overrides.py
- packages/ai-parrot-server/tests/unit/test_user_objects_hydration.py
- packages/ai-parrot-integrations/tests/integrations/telegram/test_mcp_persistence_redis.py
- packages/ai-parrot-integrations/tests/integrations/telegram/test_mcp_documentdb_gate.py
- tests/unit/integrations/oauth2/test_persistence.py
- tests/bots/flows/core/storage/test_factory.py
- packages/ai-parrot/tests/handlers/test_credentials_integration.py
- packages/ai-parrot/tests/handlers/test_credential_routes.py
- packages/ai-parrot/tests/unit/auth/test_users_integrations_model.py
- packages/ai-parrot/tests/unit/test_mcp_helper_handler.py
- packages/ai-parrot/tests/userstore/test_user_stores_docs.py
- packages/ai-parrot-server/tests/unit/test_agenttalk_oauth_hydration.py
- packages/ai-parrot-server/tests/unit/test_dashboard_handler_store.py
- packages/ai-parrot-server/tests/unit/test_vault_access_centralised.py
- packages/ai-parrot-server/tests/unit/test_userstore_copy_roundtrip.py
- packages/ai-parrot-server/tests/studio/storage/test_overrides_store.py
- packages/ai-parrot-server/tests/studio/storage/test_byok_store.py
- packages/ai-parrot-server/tests/studio/test_byok_redis.py
- packages/ai-parrot-server/tests/studio/test_integration.py
- packages/ai-parrot-server/tests/studio/test_key_source_pa2.py
- packages/ai-parrot-server/tests/studio/test_keys_empty_api_key.py
- packages/ai-parrot-server/tests/studio/test_tooling_identity.py
- packages/ai-parrot-server/tests/test_agenttalk_toolkit_overrides.py
- packages/ai-parrot-server/tests/manager/test_registry_only.py
- packages/ai-parrot-server/tests/manager/test_studio_runtime.py
- packages/ai-parrot-integrations/tests/integrations/telegram/test_mcp_commands.py
- tests/bots/flows/core/storage/test_persistence_mixin.py
- tests/bots/flows/core/storage/test_agentcrew_lifecycle.py
- tests/bots/flows/core/storage/test_agentsflow_lifecycle.py
markers: none

### Test Data / Fixtures
```python
@pytest.fixture
async def redis_user_store(monkeypatch):
    """PARROT_USER_STORE=redis on db 15 with a unique prefix (skips when Redis is unreachable)."""
    monkeypatch.setenv("PARROT_USER_STORE", "redis")
    async with redis_test_settings(monkeypatch) as prefix:
        yield prefix

@pytest.fixture
def vault_keyring(monkeypatch):
    """VAULT_MASTER_KEY_v1 / VAULT_ACTIVE_KEY_ID test keys + reset_vault_keyring() around the test."""
```

---

## 5. Acceptance Criteria

- [ ] AC1: With no switch and no `PARROT_USER_STORE`, every one of the 8 collections is served by Redis.
- [ ] AC2: `PARROT_USER_STORE=documentdb` restores today's behaviour for all stores; a per-store switch overrides the global one in both directions.
- [ ] AC3: An invalid value in any switch makes `BotManager.setup()` raise `UserStoreMisconfigured`; `postgres` on a switch that does not support it is invalid.
- [ ] AC4: A switch resolved to `postgres` with no registered store raises instead of falling back to DocumentDB (vault, BYOK, toolkit overrides).
- [ ] AC5: No module outside `parrot.security.vault_utils`, `parrot.security.vault_store_redis`, `parrot.vault_targets`, `parrot.userstore.copy` and Studio `secrets_copy` reads or writes `user_credentials` (grep check in a test).
- [ ] AC6: `PUT /api/v1/users/credentials/{name}` twice leaves exactly one stored credential holding the second value, in every backend.
- [ ] AC7: `CredentialsHandler` status codes and response bodies are unchanged (existing handler tests pass, pinned to `documentdb`, and the same cases pass on `redis`).
- [ ] AC8: An agent call with all stores on Redis and MongoDB unreachable makes zero `DocumentDb` connection attempts (`test_agenttalk_without_mongodb`).
- [ ] AC9: Telegram `/add_mcp` persists with `TELEGRAM_MCP_STORE` resolved to `redis` even when `USE_DOCUMENTDB=false`.
- [ ] AC10: Dashboards CRUD works on Redis with identical URLs and bodies; duplicate create answers 409; startup does not contact MongoDB when `DASHBOARDS_STORE` resolves to `redis`.
- [ ] AC11: A credential sealed into DocumentDB, copied with `python -m parrot.userstore.copy`, decrypts from Redis with the same keyring; re-running the copy is a no-op; `--overwrite` only replaces strictly newer sources.
- [ ] AC12: navigator-vault rotation over `redis:user_credentials` / `redis:user_llm_keys` re-seals values and they still decrypt; quarantine and restore round-trip.
- [ ] AC13: Startup logs a WARNING for an `allkeys-*` eviction policy and for disabled persistence; neither stops startup.
- [ ] AC14: No log line written by this feature contains a credential value, a ciphertext or a Redis password.
- [ ] AC15: `ruff check` passes on every touched file (TID251 import bans included); all Validation Contract tests pass.
- [ ] AC16: Documentation pages declared in §10 exist under `wiki/` (`parrot sdd techwiki check`).
- [ ] AC17: With `DOCUMENTDB_HOSTNAME` (or `DOCUMENTDB_DBNAME`) set and no `PARROT_USER_STORE`, `BotManager.setup()` raises `UserStoreMisconfigured` listing every store (and `CREW_RESULT_STORAGE` when unset) that would default to Redis, naming both fixes; `PARROT_USER_STORE` set to either value starts normally; with neither DocumentDB variable set, startup is unaffected.
- [ ] AC18: With `CREW_RESULT_STORAGE` unset, `get_result_storage()` returns `RedisResultStorage` by default and `DocumentDbResultStorage` when `PARROT_USER_STORE=documentdb`; an explicit `CREW_RESULT_STORAGE` wins.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor.** Verified against `origin/dev` @ `b93e626659`
> (2026-11-11); re-checked unchanged at `41df674d50` (M14 rows added there). Line numbers drift;
> `/sdd-task` re-runs `grep -c` for every anchor it uses.

### Verified Imports
```python
from parrot.interfaces.documentdb import DocumentDb                      # verified: interfaces/documentdb.py:65
from parrot.security.vault_utils import (                                # verified: security/vault_utils.py:46,57,92,145,184
    set_vault_credential_store, get_vault_keyring, store_vault_credential,
    retrieve_vault_credential, delete_vault_credential, VAULT_CRED_COLLECTION,
)
from parrot.security.credentials_utils import (                          # verified: credentials_utils.py:53,68,83,108
    credential_context, llm_key_context, encrypt_credential, decrypt_credential,
)
from parrot.auth.broker import set_user_llm_key_store, byok_store_setting, _UserLLMKeyResolver  # verified: auth/broker/__init__.py:31,44,53
from parrot.auth.oauth2.models import UsersIntegrationRow                # verified: auth/oauth2/models.py:172
from parrot.mcp.registry import UserMCPServerConfig                      # verified: packages/ai-parrot/src/parrot/mcp/registry.py:96 (core, not server)
from parrot.handlers.toolkit_persistence import UserToolkitOverride, set_toolkit_override_store  # verified: server toolkit_persistence.py:17,32
from parrot.vault_targets import DocumentDbTarget, QUARANTINE_SUFFIX     # verified: vault_targets.py:46,43
from navigator_session.vault.registry import BackupSink, BackupSource, VaultRow  # verified: vault_targets.py:32
from navconfig import config                                             # call-time env reads verified (os.environ changes visible)
import redis.asyncio as aioredis                                         # verified: manager.py:1759 (redis 5.2.1 via navigator-session)
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/interfaces/documentdb.py
class DocumentDb:                                              # line 65
    async def documentdb_connect(self) -> None:                # line 237 — raises ConnectionError
    async def close(self) -> None:                             # line 264
    async def update_one(...)                                  # line 342
    async def delete_many(...)                                 # line 354
    async def read(...)                                        # line 370
    async def read_one(self, collection_name: str, query: dict, **kwargs) -> Optional[dict]:  # line 407
    async def exists(self, collection_name: str, query: dict) -> bool:                        # line 422
    async def write(self, collection_name: str, data: Union[dict, List[dict]], **kwargs) -> Any:  # line 440 — INSERT
    async def update(self, collection_name: str, query: dict, update_data: dict, upsert: bool = False, **kwargs) -> Any:  # line 469
    async def delete(self, collection_name: str, query: dict, **kwargs) -> Any:               # line 496
    def save_background(...)                                   # line 529 — fire-and-forget INSERT via write() (line 603)
    async def create_indexes(self, collection_name: str, keys: List[Union[str, tuple, dict]]) -> None:  # line 874

# packages/ai-parrot/src/parrot/security/vault_utils.py
VAULT_CRED_COLLECTION: str = "user_credentials"                # line 41
_PG_VAULT_STORE: Any = None                                    # line 43
def set_vault_credential_store(store: Any) -> None:            # line 46
async def store_vault_credential(user_id: str, vault_name: str, secret_params: Dict[str, Any]) -> None:  # line 92
async def retrieve_vault_credential(user_id: str, vault_name: str) -> Dict[str, Any]:  # line 145 — KeyError when absent
async def delete_vault_credential(user_id: str, vault_name: str) -> None:  # line 184
def oauth2_vault_name(provider_id: str, channel: str, user_id: str) -> str:  # line 205

# packages/ai-parrot/src/parrot/security/credentials_utils.py
def encrypt_credential(credential: dict, context: VaultContext, keyring: KeyRing, *, key_id: Optional[int] = None) -> str:  # line 83

# packages/ai-parrot/src/parrot/auth/broker/__init__.py
_PG_STORE: Any = None                                          # line 41
def set_user_llm_key_store(store: Any) -> None:                # line 44
def byok_store_setting() -> str:                               # line 53 — today: "documentdb" | "postgres", default documentdb

# packages/ai-parrot/src/parrot/auth/broker/byok.py
class _UserLLMKeyResolver(CredentialResolver):
    COLLECTION: str = "user_llm_keys"
    async def resolve(self, channel: str, user_id: str) -> str | None:   # branch at line 49
    async def _resolve_postgres(self, channel: str, user_id: str) -> str | None:  # line 98

# packages/ai-parrot/src/parrot/auth/oauth2/persistence.py
USERS_INTEGRATIONS_COLLECTION: str = "users_integrations"      # line 27
# functions at lines 35, 60, 82, 101 (see M5)

# packages/ai-parrot/src/parrot/auth/oauth2/models.py
class UsersIntegrationRow(BaseModel):                          # line 172 — user_id, provider, …, connected_at: datetime, updated_at/last_used_at: Optional[datetime]

# packages/ai-parrot/src/parrot/mcp/registry.py
class UserMCPServerConfig(BaseModel):                          # line 96 — server_name, agent_id, user_id, params, vault_credential_name, active=True, created_at/updated_at: Optional[str]

# packages/ai-parrot/src/parrot/vault_targets.py
QUARANTINE_SUFFIX = "_quarantine"                              # line 43
class DocumentDbTarget:                                        # line 46 — iter_batches, transaction, write, quarantine, export_raw, restore_raw, to_backup_record, _row
class UserCredentialsTarget(DocumentDbTarget): name = "docdb:user_credentials"
class UserLlmKeysTarget(DocumentDbTarget): name = "docdb:user_llm_keys"
def user_llm_keys_factory(resources: Mapping[str, Any]) -> Optional[UserLlmKeysTarget]:  # line 260

# packages/ai-parrot/src/parrot/vault_targets.py (cont.)
def _default_docdb_factory() -> Optional[Callable[[], Any]]:  # line 235 — DOCUMENTDB_HOSTNAME or DOCUMENTDB_DBNAME rule

# packages/ai-parrot/src/parrot/conf.py
CREW_RESULT_STORAGE = config.get("CREW_RESULT_STORAGE", fallback="documentdb")  # line 313 — only reader: factory.py:7

# packages/ai-parrot/src/parrot/bots/flows/core/storage/backends/factory.py
def get_result_storage(name_or_instance: Union[str, "ResultStorage", None] = None) -> "ResultStorage":  # line 34
    name = name_or_instance or CREW_RESULT_STORAGE or "documentdb"  # line 58

# packages/ai-parrot-server/src/parrot/handlers/credentials.py
class CredentialsHandler(...):
    COLLECTION: str = "user_credentials"                       # line 71
    def _get_user_id(self) -> str:                             # line 78
    def _set_session_credential(...)                           # line 110
    def _remove_session_credential(self, name: str) -> None:   # line 121
    async def get(self) -> web.Response:                       # line 152
    async def post(self) -> web.Response:                      # line 229 — background INSERT today
    async def put(self) -> web.Response:                       # line 330 — background INSERT today (duplicates)
    async def delete(self) -> web.Response:                    # line 436

# packages/ai-parrot-server/src/parrot/handlers/agent.py
class AgentTalk(BaseView):                                     # line 133
    async def _restore_user_mcp_servers(...)                   # line 1127 — direct DocumentDb read at 1217-1225

# packages/ai-parrot-server/src/parrot/handlers/toolkit_persistence.py
COLLECTION: str = "user_toolkit_configs"                       # line 14
class UserToolkitOverride(BaseModel)                           # line 17
_PG_OVERRIDES: Any = None                                      # line 29
class ToolkitConfigService:                                    # line 38 — save, load, remove, purge_agent, revision

# packages/ai-parrot-server/src/parrot/handlers/studio/storage/vault_store.py
class PgVaultCredentialStore:                                  # line 23 — store, retrieve, delete (line 43)

# packages/ai-parrot-server/src/parrot/handlers/studio/storage/byok_store.py
class PgUserLLMKeyStore:                                       # get, put, delete, list_masked (line 61)
def get_byok_store(app: Any) -> PgUserLLMKeyStore:             # raises RuntimeError when unregistered

# packages/ai-parrot-server/src/parrot/handlers/studio/storage/backend.py
_STORE_SWITCHES = ("VAULT_STORE", "TOOLKIT_OVERRIDES_STORE", "BYOK_STORE")  # line 67
def _postgres_switches() -> list[str]:                         # line 75

# packages/ai-parrot-server/src/parrot/manager/manager.py
def _register_shared_redis(self) -> None:                      # line 1740
self._register_shared_redis()                                  # line 2422 (inside setup())
await _ensure_dashboard_indexes(app)                           # line 3238

# packages/ai-parrot-integrations/src/parrot/integrations/telegram/mcp_persistence.py
def documentdb_enabled() -> bool:                              # line 44 — reads parrot.conf.USE_DOCUMENTDB
async def _documentdb() -> AsyncIterator[Optional[DocumentDb]]:  # line 57
class TelegramMCPPersistenceService:                           # line 134; COLLECTION at line 153
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `RedisVaultCredentialStore` | `encrypt_credential` / `decrypt_credential` | call with `credential_context` | `credentials_utils.py:83,108,53` |
| `get_vault_credential_store` | `_PG_VAULT_STORE` registration | module global | `vault_utils.py:43,46` |
| `active_byok_store` | `get_byok_store(app)` | call | `studio/storage/byok_store.py` |
| `RedisToolkitOverrideStore` | `UserToolkitOverride` | model dump/validate | `toolkit_persistence.py:17` |
| `RedisDocumentTarget` | `DocumentDbTarget` | subclass | `vault_targets.py:46` |
| startup hooks | `BotManager.setup()` | after `_register_shared_redis()` | `manager.py:2422` |
| `_postgres_switches` | `resolve_store_backend` | call | `backend.py:75` |

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot.userstore`~~ — created by this feature (M1).
- ~~`fakeredis`~~ — not installed, not declared in any `pyproject.toml`.
- ~~`PgVaultCredentialStore.list_credentials` / `.exists`~~ — added by M4.
- ~~`vault_utils.list_vault_credentials` / `vault_credential_exists` / `get_vault_credential_store`~~ — added by M3.
- ~~`DocumentDb.upsert` / `DocumentDb.find`~~ — not methods; DocumentDB code uses `update_one(..., upsert=True)` / `read`.
- ~~`parrot.storage.userstore`~~ — do not put the package under `parrot/storage/` (its `__init__` imports DynamoDB/S3 layers).
- ~~`PARROT_USER_STORE`, `MCP_CONFIGS_STORE`, `TELEGRAM_MCP_STORE`, `INTEGRATIONS_STORE`, `DASHBOARDS_STORE`~~ — no such settings today.
- ~~`parrot/mcp/registry.py` in ai-parrot-server~~ — `UserMCPServerConfig` lives in core `packages/ai-parrot/src/parrot/mcp/registry.py`.
- ~~`Postgres` backends for `user_mcp_configs`, `telegram_user_mcp_configs`, `users_integrations`, `dashboards`~~ — none exist; not added here.

### Edit Sites (Blueprint Anchors)

Verified against: `b93e626659` (no drift in these files at `41df674d50`, where the M14 rows were verified)

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/userstore/__init__.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/userstore/settings.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/userstore/redis_documents.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/userstore/collections.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/userstore/testing.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/userstore/checks.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/userstore/copy.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/security/vault_store_redis.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/security/vault_utils.py` | MODIFY | `_PG_VAULT_STORE: Any = None` | `vault_utils.py:43` | 1 |
| `packages/ai-parrot/src/parrot/security/vault_utils.py` | MODIFY | `async def store_vault_credential(` | `vault_utils.py:92` | 1 |
| `packages/ai-parrot/src/parrot/security/vault_utils.py` | MODIFY | `async def retrieve_vault_credential(` | `vault_utils.py:145` | 1 |
| `packages/ai-parrot/src/parrot/security/vault_utils.py` | MODIFY | `async def delete_vault_credential(user_id: str, vault_name: str) -> None:` | `vault_utils.py:184` | 1 |
| `packages/ai-parrot/src/parrot/security/__init__.py` | MODIFY | `'VAULT_CRED_COLLECTION',` | `security/__init__.py:77` | 1 |
| `packages/ai-parrot/src/parrot/auth/oauth2/persistence_redis.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/auth/oauth2/persistence.py` | MODIFY | `async def upsert_users_integration(row: UsersIntegrationRow) -> None:` | `persistence.py:35` | 1 |
| `packages/ai-parrot/src/parrot/auth/oauth2/persistence.py` | MODIFY | `async def get_users_integration(` | `persistence.py:60` | 1 |
| `packages/ai-parrot/src/parrot/auth/oauth2/persistence.py` | MODIFY | `async def delete_users_integration(user_id: str, provider: str) -> None:` | `persistence.py:82` | 1 |
| `packages/ai-parrot/src/parrot/auth/oauth2/persistence.py` | MODIFY | `async def list_users_integrations(user_id: str) -> List[UsersIntegrationRow]:` | `persistence.py:101` | 1 |
| `packages/ai-parrot/src/parrot/auth/broker/byok_redis.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/auth/broker/__init__.py` | MODIFY | `def byok_store_setting() -> str:` | `__init__.py:53` | 1 |
| `packages/ai-parrot/src/parrot/auth/broker/byok.py` | MODIFY | `if _pkg.byok_store_setting() == "postgres":` | `byok.py:49` | 1 |
| `packages/ai-parrot/src/parrot/auth/broker/byok.py` | MODIFY | `async def _resolve_postgres(self, channel: str, user_id: str) -> str \| None:` | `byok.py:98` | 1 |
| `packages/ai-parrot/src/parrot/vault_targets.py` | MODIFY | `def user_llm_keys_factory(resources: Mapping[str, Any]) -> Optional[UserLlmKeysTarget]:` | `vault_targets.py:260` | 1 |
| `packages/ai-parrot/pyproject.toml` | MODIFY | `parrot_user_llm_keys = "parrot.vault_targets:user_llm_keys_factory"` | `pyproject.toml:958` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/credentials.py` | MODIFY | `from parrot.interfaces.documentdb import DocumentDb` | `credentials.py:29` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/credentials.py` | MODIFY | `async def get(self) -> web.Response:` | `credentials.py:152` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/credentials.py` | MODIFY | `async def post(self) -> web.Response:` | `credentials.py:229` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/credentials.py` | MODIFY | `async def put(self) -> web.Response:` | `credentials.py:330` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/credentials.py` | MODIFY | `async def delete(self) -> web.Response:` | `credentials.py:436` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/agent.py` | MODIFY | `"user_credentials",` (inside `async with DocumentDb() as db:` at :1217) | `agent.py:1219` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/studio/storage/vault_store.py` | MODIFY | `async def delete(self, user_id: Any, vault_name: str) -> None:` | `vault_store.py:43` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/toolkit_persistence_redis.py` | CREATE | — | — | — |
| `packages/ai-parrot-server/src/parrot/handlers/toolkit_persistence.py` | MODIFY | `_PG_OVERRIDES: Any = None` (+ 5× `if _PG_OVERRIDES is not None:` at :43 :51 :69 :81 :109) | `toolkit_persistence.py:29` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/mcp_persistence_redis.py` | CREATE | — | — | — |
| `packages/ai-parrot-server/src/parrot/handlers/mcp_persistence.py` | MODIFY | `async def save_user_mcp_config(self, config: UserMCPServerConfig) -> None:` | `mcp_persistence.py:49` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/mcp_persistence.py` | MODIFY | `async def load_user_mcp_configs(` | `mcp_persistence.py:94` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/mcp_persistence.py` | MODIFY | `async def remove_user_mcp_config(` | `mcp_persistence.py:136` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/dashboard_store.py` | CREATE | — | — | — |
| `packages/ai-parrot-server/src/parrot/handlers/dashboard_handler.py` | MODIFY | `async def _ensure_dashboard_indexes(app: web.Application) -> None:` | `dashboard_handler.py:37` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/dashboard_handler.py` | MODIFY | `class DashboardHandler(BaseView):` (13× `async with DocumentDb() as db:` from :45) | `dashboard_handler.py:74` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/dashboard_handler.py` | MODIFY | `class DashboardTabHandler(BaseView):` | `dashboard_handler.py:341` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/studio/byok.py` | MODIFY | `def _mask(api_key: str) -> str:` | `byok.py:47` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/studio/byok.py` | MODIFY | `async def _list_keys(self, user, keyring) -> list[dict]:` | `byok.py:120` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/studio/byok.py` | MODIFY | `async def _persist_key(self, user, provider: str, encrypted: str, plaintext: str) -> None:` | `byok.py:217` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/studio/byok.py` | MODIFY | `async def _remove_key(self, user, provider: str) -> None:` | `byok.py:250` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/studio/key_source.py` | MODIFY | `async def user_byok_providers(app: Any, user_id: Any) -> frozenset[str]:` | `key_source.py:75` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/studio/storage/backend.py` | MODIFY | `def _postgres_switches() -> list[str]:` | `backend.py:75` | 1 |
| `packages/ai-parrot-server/src/parrot/manager/manager.py` | MODIFY | `self._register_shared_redis()` | `manager.py:2422` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/mcp_persistence_redis.py` | CREATE | — | — | — |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/mcp_persistence.py` | MODIFY | `def documentdb_enabled() -> bool:` | `mcp_persistence.py:44` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/mcp_persistence.py` | MODIFY | `class TelegramMCPPersistenceService:` | `mcp_persistence.py:134` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/mcp_commands.py` | MODIFY | `documentdb_enabled` (import :53, uses :262 :383 :449) | `mcp_commands.py:53` | 4 |
| `packages/ai-parrot/src/parrot/conf.py` | MODIFY | `CREW_RESULT_STORAGE = config.get("CREW_RESULT_STORAGE", fallback="documentdb")` | `conf.py:313` | 1 |
| `packages/ai-parrot/src/parrot/bots/flows/core/storage/backends/factory.py` | MODIFY | `name = name_or_instance or CREW_RESULT_STORAGE or "documentdb"` | `factory.py:58` | 1 |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Store registration and dispatch follow FEAT-621: a module global set by the server (`set_*_store`)
  wins; Redis stores are built lazily in the owning module; the DocumentDB inline code stays as it is.
- Core never imports server or integrations code (Redis stores live beside their services).
- Async only (`redis.asyncio`); no `redis` sync client, no `requests`/`httpx` (TID251).
- Pydantic `model_dump(mode="json")` for every document written to Redis; validate on read and skip
  malformed documents with a warning, as the DocumentDB paths do.
- `self.logger` / module loggers; never log values, ciphertexts or credentialed URLs.
- Redis tests: real Redis db 15, unique prefix, prefix-only cleanup, skip when unreachable.

### Known Risks / Gotchas
- **Breaking default.** An upgraded deployment that relied on the implicit DocumentDB default
  would read empty Redis stores: credentials, OAuth connections and overrides "disappear"
  (they are still in MongoDB). Mitigation: startup fails closed when DocumentDB is configured and
  any store defaults implicitly (§2), with the one-line fix in the error; release notes and the
  wiki page repeat it.
- **Local env files.** A developer `env/.env` that still sets `DOCUMENTDB_HOSTNAME` (this
  repository's does: `localhost`) must add `PARROT_USER_STORE=redis` or `=documentdb` once. Tests
  that run `BotManager.setup()` under such an env hit the guard; the M11 task finds them and sets
  the switch in their fixtures.
- **Crew results expire in Redis.** With the new default, results use `RedisResultStorage` and its
  7-day TTL, unlike DocumentDB. Installations that keep results longer set
  `CREW_RESULT_STORAGE=documentdb|postgres` or raise `CREW_RESULT_STORAGE_REDIS_TTL` (`0` disables it).
- **Redis is not a cache here.** Secrets have no TTL. An `allkeys-*` eviction policy or a Redis
  without RDB/AOF loses them. The diagnostic warns; operators of managed Redis must check settings
  that `CONFIG GET` cannot read.
- **Shared logical DB.** Default db 6 avoids the cache (2), sessions (0), jobs/general (1),
  history/datasets (3) and services/OAuth state (4) DBs used today (§8 Q3). Redis Cluster and
  DB-0-only services must set `PARROT_USER_STORE_REDIS_URL`; the startup `PING` diagnostic reports
  a URL whose DB the server rejects.
- **Event loops.** A `redis.asyncio` client is bound to the loop that first used it; the per-loop
  client cache avoids "attached to a different loop" errors in tests and multi-loop hosts.
- **Index consistency.** Index maintenance must be transactional (WATCH/MULTI) — a crash between
  writing a document and its index sets would make `find` miss it. `find` tolerates ids whose
  document is gone (skips them).
- **`user_id` types.** DocumentDB stores whatever type callers pass (`35` or `"35"`); Redis compares
  key/index fields as strings. Do not change the type callers pass.
- **Legacy tests.** Flipping the default changes the code path of every test that mocks `DocumentDb`;
  pin per module (§3 table), never globally.
- **Entry points.** New `navigator_session.vault_targets` entry points are only discovered after the
  package metadata is reinstalled (editable install refresh) — an operator step, and the reason M13
  is an exclusive task. Tests call the factories directly.
- **Quarantine in Redis** keys documents by identity, so quarantining the same identity twice keeps
  the latest copy only (DocumentDB keeps both).
- **Copy duplicates.** DocumentDB may hold several `user_credentials` documents per key because of the
  PUT bug; the copy keeps the newest by `updated_at`.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `redis` | `>=5.0` (5.2.1 installed via `navigator-session`) | `redis.asyncio` client; no new declaration needed unless a task finds `ai-parrot` must declare it directly (then add `redis>=5.0` to core `pyproject.toml` — exclusive task) |

---

## Decisions

```yaml
schema_version: 1
document_id: redis-user-stores
entries:
  - id: redis-default-user-stores
    statement: User-scoped stores resolve their backend per store switch, then PARROT_USER_STORE, then Redis as the default; an unset CREW_RESULT_STORAGE follows the same global switch; an invalid value, or an implicit Redis default on an installation with DocumentDB configured, fails closed at startup.
    relation: constrains
    about: [config]
    targets:
      - sym:packages/ai-parrot/src/parrot/auth/broker/__init__.py#byok_store_setting
      - sym:packages/ai-parrot-server/src/parrot/handlers/studio/storage/backend.py#_postgres_switches
    contradicts: []
    supersedes: []
    rationale: Local and small installations must run without MongoDB; one switch keeps the opt-out a single line.
    rejected_alternatives:
      - Keep DocumentDB as the default and make Redis opt-in.
      - Auto-detect the backend from DOCUMENTDB_HOSTNAME.
      - Only warn when a DocumentDB installation silently defaults to Redis.
      - Keep CREW_RESULT_STORAGE defaulting to documentdb independently of the global switch.
  - id: vault-access-through-vault-utils
    statement: Every read or write of user_credentials goes through parrot.security.vault_utils; handlers never open DocumentDB for it directly.
    relation: requires
    about: [server]
    targets:
      - sym:packages/ai-parrot-server/src/parrot/handlers/credentials.py#CredentialsHandler
      - sym:packages/ai-parrot/src/parrot/security/vault_utils.py#store_vault_credential
    contradicts: []
    supersedes: []
    rationale: The direct DocumentDB reads in CredentialsHandler and the MCP restore ignore VAULT_STORE and split credentials across stores.
    rejected_alternatives:
      - Add a Redis branch inside CredentialsHandler beside the DocumentDB code.
  - id: redis-documents-mirror-documentdb
    statement: A Redis user-store document mirrors the DocumentDB document of the same collection field for field, without _id, with sealed values unchanged.
    relation: constrains
    about: [config]
    targets:
      - sym:packages/ai-parrot/src/parrot/vault_targets.py#DocumentDbTarget
    contradicts: []
    supersedes: []
    rationale: Keeps the copy verbatim, the AAD contexts valid and the rotation target logic shared.
    rejected_alternatives:
      - A Redis-specific normalised schema per collection.
```

## Decision Waivers

## Consequences

<!-- decision-audit: input_digest=sha256:42f6d1a0bdd44f3fb52b7b602f1e4421134c886c5020ec83c91af28787d09671 evaluation_digest=sha256:2f2d4f51f2fc6e2ec9411244a2a4db4b2c75a5aa6b1e51ee529888092da41d88 rules_version=1 status=pass -->

Audit status: `pass` (exit 0)

Findings:
- `blast-radius` [advisory]; waived_by: not recorded; participants: adr:spec:redis-user-stores#vault-access-through-vault-utils@1; scope: sym:packages/ai-parrot/src/parrot/security/vault_utils.py#store_vault_credential; message: sym:packages/ai-parrot/src/parrot/security/vault_utils.py#store_vault_credential impacts 26 dependent(s): sym:packages/ai-parrot-integrations/src/parrot/integrations/telegram/mcp_commands.py#add_mcp_handler, sym:packages/ai-parrot-integrations/tests/integrations/telegram/test_mcp_commands.py#TestAddMcpHandler.test_add_mcp_happy_path, sym:packages/ai-parrot-integrations/tests/integrations/telegram/test_mcp_commands.py#TestAddMcpHandler.test_add_mcp_no_auth_scheme_none, sym:packages/ai-parrot-integrations/tests/integrations/telegram/test_mcp_commands.py#TestAddMcpHandler.test_add_mcp_rolls_back_on_tool_manager_failure, sym:packages/ai-parrot-integrations/tests/integrations/telegram/test_mcp_commands.py#TestAddMcpHandler.test_add_mcp_rolls_back_on_vault_failure, sym:packages/ai-parrot-integrations/tests/integrations/telegram/test_mcp_commands.py#TestAddMcpHandler.test_non_private_chat_rejected, sym:packages/ai-parrot-integrations/tests/integrations/telegram/test_mcp_commands.py#TestEndToEnd.test_end_to_end_add_list_remove, sym:packages/ai-parrot-integrations/tests/integrations/telegram/test_mcp_commands.py#TestRedisNotUsed.test_vault_is_used_not_redis, sym:packages/ai-parrot-integrations/tests/integrations/telegram/test_mcp_documentdb_gate.py#TestHandlersWhenDisabled.test_add_mcp_session_only, sym:packages/ai-parrot-server/src/parrot/handlers/mcp_helper.py#MCPHelperHandler.post, sym:packages/ai-parrot-server/src/parrot/handlers/studio/storage/services/tooling.py#StudioToolingService.put_mcp_servers, sym:packages/ai-parrot-server/src/parrot/handlers/studio/storage/services/tooling.py#StudioToolingService.put_toolkit, sym:packages/ai-parrot-server/src/parrot/handlers/studio/tooling_store.py#AgentToolingStore._split_secrets, sym:packages/ai-parrot-server/src/parrot/handlers/studio/tooling_store.py#AgentToolingStore.put_mcp_servers, sym:packages/ai-parrot-server/src/parrot/handlers/studio/tooling_store.py#AgentToolingStore.put_toolkit, sym:packages/ai-parrot-server/src/parrot/handlers/studio/tooling_store.py#flush_vault_writes, sym:packages/ai-parrot-server/src/parrot/handlers/studio/toolkit_overrides.py#StudioUserToolkitOverrideHandler.put, sym:packages/ai-parrot-server/tests/studio/storage/test_vault_store.py#test_startup_registers_store_only_when_switch_is_postgres, sym:packages/ai-parrot-server/tests/studio/storage/test_vault_store.py#test_vault_pg_roundtrip, sym:packages/ai-parrot-server/tests/studio/test_tooling_db_mode.py#_configure, sym:packages/ai-parrot-server/tests/studio/test_tooling_db_mode.py#test_cross_tenant_tooling_identity, sym:packages/ai-parrot-server/tests/studio/test_tooling_db_mode.py#test_legacy_source_tooling_refuses_expected_version, sym:packages/ai-parrot-server/tests/studio/test_tooling_db_mode.py#test_overrides_expected_version_unsupported, sym:packages/ai-parrot-server/tests/studio/test_tooling_db_mode.py#test_persist_responses_carry_the_agent_version, sym:packages/ai-parrot-server/tests/studio/test_tooling_db_mode.py#test_stale_tooling_writes, sym:packages/ai-parrot-server/tests/studio/test_tooling_db_mode.py#test_tooling_policy_http
- `blast-radius` [advisory]; waived_by: not recorded; participants: adr:spec:redis-user-stores#redis-default-user-stores@1; scope: sym:packages/ai-parrot-server/src/parrot/handlers/studio/storage/backend.py#_postgres_switches; message: sym:packages/ai-parrot-server/src/parrot/handlers/studio/storage/backend.py#_postgres_switches impacts 3 dependent(s): sym:packages/ai-parrot-server/src/parrot/handlers/studio/storage/backend.py#_fail_closed, sym:packages/ai-parrot-server/src/parrot/handlers/studio/storage/backend.py#_register_postgres_stores, sym:packages/ai-parrot-server/src/parrot/handlers/studio/storage/backend.py#ensure_studio_storage
- `blast-radius` [advisory]; waived_by: not recorded; participants: adr:spec:redis-user-stores#redis-default-user-stores@1; scope: sym:packages/ai-parrot/src/parrot/auth/broker/__init__.py#byok_store_setting; message: sym:packages/ai-parrot/src/parrot/auth/broker/__init__.py#byok_store_setting impacts 7 dependent(s): sym:packages/ai-parrot-server/src/parrot/handlers/studio/byok.py#StudioKeysHandler._list_keys, sym:packages/ai-parrot-server/src/parrot/handlers/studio/byok.py#StudioKeysHandler._persist_key, sym:packages/ai-parrot-server/src/parrot/handlers/studio/byok.py#StudioKeysHandler._remove_key, sym:packages/ai-parrot-server/src/parrot/handlers/studio/byok.py#StudioKeysHandler.delete, sym:packages/ai-parrot-server/src/parrot/handlers/studio/byok.py#StudioKeysHandler.get, sym:packages/ai-parrot-server/src/parrot/handlers/studio/byok.py#StudioKeysHandler.post, sym:packages/ai-parrot-server/src/parrot/handlers/studio/key_source.py#user_byok_providers; inferred: sym:packages/ai-parrot-server/src/parrot/handlers/studio/catalog.py#StudioCatalogHandler._llm_clients_for_caller, sym:packages/ai-parrot/src/parrot/auth/broker/byok.py#_UserLLMKeyResolver.resolve
- `blast-radius` [advisory]; waived_by: not recorded; participants: adr:spec:redis-user-stores#redis-documents-mirror-documentdb@1; scope: sym:packages/ai-parrot/src/parrot/vault_targets.py#DocumentDbTarget; message: sym:packages/ai-parrot/src/parrot/vault_targets.py#DocumentDbTarget impacts 4 dependent(s): sym:packages/ai-parrot/src/parrot/vault_targets.py#UserCredentialsTarget, sym:packages/ai-parrot/src/parrot/vault_targets.py#UserLlmKeysTarget, sym:packages/ai-parrot/tests/security/test_vault_targets.py#credentials_target, sym:packages/ai-parrot/tests/security/test_vault_targets.py#llm_keys_target

Diagnostics:
- none

Coverage:
- Subsystems: auth, bots, clients, config, flows, integrations, knowledge-graphindex, knowledge-pageindex, knowledge-wiki, memory, server, skills, tools
- Unmapped tags: credentials, local-dev, redis, storage, vault
- Targets resolved: 5/5
- Impact complete: true
- Inventory complete: true
- Omitted ids: not recorded

```json
{
  "coverage": {
    "impact_complete": true,
    "inventory_complete": true,
    "omitted_ids": [],
    "subsystems": [
      "auth",
      "bots",
      "clients",
      "config",
      "flows",
      "integrations",
      "knowledge-graphindex",
      "knowledge-pageindex",
      "knowledge-wiki",
      "memory",
      "server",
      "skills",
      "tools"
    ],
    "targets_resolved": 5,
    "targets_total": 5,
    "unmapped_tags": [
      "credentials",
      "local-dev",
      "redis",
      "storage",
      "vault"
    ]
  },
  "diagnostics": [],
  "evaluation_digest": "sha256:2f2d4f51f2fc6e2ec9411244a2a4db4b2c75a5aa6b1e51ee529888092da41d88",
  "exit_code": 0,
  "findings": [
    {
      "blocking": false,
      "fingerprint": "sha256:022ec26a1a8b8d827c7de799951ff1a5f478e3e0096234f88ede5720ef61e8fe",
      "kind": "blast-radius",
      "message": "sym:packages/ai-parrot/src/parrot/security/vault_utils.py#store_vault_credential impacts 26 dependent(s): sym:packages/ai-parrot-integrations/src/parrot/integrations/telegram/mcp_commands.py#add_mcp_handler, sym:packages/ai-parrot-integrations/tests/integrations/telegram/test_mcp_commands.py#TestAddMcpHandler.test_add_mcp_happy_path, sym:packages/ai-parrot-integrations/tests/integrations/telegram/test_mcp_commands.py#TestAddMcpHandler.test_add_mcp_no_auth_scheme_none, sym:packages/ai-parrot-integrations/tests/integrations/telegram/test_mcp_commands.py#TestAddMcpHandler.test_add_mcp_rolls_back_on_tool_manager_failure, sym:packages/ai-parrot-integrations/tests/integrations/telegram/test_mcp_commands.py#TestAddMcpHandler.test_add_mcp_rolls_back_on_vault_failure, sym:packages/ai-parrot-integrations/tests/integrations/telegram/test_mcp_commands.py#TestAddMcpHandler.test_non_private_chat_rejected, sym:packages/ai-parrot-integrations/tests/integrations/telegram/test_mcp_commands.py#TestEndToEnd.test_end_to_end_add_list_remove, sym:packages/ai-parrot-integrations/tests/integrations/telegram/test_mcp_commands.py#TestRedisNotUsed.test_vault_is_used_not_redis, sym:packages/ai-parrot-integrations/tests/integrations/telegram/test_mcp_documentdb_gate.py#TestHandlersWhenDisabled.test_add_mcp_session_only, sym:packages/ai-parrot-server/src/parrot/handlers/mcp_helper.py#MCPHelperHandler.post, sym:packages/ai-parrot-server/src/parrot/handlers/studio/storage/services/tooling.py#StudioToolingService.put_mcp_servers, sym:packages/ai-parrot-server/src/parrot/handlers/studio/storage/services/tooling.py#StudioToolingService.put_toolkit, sym:packages/ai-parrot-server/src/parrot/handlers/studio/tooling_store.py#AgentToolingStore._split_secrets, sym:packages/ai-parrot-server/src/parrot/handlers/studio/tooling_store.py#AgentToolingStore.put_mcp_servers, sym:packages/ai-parrot-server/src/parrot/handlers/studio/tooling_store.py#AgentToolingStore.put_toolkit, sym:packages/ai-parrot-server/src/parrot/handlers/studio/tooling_store.py#flush_vault_writes, sym:packages/ai-parrot-server/src/parrot/handlers/studio/toolkit_overrides.py#StudioUserToolkitOverrideHandler.put, sym:packages/ai-parrot-server/tests/studio/storage/test_vault_store.py#test_startup_registers_store_only_when_switch_is_postgres, sym:packages/ai-parrot-server/tests/studio/storage/test_vault_store.py#test_vault_pg_roundtrip, sym:packages/ai-parrot-server/tests/studio/test_tooling_db_mode.py#_configure, sym:packages/ai-parrot-server/tests/studio/test_tooling_db_mode.py#test_cross_tenant_tooling_identity, sym:packages/ai-parrot-server/tests/studio/test_tooling_db_mode.py#test_legacy_source_tooling_refuses_expected_version, sym:packages/ai-parrot-server/tests/studio/test_tooling_db_mode.py#test_overrides_expected_version_unsupported, sym:packages/ai-parrot-server/tests/studio/test_tooling_db_mode.py#test_persist_responses_carry_the_agent_version, sym:packages/ai-parrot-server/tests/studio/test_tooling_db_mode.py#test_stale_tooling_writes, sym:packages/ai-parrot-server/tests/studio/test_tooling_db_mode.py#test_tooling_policy_http",
      "participants": [
        {
          "decision_id": "adr:spec:redis-user-stores#vault-access-through-vault-utils",
          "revision": 1
        }
      ],
      "rule_version": 1,
      "scope": [
        "sym:packages/ai-parrot/src/parrot/security/vault_utils.py#store_vault_credential"
      ],
      "waived_by": null
    },
    {
      "blocking": false,
      "fingerprint": "sha256:500d486d878ed8dd99bcc565f19e915d6a6f2ef2ef0179d52f6f5cded544995a",
      "kind": "blast-radius",
      "message": "sym:packages/ai-parrot-server/src/parrot/handlers/studio/storage/backend.py#_postgres_switches impacts 3 dependent(s): sym:packages/ai-parrot-server/src/parrot/handlers/studio/storage/backend.py#_fail_closed, sym:packages/ai-parrot-server/src/parrot/handlers/studio/storage/backend.py#_register_postgres_stores, sym:packages/ai-parrot-server/src/parrot/handlers/studio/storage/backend.py#ensure_studio_storage",
      "participants": [
        {
          "decision_id": "adr:spec:redis-user-stores#redis-default-user-stores",
          "revision": 1
        }
      ],
      "rule_version": 1,
      "scope": [
        "sym:packages/ai-parrot-server/src/parrot/handlers/studio/storage/backend.py#_postgres_switches"
      ],
      "waived_by": null
    },
    {
      "blocking": false,
      "fingerprint": "sha256:5cf3cec3bd4a2024d9680bb4704c3d81b6eecf06e590e160f6344cb87d0cd469",
      "kind": "blast-radius",
      "message": "sym:packages/ai-parrot/src/parrot/auth/broker/__init__.py#byok_store_setting impacts 7 dependent(s): sym:packages/ai-parrot-server/src/parrot/handlers/studio/byok.py#StudioKeysHandler._list_keys, sym:packages/ai-parrot-server/src/parrot/handlers/studio/byok.py#StudioKeysHandler._persist_key, sym:packages/ai-parrot-server/src/parrot/handlers/studio/byok.py#StudioKeysHandler._remove_key, sym:packages/ai-parrot-server/src/parrot/handlers/studio/byok.py#StudioKeysHandler.delete, sym:packages/ai-parrot-server/src/parrot/handlers/studio/byok.py#StudioKeysHandler.get, sym:packages/ai-parrot-server/src/parrot/handlers/studio/byok.py#StudioKeysHandler.post, sym:packages/ai-parrot-server/src/parrot/handlers/studio/key_source.py#user_byok_providers; inferred: sym:packages/ai-parrot-server/src/parrot/handlers/studio/catalog.py#StudioCatalogHandler._llm_clients_for_caller, sym:packages/ai-parrot/src/parrot/auth/broker/byok.py#_UserLLMKeyResolver.resolve",
      "participants": [
        {
          "decision_id": "adr:spec:redis-user-stores#redis-default-user-stores",
          "revision": 1
        }
      ],
      "rule_version": 1,
      "scope": [
        "sym:packages/ai-parrot/src/parrot/auth/broker/__init__.py#byok_store_setting"
      ],
      "waived_by": null
    },
    {
      "blocking": false,
      "fingerprint": "sha256:e4c6a0b6d21f6831e9d7e5ed084e13c9113efa2bbbbd638101d3c2a6e4f26e4e",
      "kind": "blast-radius",
      "message": "sym:packages/ai-parrot/src/parrot/vault_targets.py#DocumentDbTarget impacts 4 dependent(s): sym:packages/ai-parrot/src/parrot/vault_targets.py#UserCredentialsTarget, sym:packages/ai-parrot/src/parrot/vault_targets.py#UserLlmKeysTarget, sym:packages/ai-parrot/tests/security/test_vault_targets.py#credentials_target, sym:packages/ai-parrot/tests/security/test_vault_targets.py#llm_keys_target",
      "participants": [
        {
          "decision_id": "adr:spec:redis-user-stores#redis-documents-mirror-documentdb",
          "revision": 1
        }
      ],
      "rule_version": 1,
      "scope": [
        "sym:packages/ai-parrot/src/parrot/vault_targets.py#DocumentDbTarget"
      ],
      "waived_by": null
    }
  ],
  "input_digest": "sha256:42f6d1a0bdd44f3fb52b7b602f1e4421134c886c5020ec83c91af28787d09671",
  "snapshot": {
    "approvals_digest": "6e5b5a5fb07d04ec7e7cdbf3afac1a634711ea195aa4061a8261bcf61b19992f",
    "config_digest": "sha256:a6bce9c0800713c30eaa78146ad0c06399f6ec0e9b083129e494abb6fd073343",
    "inventory": {
      "adr:doc:171b17ccd26bdbd2d71040746b22371a335d364d": "b22c79daae2a187f2091ea23449825e8769e2c07",
      "adr:doc:34394c36f5bf140678b8e17d43c3628e3d2c1440": "3fa15352d0e9ed972bd5de7ac1fd60e06906e60b",
      "adr:doc:666d8f740c695673063f76777db7b7b0e9d95a2e": "47f1bebe56724843f6c0981f67bbba72917b4b0b",
      "adr:doc:87781d348dff80cbfb25c253989a8940badd08d1": "49458f64f4bb614a9ff42750b53d9caa806f81a0",
      "adr:doc:89e808b78adee5c727e047ac239817bfd29e5cfe": "9feeb90ec52cb53395d978a3b946323a7b9072ab",
      "adr:doc:96dabb33251cd210186d7ab5c456ded102a4b025": "b537050f62f77a85b651af8c2595f4dc7fd4cebe",
      "adr:doc:c3c29b415ba46e730ee37c6fc520914a1905d022": "0cd9cc9f082b9d988da023e3886d310f8eed8eae",
      "adr:doc:c6b0e17a26d4b1ae2be8569a33db9a3aeedc0fbd": "804496ec336c99570df5502580ff980a38f56bfc",
      "adr:doc:e7c5ae770b06db3b35cdd4cba93001a58bfa7bef": "394f4656c71618a256427d81350fdc32335fa791"
    },
    "rules_version": 1,
    "structural_revision": "sha256:902eddc2757edbcadf8b7d3418479fd71f2fcdaf0470b2a01c856ab7c6caceb0",
    "taxonomy_digest": "65548b9a71329b13ab44f4904dff99814e1aac0da4bb2b58171a7201e3a9ba39"
  },
  "status": "pass"
}
```

## 8. Open Questions

- [x] How is Redis mode switched on? — *Resolved with the user 2026-11-11*: a global `PARROT_USER_STORE` plus per-store switches that override it.
- [x] Default when nothing is configured? — *Resolved with the user 2026-11-11*: Redis; production must declare DocumentDB (or Postgres) explicitly.
- [x] Scope beyond the five collections? — *Resolved with the user 2026-11-11*: include BYOK `user_llm_keys`, dashboards, a DocumentDB → Redis copy script and Redis keyring rotation.
- [x] Q1: Should startup fail (instead of warn) when a store defaults to Redis while DocumentDB is configured? — *Resolved with the user 2026-11-11*: fail, with an error listing the stores and both fixes (`PARROT_USER_STORE=documentdb` / `=redis`); only when `DOCUMENTDB_HOSTNAME` or `DOCUMENTDB_DBNAME` is set. See §2 Startup, M1, AC17.
- [x] Q2: Should `CREW_RESULT_STORAGE` follow `PARROT_USER_STORE`? — *Resolved with the user 2026-11-11*: yes, when `CREW_RESULT_STORAGE` is unset (new M14, AC18); explicit values win.
- [x] Q3: Dedicated logical DB or `REDIS_URL` + prefix? — *Resolved with the user 2026-11-11*: dedicated logical DB 6; DB-0-only deployments (Redis Cluster) set `PARROT_USER_STORE_REDIS_URL`.

---

## Worktree Strategy

- **Isolation**: one feature worktree (`feat-FEAT-878-redis-user-stores`); the `sdd-coder` engine gives each task its own sub-worktree.
- **Module dependency graph** (evidence = the import named):
  - M2 → M1 (`redis_url`, `key_prefix`, `get_user_store_redis`).
  - M3, M5, M6, M7, M8, M9, M10 → M1 + M2 (`resolve_store_backend`, `RedisDocumentStore`, collection specs).
  - M4 → M3 (`list_vault_credentials`, `vault_credential_exists`, `VaultCredentialStore`).
  - M11 → M1 + M2 (`validate_user_store_settings`, `get_user_store_redis`).
  - M12 → M2 (`RedisDocumentStore`, `USER_STORE_COLLECTIONS`).
  - M13 → M2 (`RedisDocumentStore`).
  - M14 → M1 (`default_result_storage`).
  - After M1 (M14) and M1+M2 (the rest), the modules M3, M5–M14 have no edges between them and run
    concurrently; M4 follows M3.
- **Shared files**: none between modules (each module owns its files). `vault_utils.py` is M3 only;
  `studio/byok.py` M6 only; `manager.py` and `backend.py` M11 only; `conf.py` and the result-storage
  `factory.py` M14 only.
- **Exclusive resources**: M13 edits `packages/ai-parrot/pyproject.toml` (entry points; metadata
  reinstall) → `parallel: false`.
- **Cross-feature dependencies**: none. FEAT-621 (agentstudio-db-storage) is merged; its Postgres
  stores are extended, not replaced.

---

## 9. Design Research Cross-Check

> Model: — · Status: skipped (no accepted exploration document — spec written from a direct request
> and an in-session design interview) · Transcript: —

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|

Summary: **0** confirmed · **0** rejected · **0** escalated.

---

## 10. Documentation

- **Policy**: `required`
- **Pages**:
  - `wiki/stores/user-stores.md` — create: switches and precedence, Redis layout and db 6 (Cluster: set the URL), durability requirements (no eviction, persistence on), the implicit-default startup guard and its two fixes, startup warnings, copy CLI, rotation targets, upgrade checklist for production (`PARROT_USER_STORE=documentdb`).
  - `wiki/bots/orchestration/crew-definition-storage.md` — update: an unset `CREW_RESULT_STORAGE` now follows `PARROT_USER_STORE` (Redis by default, 7-day TTL).
  - `wiki/bots/agentstudio/db-storage.md` — update: phase-2 switches accept `redis`; default is now Redis via `PARROT_USER_STORE`; `postgres` without registration fails closed for the vault too.
  - `wiki/stores/documentdb_interface.md` — update: DocumentDB is no longer the default for user stores; link to `user-stores.md`.
- **API modules**:
  - `parrot.userstore`
  - `parrot.security.vault_utils`

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-11-11 | Jesus Lara | Initial draft (design decisions from the 2026-11-11 interview) |
| 0.2 | 2026-11-11 | Jesus Lara | Approved; §8 Q1–Q3 left open (spec defaults apply: warn, CREW_RESULT_STORAGE independent, Redis db 6) |
| 0.3 | 2026-11-11 | Jesus Lara | Resolved §8 Q1–Q3: implicit Redis default on a DocumentDB install fails startup; unset CREW_RESULT_STORAGE follows PARROT_USER_STORE (M14); dedicated Redis db 6 |
| 0.4 | 2026-11-11 | Jesus Lara | /sdd-task: Validation Contract extended with the regression suites and new test files the tasks run |
