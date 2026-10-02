# TASK-3952: Phase 2: BYOK keys in navigator.ai_user_llm_keys behind BYOK_STORE

**Feature**: FEAT-621 — Agent Studio — Database-Backed Storage
**Spec**: `sdd/specs/agentstudio-db-storage.spec.md`
**Spec wave**: P2 (phase 2) — BYOK Postgres store (M11)
**Status**: pending
**Priority**: low
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3926, TASK-3932
**Assigned-to**: unassigned

---

## Context

Spec §2.10 (BYOK row, 0006 DDL, `BYOK_STORE = documentdb | postgres`), §3 Module 11, Q4 (keys per user, not per
tenant). Phase 2 (spec §2.10): separately releasable; defaults stay `documentdb` until a host opts in (FieldSync sets all three switches to `postgres`). The identity scheme (§2.5c) is already in force in v1: phase 2 changes WHERE credentials live, never WHAT they are called. Ciphertexts are byte-compatible (same AAD contexts), so every move is a copy, not a re-encryption.

---

## Scope

- `migrations/0006_ai_user_llm_keys.sql` (body from §2.10 verbatim) + trailer; MANIFEST entry.
- `storage/byok_store.py` `PgUserLLMKeyStore(pool)`: `get(user_id, provider) -> str | None` (decrypt with
  `llm_key_context`), `put(user_id, provider, api_key)` (upsert ciphertext, `key_id` of the active keyring version,
  `masked = byok._mask(api_key)`), `delete`, `list_masked(user_id)`; registration helper
  `register_byok_store(app)` used at startup when `BYOK_STORE=postgres`.
- `byok.py` (`StudioKeysHandler`, `resolve_user_api_key`) dispatch on `BYOK_STORE`; `COLLECTION` path unchanged for
  `documentdb`.
- `auth/broker.py` `_UserLLMKeyResolver`: reads from the configured store (Postgres store reached through a
  registration call, core never imports server code).
- `backend.py`: when any phase-2 switch is `postgres`, the probe requires `STUDIO_SCHEMA_REQUIRED_PHASE2` (8).

**NOT in scope**: Vault credentials and overrides (TASK-3953/33); the copy script (TASK-3955).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/studio/storage/migrations/0006_ai_user_llm_keys.sql` | CREATE | BYOK table (§2.10) + ledger trailer |
| `packages/ai-parrot-server/src/parrot/handlers/studio/storage/migrations/MANIFEST.json` | MODIFY | version 6 entry |
| `packages/ai-parrot-server/src/parrot/handlers/studio/storage/byok_store.py` | CREATE | PgUserLLMKeyStore + registration |
| `packages/ai-parrot-server/src/parrot/handlers/studio/byok.py` | MODIFY | BYOK_STORE dispatch |
| `packages/ai-parrot/src/parrot/auth/broker.py` | MODIFY | _UserLLMKeyResolver store selection |
| `packages/ai-parrot-server/src/parrot/handlers/studio/storage/backend.py` | MODIFY | phase-2 required version when a phase-2 switch is postgres |
| `packages/ai-parrot-server/tests/studio/storage/test_byok_store.py` | CREATE | real-PG BYOK round trip |
| `packages/ai-parrot/tests/unit/test_user_llm_key_resolver.py` | MODIFY | resolver reads the registered Postgres store |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified code references. Use these exact imports, names and signatures. Anything not listed:
> verify it exists (`grep`/`read`) before using it.

### Verified Imports
```python
from parrot.security.credentials_utils import encrypt_credential, decrypt_credential, llm_key_context  # credentials_utils.py:53,68,83
from parrot.security.vault_utils import get_vault_keyring                                             # vault_utils.py:49 ; byok.py:25
from parrot.handlers.studio.storage.repositories import studio_transaction, _exec                    # TASK-3925
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/handlers/studio/byok.py
COLLECTION = "user_llm_keys"                                  # :31 (occurrences: 1)
def _mask(api_key: str) -> str                                # :47
async def resolve_user_api_key(app, user_id, provider) -> str | None   # :55 (delegates to _UserLLMKeyResolver)
class StudioKeysHandler(StudioBaseView):                      # :86
# packages/ai-parrot/src/parrot/auth/broker.py
class _UserLLMKeyResolver(CredentialResolver):                # :327 (occurrences: 1) — COLLECTION = "user_llm_keys"
    async def resolve(self, channel: str, user_id: str) -> str | None
```

### Does NOT Exist
- ~~`BYOK_STORE`~~ config key, ~~`navigator.ai_user_llm_keys`~~, ~~`PgUserLLMKeyStore`~~ — new.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/storage/migrations/0006_ai_user_llm_keys.sql",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/storage/migrations/MANIFEST.json",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/storage/byok_store.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/byok.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/auth/broker.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/storage/backend.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/studio/storage/test_byok_store.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/unit/test_user_llm_key_resolver.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/auth/broker.py#_UserLLMKeyResolver",
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/byok.py#StudioKeysHandler"
  ]
}
```

---

## Implementation Notes

- Parallelism: exclusive: adds migration 0006 and rewrites the shared MANIFEST.json (stamp) that TASK-3953/33 also extend; needs the --stamp CLI from TASK-3926 (storage/migrate.py) and edits storage/backend.py after TASK-3932 (phase-2 required version)
- Cross-feature ordering: none (phase 2 is outside the X16 release gate's W0–W4; it is separately releasable).
- New migration file follows TASK-3924's format exactly (advisory lock first; body + one `-- @studio-ledger` trailer); write the body, then run `parrot-studio-migrate --stamp` to produce the trailer hex and the MANIFEST entry. `required` stays 5; `required_phase2` is 8.
- Session hot copy (`SESSION_PREFIX`) unchanged.

### Common constraints (all FEAT-621 tasks)
- Contract verified against `dev` @ `32b1a45d4` (2026-09-30). Earlier FEAT-621 tasks shift line numbers:
  re-run every `grep -c` before editing and fix this file first if an anchor moved.
- Async throughout; the pool is the host's `app["database"]` (asyncdb `pg` pool); no sync driver, no second pool.
- Raw parametrised SQL (`$1…$n`), never value interpolation; schema literal `navigator`.
- Transactions only through `studio_transaction`; statements only through `_exec` (spec §2.5a).
- Pydantic for payloads, frozen dataclasses for records; `self.logger` in views,
  `logging.getLogger("Parrot.AgentStudio.Storage")` in storage/services/runtime.
- ARCHITECTURE Rule 4: functions ≤ 60 lines, cyclomatic complexity ≤ 10, modules ≤ 500 lines.
- **Database rule** (spec §4): integration tests read `TEST_STUDIO_PG_DSN` and `pytest.skip` with a reason when it is
  unset. Point it at a PostgreSQL ≥ 14 database dedicated to this worktree — the fixtures truncate `navigator.ai_*`.
- **Request/session rule** (spec §4, ARCHITECTURE R6): handler tests use `aiohttp_client` with the real session
  middleware or `make_mocked_request(..., app=app)` + `request["NAV_SESSION"] = SessionData(...)`; never a `Mock`
  with a hand-set `.session`. Each new assertion is mutation-checked (revert the guarded line ⇒ RED).
- Worktree tests: prefix with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src` as needed;
  never `uv sync` inside a worktree.

---

## Implementation Blueprint

> Write each block to its declared path nearly verbatim, then complete every `# FILL IN:` marker. Never change a
> signature, class name or file path the blueprint fixes (they come from spec §2.4/§2.5/§3 skeletons).

### `packages/ai-parrot-server/src/parrot/handlers/studio/storage/byok_store.py` (CREATE)
```python
"""BYOK keys in Postgres (spec §2.10, M11). Same AAD as DocumentDB, so ciphertexts copy verbatim."""
class PgUserLLMKeyStore:
    def __init__(self, pool) -> None:
        self._pool = pool
    # FILL IN: get / put / delete / list_masked — parametrised SQL on navigator.ai_user_llm_keys.

_REGISTERED: "PgUserLLMKeyStore | None" = None

def register_byok_store(store: "PgUserLLMKeyStore | None") -> None:
    """Called by the server at startup when BYOK_STORE=postgres; read by the core resolver."""
    global _REGISTERED
    _REGISTERED = store
```
**Why**: core `auth/broker.py` must not import server code at module load — FILL IN: expose the registration through a
core-side hook (e.g. a module-level `set_user_llm_key_store()` in `auth/broker.py`) that this server module calls.

### `packages/ai-parrot/src/parrot/auth/broker.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'class _UserLLMKeyResolver(CredentialResolver):' broker.py)
# FILL IN: module-level _PG_STORE = None + set_user_llm_key_store(store); resolve(): if _PG_STORE is not None → its get().
```

### `packages/ai-parrot-server/tests/studio/storage/test_byok_store.py` (CREATE)
```python
"""FEAT-621 phase 2 — test_byok_pg_roundtrip (AC21)."""
# FILL IN: put → row ciphertext decrypts with llm_key_context; resolve_user_api_key returns plaintext with
#   BYOK_STORE=postgres; a DocumentDB ciphertext inserted verbatim decrypts; DocumentDb never instantiated
#   (patched at the parrot.interfaces.documentdb boundary to raise).
```

---

## Acceptance Criteria

- [ ] `test_byok_pg_roundtrip`: put/get/delete through Postgres with `BYOK_STORE=postgres`; DocumentDB not contacted; a copied DocumentDB ciphertext decrypts (AC21).
- [ ] With any phase-2 switch on, the probe requires versions 1..8 (`STUDIO_SCHEMA_REQUIRED_PHASE2`).
- [ ] Migration 0006 stamped; MANIFEST updated; regression `pytest packages/ai-parrot-server/tests/studio/storage/test_migration_files.py -q` (from TASK-3924) green.
- [ ] `ruff check` clean on every touched Python file; new functions within Rule-4 budgets (`flake8` complexity).

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/studio/storage/test_byok_store.py -q`
- `pytest packages/ai-parrot/tests/unit/test_user_llm_key_resolver.py -q`

---

## Test Specification

| Test | Covers |
|---|---|
| `test_byok_pg_roundtrip` | AC21 |
| `test_migration_files_match_manifest` | AC2 (regression) |

---

## Agent Instructions

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug agentstudio-db-storage --feature-id FEAT-621`).
2. Read the spec sections cited in Context; check every `Depends-on` task is `"done"` in
   `sdd/tasks/index/agentstudio-db-storage.json`.
3. Verify the Codebase Contract anchors (`grep -c`) before editing; fix stale entries in this file first.
4. Set this task `"in-progress"` in the index (with `started_at`) and commit only the index.
5. Implement exactly the files listed, starting from the Blueprint; no refactors outside scope.
6. `ruff check --fix` the touched Python files; run the Validation Commands.
7. Commit code only (never `git add .`/`-A`):
   `feat(agentstudio-db-storage): TASK-3952 — Phase 2: BYOK keys in navigator.ai_user_llm_keys behind BYOK_STORE`.
8. Close with `scripts/sdd/close_task.sh TASK-3952 agentstudio-db-storage verified` and fill the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (package integration branch, tramo A)
**Date**: 2026-10-02
**Notes**: Commit 51b87fa5e. Migration 0006 stamped, PgUserLLMKeyStore, BYOK_STORE dispatch in byok.py and broker, 10 mutations RED. Also edited unlisted test_migrations_db.py (hard-coded 5 migrations). OPEN: required-version probe returns 8 when any phase-2 switch is postgres (0007/0008 follow in later tasks); no startup hook registers the BYOK store (lazy via get_byok_store(app)); broker.py 673 lines (was 639).

**Deviations from spec**: none
