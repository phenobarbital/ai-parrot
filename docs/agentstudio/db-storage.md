# Agent Studio — database storage (host guide)

Agent Studio can keep its agents, drafts, assets, tooling and skills catalog in PostgreSQL (schema `navigator`) instead
of the `AGENTS_DIR` file tree, and — as the second phase of the same release — keep per-user BYOK keys, vault
credentials and per-user toolkit overrides there too instead of DocumentDB. This page is for the host that mounts the
Studio routes. The HTTP contract is in [`docs/agent_studio_api.md`](../agent_studio_api.md); every response-shape change
of database mode is additive (nothing is removed or renamed) and filesystem mode is unchanged.

Spec: `sdd/specs/agentstudio-db-storage.spec.md` (FEAT-621).

## Settings

All keys are read through `navconfig` (environment variables or the host's `env/` files).

### Storage backend and runtime

| Key | Default | Effect |
|---|---|---|
| `PARROT_STUDIO_STORAGE` | `auto` | `auto`: database when a pool exists and the schema is migrated, else the filesystem backend (logged). `database`: database or `unavailable` (every Studio request then answers 503 `studio_storage_unavailable`). `filesystem`: always the legacy layout. Any other value is logged and treated as `auto`. |
| `STUDIO_RUNTIME_DIR` | `<tempdir>/parrot-studio-<pid>` | Where versioned asset directories of Studio agents are materialised. Must not be under `AGENTS_DIR`. |
| `STUDIO_PYTHON_DRAFTS` | `true` | Allow legacy Python (`source`) drafts in the global partition. Tenant partitions are always declarative-only (422 `declarative_only`). |
| `STUDIO_REVALIDATE_TTL_SECONDS` | `0` | How long a cached agent version is trusted before the stored version is re-read. `0` re-validates on every lookup (a write on one pod applies on the next lookup of every pod). |
| `STUDIO_SESSION_TTL_SECONDS` | `3600` | Lifetime of a per-session agent instance. |
| `STUDIO_IDLE_TTL_SECONDS` | `3600` | An instance unused for this long is reclaimable. |
| `STUDIO_RETIRE_GRACE_SECONDS` | `300` | Grace period before a superseded version's instance and asset directory are removed. |
| `STUDIO_SWEEP_INTERVAL_SECONDS` | `60` | Period of the expiry sweep. |
| `STUDIO_ASSET_MAX_BYTES_IDENTITY` | `65536` | Per-file cap for `identity` assets (413 `asset_too_large`). |
| `STUDIO_ASSET_MAX_BYTES_KB` | `262144` | Per-file cap for `kb` assets. |
| `STUDIO_ASSET_MAX_BYTES_SKILLS` | `131072` | Per-file cap for `skills` assets. |
| `STUDIO_AGENT_MAX_ASSET_BYTES` | `4194304` | Total asset bytes per agent (413 `agent_assets_quota`). |

### Phase 2 — secrets stores (default: DocumentDB, unchanged behaviour)

| Key | Default | Values | Moves to PostgreSQL |
|---|---|---|---|
| `BYOK_STORE` | `documentdb` | `documentdb` \| `postgres` | per-user LLM keys (`user_llm_keys`) -> `navigator.ai_user_llm_keys` (migration 0006) |
| `VAULT_STORE` | `documentdb` | `documentdb` \| `postgres` | vault credentials (`user_credentials`: agent toolkit/MCP secrets, per-user override secrets) -> `navigator.ai_user_credentials` (migration 0007) |
| `TOOLKIT_OVERRIDES_STORE` | `documentdb` | `documentdb` \| `postgres` | per-user toolkit overrides (`user_toolkit_configs`) -> `navigator.ai_user_toolkit_overrides` (migration 0008) |

Each switch is independent. Ciphertexts keep the same format and the same AAD contexts in both stores, so a value
sealed for DocumentDB opens unchanged from PostgreSQL (this is what makes the copy script a verbatim copy).

A `postgres` value requires the Studio backend to resolve to `database`. Otherwise startup **fails** with an error
naming the switch and the reason (fail closed: a store never silently stays on DocumentDB). The Postgres stores are
registered in `ensure_studio_storage`, run by the `on_startup` resolve hook that `BotManager.setup()`,
`setup_registry_only()` and `setup_studio_routes()` all install, so registration does not depend on Studio routes being
mounted or on any `/keys` call. An `on_cleanup` hook clears the process-global registrations again.

Keyring provisioning stays the host's job and is unchanged: `VAULT_MASTER_KEY_v{N}` and `VAULT_ACTIVE_KEY_ID` in the
pod environment. Without a keyring, `/keys` and secret writes answer 503 `vault_unavailable`.

**Required schema version.** `STUDIO_SCHEMA_REQUIRED = 8` (migrations 0001-0008) whenever the Studio backend is
`database`, regardless of the phase-2 switches (phase 2 is part of the release). The constant lives in
`parrot.handlers.studio.storage.migrate` and equals `required` of `MANIFEST.json`. The startup probe requires every
version up to 8 to be in the ledger with the manifest checksum; a database still at version 5 resolves to `unavailable`
(503). Apply 0006-0008 first.

## Supported PostgreSQL

PostgreSQL 14 or later (tested on 14 and 16). The startup probe and the migration CLI both refuse an older server with
a clear message (`server_version_num < 140000`). The schema name is the literal `navigator`; every statement is
schema-qualified, so `search_path` / `PARROT_SCHEMA` cannot redirect it. The pool is the host's `app["database"]`
(asyncdb `pg`); Studio opens no second pool.

## Migrations

**Studio never changes the schema at startup.** `setup()` and `on_startup` only run a read-only probe (server version,
ledger table, applied versions and checksums). Migrations are applied by the operator, once per database, before the
deploy that needs them. No module outside `storage/migrate.py` references `apply_studio_migrations`
(`test_storage_gates.py`), and no DDL exists outside `storage/migrations/*.sql`.

### Files

The files ship as package data in `parrot/handlers/studio/storage/migrations/`:

| Version | File | Creates | Phase |
|---|---|---|---|
| 1 | `0001_studio_migrations_ledger.sql` | `navigator.ai_studio_migrations` (the ledger) | 1 |
| 2 | `0002_ai_agents.sql` | `ai_agents`, `ai_agent_assets`, `ai_agent_tooling` | 1 |
| 3 | `0003_ai_agent_drafts.sql` | `ai_agent_drafts` (declarative bundle drafts) | 1 |
| 4 | `0004_ai_skills_catalog_tenancy.sql` | `ai_skills_catalog` (created if missing) plus tenancy columns and per-tenant name uniqueness | 1 |
| 5 | `0005_studio_drafts_baseline.sql` | `studio_drafts` (legacy Python drafts, create-if-missing) | 1 |
| 6 | `0006_ai_user_llm_keys.sql` | `navigator.ai_user_llm_keys` | 2 (`BYOK_STORE`) |
| 7 | `0007_ai_user_credentials.sql` | `navigator.ai_user_credentials` | 2 (`VAULT_STORE`) |
| 8 | `0008_ai_user_toolkit_overrides.sql` | `navigator.ai_user_toolkit_overrides` | 2 (`TOOLKIT_OVERRIDES_STORE`) |

Format of one file:

- **Body**: idempotent DDL (`CREATE ... IF NOT EXISTS`), beginning with
  `SELECT pg_advisory_xact_lock(4715391001);` so two runners serialise.
- **Marker**: a line that is exactly `-- @studio-ledger`.
- **Trailer**: after the marker, one `INSERT INTO navigator.ai_studio_migrations (version, name, checksum) ...
  ON CONFLICT (version) DO NOTHING;` that records the file.
- **Checksum**: sha256 of the body (every byte up to and including the line feed before the marker). The trailer is not
  hashed. `MANIFEST.json` lists `version`, `name` and `sha256` for every file plus `required`;
  loading fails if the files, the manifest and the trailers disagree.

Versions must be contiguous from 1. Every file records itself through its own trailer, so the ledger looks the same
whichever runner applied it. The file must run **inside one transaction**: the advisory lock is transaction-scoped, and
in autocommit it would be released immediately.

### Plain host: `parrot-studio-migrate`

```bash
parrot-studio-migrate --dsn "$DSN" --dry-run     # list pending versions, change nothing
parrot-studio-migrate --dsn "$DSN"               # apply every pending file, one transaction each
parrot-studio-migrate --dsn "$DSN" --verify      # report missing / drifted / unknown versions; exit 1 on any
parrot-studio-migrate --dsn "$DSN" --print       # emit the pending files (body + trailer) for review
parrot-studio-migrate --stamp                    # release tooling, repository checkout only: rewrite trailers + MANIFEST
```

- Applying runs **all** pending files, 0001-0008. The phase-2 tables are inert until a store switch is flipped.
- `--print` pipes straight into `psql`: `parrot-studio-migrate --dsn "$DSN" --print | psql -1 -v ON_ERROR_STOP=1 "$DSN"`
  (`-1` is what makes each file one transaction; do not drop it).
- `--verify` checks versions 1-8 against the manifest and flags any missing version, any recorded version that is
  unknown and any checksum that drifted. After applying phase 2, confirm with `--dry-run` that nothing is
  pending (`pending: []`).
- A host deploy hook can call `await apply_studio_migrations(pool)` from `parrot.handlers.studio.storage.migrate`
  (also `dry_run=True`). It must never be called from `setup()` or an `on_startup` hook.

### FieldSync (or any host runner)

A host that owns its own migration runner applies the same files as-is: read them with `importlib.resources` from the
pinned `ai-parrot-server` wheel, or vendor them byte-for-byte into the host's migration tree under the host's own
numbers. Each file must be executed in one transaction, raw bytes, body then trailer. Because each file records itself,
parrot's probe sees the same ledger with the same checksums whichever runner applied it; never edit a file after
vendoring (the checksum would drift and the probe would resolve `unavailable`). The phase-2 files 0006-0008 follow the
same rule: vendor them together with 0001-0005: the probe requires all of 0001-0008.

## Moving existing secrets: `secrets_copy`

Switching a store to `postgres` does not move data. Existing BYOK keys, vault credentials and per-user overrides are
copied from DocumentDB with a one-shot script. The DSN is read from the environment (`STUDIO_PG_DSN`), never from argv,
because argv shows up in process listings; `--dsn` is rejected.

```bash
export STUDIO_PG_DSN="postgresql://..."
python -m parrot.handlers.studio.storage.secrets_copy --dry-run
python -m parrot.handlers.studio.storage.secrets_copy
python -m parrot.handlers.studio.storage.secrets_copy --byok --vault
python -m parrot.handlers.studio.storage.secrets_copy --overwrite     # explicit, see below
```

| Flag / env | Meaning |
|---|---|
| `STUDIO_PG_DSN` | required env var; PostgreSQL DSN of the Studio database (never logged) |
| `--dry-run` | writes nothing, but opens every BYOK key and vault credential with the keyring, so it reports the same `failed` count a real run would |
| `--overwrite` | also update rows that already exist in Postgres, but only when the source `updated_at` is strictly newer |
| `--byok` | copy `user_llm_keys` -> `ai_user_llm_keys` |
| `--vault` | copy `user_credentials` -> `ai_user_credentials` |
| `--overrides` | copy `user_toolkit_configs` -> `ai_user_toolkit_overrides` |

With none of `--byok`, `--vault`, `--overrides` all three are copied. The script reads DocumentDB through the host's
normal DocumentDB configuration and prints `would copy: {...}` / `copied: {...}` with counts per collection, `skipped`
and `failed`; the exit code is 1 when any document failed. Documents it cannot copy are skipped and logged by identity
and exception class only; no value, ciphertext or DSN is ever logged.

Requirements and behaviour:

- **Insert-only by default**: a row that already exists in Postgres is never touched (`ON CONFLICT DO NOTHING`) and is
  counted as `skipped`. After cutover Postgres is the source of truth and users edit keys, credentials and overrides
  there, so running the script again is a no-op: it cannot overwrite newer Postgres data.
- **`--overwrite` is newer-wins**: an existing row is replaced only when the source document's `updated_at` is strictly
  newer than the row's (equal or older sources, and sources without `updated_at`, leave it untouched). Ciphertexts and
  timestamps are still copied verbatim.
- **Order of operations**: apply migrations 0006-0008 -> run `secrets_copy` (use `--dry-run` first) -> only then flip the
  `BYOK_STORE` / `VAULT_STORE` / `TOOLKIT_OVERRIDES_STORE` switch and roll the pods. Run the copy BEFORE flipping a
  switch; a re-run after the flip is a no-op unless `--overwrite` is given. The probe will not accept the Studio backend
  switch before the schema is at version 8.
- **Keyring**: `--byok` and `--vault` need the vault keyring in the environment (`VAULT_MASTER_KEY_v{N}`,
  `VAULT_ACTIVE_KEY_ID`) in a real run AND in `--dry-run`, because each key / credential is opened once, read-only (BYOK
  also to derive its `masked` preview). Run it with the same keyring the pods use. When the keyring is missing the script
  logs one clear error and counts every BYOK / vault document as `failed` (no traceback); a document that cannot be
  opened (wrong keyring, wrong AAD context, malformed) is counted `failed` and not copied. `--overrides` needs no keyring.
- **Ciphertexts are copied verbatim**: they are not re-sealed, so they keep their original keyring `key_id` and AAD
  context and stay decryptable by the same keyring.
- **Snapshot, not sync**: anything written to DocumentDB after the copy is not carried over and deletions are not
  propagated. Before the flip, run the copy again (new documents are inserted; documents edited in DocumentDB since the first run need `--overwrite`) or freeze secret writes during the window.

### Vault rotation targets

`navigator-vault` rotation and migration must cover the new tables, otherwise a keyring rotation would skip them. The
`ai-parrot-server` distribution registers two `navigator_session.vault_targets` entry points (next to the existing
`parrot_users_bots`):

| Entry point | Target name | Table / sealed column |
|---|---|---|
| `parrot_studio_user_credentials` | `pg:ai_user_credentials` | `navigator.ai_user_credentials.credential` |
| `parrot_studio_user_llm_keys` | `pg:ai_user_llm_keys` | `navigator.ai_user_llm_keys.api_key_enc` (+ `key_id`) |

Both targets need the PostgreSQL pool (`parrot_db_pool` or `db_pool` in the resources the CLI is given); without it
the factory returns nothing and the table is not rotated. They use the same AAD contexts as the DocumentDB targets in
core (`parrot_user_credentials`, `parrot_user_llm_keys`), which keep covering DocumentDB while a switch is still
`documentdb`. The tables have no lifecycle column, so a quarantined row is renamed (`<name>#quarantined:<run_id>`):
its blob is untouched, runtime reads no longer find it, iteration skips it and `restore_raw` puts the original key
back. `ai_user_toolkit_overrides` holds no ciphertext (only vault references), so it is not a rotation target.

## Lifecycle and mount order

Hooks (each appended at most once per app, whatever the number of prefixes or calls):

| Hook | Registered by | Phase | What it does |
|---|---|---|---|
| `resolve_studio_storage` | `setup_studio_routes` | `on_startup` | Runs `ensure_studio_storage(app)`: the read-only probe, memoised on `app["studio_storage"]` (`StudioStorage.backend` = `database` / `filesystem` / `unavailable`). Also registers the Postgres vault / override stores when their switches are `postgres`. |
| `reconcile_skills_catalog` | `setup_studio_routes` | `on_startup` | Repairs stale skills-catalog search-index rows. |
| `install_studio_runtime` | `add_studio_runtime_hooks` | `on_startup` | Awaits `ensure_studio_storage` **first**, so storage resolution precedes runtime construction whatever the hook order. Installs `BotManager.studio` only when the backend is `database`; loads nothing eagerly. |
| `shutdown_studio_runtime` | `add_studio_runtime_hooks` | `on_cleanup` | Stops the sweeper and cleans up instances and asset directories. |

`BotManager.setup_registry_only(app)` calls `add_studio_runtime_hooks(app)`; `BotManager.setup(..., studio_routes=True)`
calls `setup_studio_routes(app)`.

Documented mount order for a tenant host: **resolver -> `setup_registry_only` -> `setup_studio_routes`**. The reverse
order behaves the same. `setup_studio_routes(app, prefix=..., view_wrapper=...)` may be called for several prefixes;
a prefix mounted twice is a logged no-op.

Operational notes:

- A probe failure never crashes startup: the backend becomes `unavailable`, the reason is logged (never returned to
  clients) and Studio requests answer 503 `studio_storage_unavailable`.
- Tenant partitions are served only by the `database` backend.
- The existing `tests/studio` suite documents filesystem mode and must stay green with the legacy layout:

  ```bash
  PARROT_STUDIO_STORAGE=filesystem PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src \
    pytest packages/ai-parrot-server/tests/studio -q
  ```

  Tests that need PostgreSQL read `TEST_STUDIO_PG_DSN` (a disposable PostgreSQL >= 14 database: fixtures truncate
  `navigator.ai_*`) and skip with a reason when it is unset.

## Release gate

Database storage is not tenant-ready on its own. No release is called, documented or enabled as tenant-ready until all
three specs of the package are merged and their gates met: FEAT-605 (through W4.3, including W2.2 and W3.6), this
spec's waves W0-W4 together with phase 2 (W4 is closed by the response-shape snapshot and the source gates in
`packages/ai-parrot-server/tests/studio/test_shapes_db_mode.py` and
`packages/ai-parrot-server/tests/studio/storage/test_storage_gates.py`), and the TOOLKITS waves 1-4. Until then tenant
hosts keep `studio_enabled=False`.
