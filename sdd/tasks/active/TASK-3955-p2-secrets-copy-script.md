# TASK-3955: Phase 2: DocumentDB → Postgres secrets copy script (BYOK, vault, overrides)

**Feature**: FEAT-621 — Agent Studio — Database-Backed Storage
**Spec**: `sdd/specs/agentstudio-db-storage.spec.md`
**Spec wave**: P2 (phase 2) — Secrets copy script
**Status**: pending
**Priority**: low
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3954
**Assigned-to**: unassigned

---

## Context

Spec §2.10 one-shot copy: `python -m parrot.handlers.studio.storage.secrets_copy --dry-run [--byok] [--vault]
[--overrides]` — idempotent upserts, reports counts, never logs values. Phase 2 (spec §2.10): separately releasable; defaults stay `documentdb` until a host opts in (FieldSync sets all three switches to `postgres`). The identity scheme (§2.5c) is already in force in v1: phase 2 changes WHERE credentials live, never WHAT they are called. Ciphertexts are byte-compatible (same AAD contexts), so every move is a copy, not a re-encryption.

---

## Scope

- `storage/secrets_copy.py` with `main(argv)` and `async copy_secrets(pool, *, byok, vault, overrides, dry_run) ->
  dict[str, int]`; reads each DocumentDB collection and upserts the ciphertext verbatim through the stores in
  `storage/byok_store.py`, `storage/vault_store.py` and `storage/overrides_store.py`.

**NOT in scope**: Re-encryption or keyring rotation (navigator-vault's job).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/studio/storage/secrets_copy.py` | CREATE | copy script |
| `packages/ai-parrot-server/tests/studio/storage/test_secrets_copy.py` | CREATE | copy is verbatim, idempotent, value-free in logs |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified code references. Use these exact imports, names and signatures. Anything not listed:
> verify it exists (`grep`/`read`) before using it.

### Verified Imports
```python
from parrot.interfaces.documentdb import DocumentDb     # vault_utils.py imports it the same way
```
Collections: `user_llm_keys` (`byok.py:31`), `user_credentials` (`vault_utils.py:41`), `user_toolkit_configs`
(`toolkit_persistence.py:14`).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/storage/secrets_copy.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/tests/studio/storage/test_secrets_copy.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

- Parallelism: upserts through PgUserLLMKeyStore from TASK-3952 (storage/byok_store.py), PgVaultCredentialStore from TASK-3953 (storage/vault_store.py) and PgToolkitOverrideStore from TASK-3954 (storage/overrides_store.py); creates storage/secrets_copy.py only
- Cross-feature ordering: none (phase 2).
- Never log a value: counts and keys `(user_id, name|provider|slug)` only; assert with `caplog`.

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

### `packages/ai-parrot-server/src/parrot/handlers/studio/storage/secrets_copy.py` (CREATE)
```python
"""One-shot DocumentDB → Postgres copy of Studio secrets (spec §2.10). Ciphertexts copied verbatim."""
# FILL IN: argparse (--dsn, --dry-run, --byok, --vault, --overrides); copy_secrets(...) -> {"byok": n, ...}.
```
### `packages/ai-parrot-server/tests/studio/storage/test_secrets_copy.py` (CREATE)
```python
# FILL IN: test_copy_verbatim_and_decrypts; test_copy_idempotent; test_dry_run_writes_nothing; test_no_values_logged.
```

---

## Acceptance Criteria

- [ ] `secrets_copy` copies ciphertexts verbatim and they decrypt from Postgres (AC21).
- [ ] Idempotent; `--dry-run` writes nothing; no secret value appears in logs.
- [ ] `ruff check` clean on every touched Python file; new functions within Rule-4 budgets (`flake8` complexity).

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/studio/storage/test_secrets_copy.py -q`

---

## Test Specification

| Test | Covers |
|---|---|
| `test_copy_verbatim_and_decrypts` | AC21 |
| `test_copy_idempotent` | §2.10 |
| `test_dry_run_writes_nothing` | §2.10 |
| `test_no_values_logged` | §2.10 |

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
   `feat(agentstudio-db-storage): TASK-3955 — Phase 2: DocumentDB → Postgres secrets copy script (BYOK, vault, overrides)`.
8. Close with `scripts/sdd/close_task.sh TASK-3955 agentstudio-db-storage verified` and fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, deviations, issues.

**Deviations from spec**: none | describe if any
