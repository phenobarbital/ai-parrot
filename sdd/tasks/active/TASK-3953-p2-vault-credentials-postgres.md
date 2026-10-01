# TASK-3953: Phase 2: vault credentials in navigator.ai_user_credentials behind VAULT_STORE

**Feature**: FEAT-621 — Agent Studio — Database-Backed Storage
**Spec**: `sdd/specs/agentstudio-db-storage.spec.md`
**Spec wave**: P2 (phase 2) — Vault credentials + overrides in Postgres (M12, part 1: vault credentials)
**Status**: pending
**Priority**: low
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3952
**Assigned-to**: unassigned

---

## Context

Spec §2.10 (vault credentials row, 0007 DDL, `VAULT_STORE`), §3 Module 12 (`store_vault_credential` /
`retrieve_vault_credential` / `delete_vault_credential` dispatch with unchanged signatures, so every caller — Studio,
MCP, OAuth2 — is unchanged; the Postgres store receives the pool through a registration call made by the server at
startup; a `navigator_session.vault_targets` entry so keyring rotation covers the new table). Phase 2 (spec §2.10): separately releasable; defaults stay `documentdb` until a host opts in (FieldSync sets all three switches to `postgres`). The identity scheme (§2.5c) is already in force in v1: phase 2 changes WHERE credentials live, never WHAT they are called. Ciphertexts are byte-compatible (same AAD contexts), so every move is a copy, not a re-encryption.

---

## Scope

- `migrations/0007_ai_user_credentials.sql` + trailer; MANIFEST entry.
- `storage/vault_store.py` `PgVaultCredentialStore(pool)` (`store`, `retrieve`, `delete` with the same AAD
  `credential_context(user_id, name)`), registered at startup when `VAULT_STORE=postgres` (registration performed in
  `ensure_studio_storage`, `backend.py`).
- `security/vault_utils.py`: `VAULT_STORE` dispatch + `set_vault_credential_store(store)` registration hook.
- `storage/vault_targets.py`: `navigator_session` Postgres targets for `navigator.ai_user_credentials` and
  `navigator.ai_user_llm_keys` (mirrors core `parrot/vault_targets.py` DocumentDB targets); two entry points in the
  server `pyproject.toml` next to `parrot_users_bots`.

**NOT in scope**: Per-user overrides store (TASK-3954); copy script (TASK-3955).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/studio/storage/migrations/0007_ai_user_credentials.sql` | CREATE | vault credentials table (§2.10) + trailer |
| `packages/ai-parrot-server/src/parrot/handlers/studio/storage/migrations/MANIFEST.json` | MODIFY | version 7 entry |
| `packages/ai-parrot-server/src/parrot/handlers/studio/storage/vault_store.py` | CREATE | PgVaultCredentialStore |
| `packages/ai-parrot-server/src/parrot/handlers/studio/storage/vault_targets.py` | CREATE | navigator_session Postgres vault targets for the two phase-2 secret tables |
| `packages/ai-parrot/src/parrot/security/vault_utils.py` | MODIFY | VAULT_STORE dispatch + registration hook |
| `packages/ai-parrot-server/src/parrot/handlers/studio/storage/backend.py` | MODIFY | register the Postgres vault store at startup when VAULT_STORE=postgres |
| `packages/ai-parrot-server/pyproject.toml` | MODIFY | navigator_session.vault_targets entry points |
| `packages/ai-parrot-server/tests/studio/storage/test_vault_store.py` | CREATE | real-PG vault round trip + rotation target smoke test |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified code references. Use these exact imports, names and signatures. Anything not listed:
> verify it exists (`grep`/`read`) before using it.

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/security/vault_utils.py
VAULT_CRED_COLLECTION: str = "user_credentials"                    # :41 (occurrences: 1)
def get_vault_keyring() -> Any                                     # :49
async def store_vault_credential(user_id, vault_name, secret_params) -> None   # :84 (AAD credential_context)
async def retrieve_vault_credential(...)                           # :135
async def delete_vault_credential(user_id: str, vault_name: str) -> None       # :172
# packages/ai-parrot-server/pyproject.toml
[project.entry-points."navigator_session.vault_targets"]           # :92
parrot_users_bots = "parrot.handlers.models.vault_target:factory"  # :93 (anchor)
# packages/ai-parrot/src/parrot/vault_targets.py — DocumentDB targets user_credentials :210, user_llm_keys :223 (pattern)
# packages/ai-parrot-server/src/parrot/handlers/models/vault_target.py — PostgresTarget subclass precedent (UsersBotsTarget)
```

### Does NOT Exist
- ~~A Postgres-backed vault~~ — `store_vault_credential` always uses DocumentDB today (`vault_utils.py:30`, `:111`).
- ~~`VAULT_STORE`~~ — new.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/storage/migrations/0007_ai_user_credentials.sql",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/storage/migrations/MANIFEST.json",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/storage/vault_store.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/storage/vault_targets.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/security/vault_utils.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/storage/backend.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/pyproject.toml",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/studio/storage/test_vault_store.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/security/vault_utils.py#store_vault_credential",
    "sym:packages/ai-parrot/src/parrot/security/vault_utils.py#retrieve_vault_credential",
    "sym:packages/ai-parrot/src/parrot/security/vault_utils.py#delete_vault_credential"
  ]
}
```

---

## Implementation Notes

- Parallelism: exclusive: edits packages/ai-parrot-server/pyproject.toml (vault_targets entry points) and the shared MANIFEST.json after TASK-3952 (0006 entry, same file); also edits storage/backend.py after TASK-3952
- Cross-feature ordering: none (phase 2).
- New migration file follows TASK-3924's format exactly (advisory lock first; body + one `-- @studio-ledger` trailer); write the body, then run `parrot-studio-migrate --stamp` to produce the trailer hex and the MANIFEST entry. `required` stays 5; `required_phase2` is 8.
- Spec ambiguity resolved here: §3 M12 asks for "a `navigator_session.vault_targets` entry for the new table"; both
  phase-2 secret tables (`ai_user_credentials`, `ai_user_llm_keys`) hold keyring-sealed values, so both get a target.

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

### `packages/ai-parrot/src/parrot/security/vault_utils.py` (MODIFY)
```python
# AFTER — insert below `VAULT_CRED_COLLECTION: str = "user_credentials"` (verified: vault_utils.py:41, occurrences: 1)
_PG_VAULT_STORE: Any = None


def set_vault_credential_store(store: Any) -> None:
    """Server registers its Postgres store at startup (VAULT_STORE=postgres). Core never imports server code."""
    global _PG_VAULT_STORE
    _PG_VAULT_STORE = store
# FILL IN: first statement of store/retrieve/delete: `if _PG_VAULT_STORE is not None: return await _PG_VAULT_STORE.<op>(...)`.
```
### `packages/ai-parrot-server/src/parrot/handlers/studio/storage/vault_store.py`, `packages/ai-parrot-server/src/parrot/handlers/studio/storage/vault_targets.py` (CREATE) — FILL IN per Scope.
### `packages/ai-parrot-server/tests/studio/storage/test_vault_store.py` (CREATE)
```python
# FILL IN: test_vault_pg_roundtrip (store/retrieve/delete with VAULT_STORE=postgres; DocumentDB never contacted);
#   test_vault_targets_entry_points_load.
```

---

## Acceptance Criteria

- [ ] With `VAULT_STORE=postgres`, vault credentials round-trip through `navigator.ai_user_credentials`; DocumentDB not contacted (AC21, vault half).
- [ ] Callers of `store/retrieve/delete_vault_credential` unchanged (same signatures).
- [ ] Regression: `pytest packages/ai-parrot-server/tests/studio/storage/test_migration_files.py -q` (from TASK-3924) green with 0007 stamped.
- [ ] Keyring rotation targets registered for both phase-2 secret tables.
- [ ] `ruff check` clean on every touched Python file; new functions within Rule-4 budgets (`flake8` complexity).

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/studio/storage/test_vault_store.py -q`

---

## Test Specification

| Test | Covers |
|---|---|
| `test_vault_pg_roundtrip` | AC21 |
| `test_vault_targets_entry_points_load` | §3 M12 rotation |

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
   `feat(agentstudio-db-storage): TASK-3953 — Phase 2: vault credentials in navigator.ai_user_credentials behind VAULT_STORE`.
8. Close with `scripts/sdd/close_task.sh TASK-3953 agentstudio-db-storage verified` and fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, deviations, issues.

**Deviations from spec**: none | describe if any
