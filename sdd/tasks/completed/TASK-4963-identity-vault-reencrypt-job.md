# TASK-4963: Identity Vault re-encryption job (dry-run default, all-columns, retirement gate)

**Feature**: FEAT-773 — Delegated Auth Connections — S-1 Connections Core
**Spec**: `sdd/specs/delegated-auth-connections.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4951, TASK-4941
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 10 (AC-18, §8 key rotation). `python -m parrot.auth.oauth2.reencrypt [--apply] [--provider P ...]`
scans every credential-bearing `auth.user_identities` row in scope (disabled rows and hand-written providers such as
O365 included), never filtering by `key_version`. Per row: take the principal lock → re-read → re-seal all present
token columns under the active key in one metadata-preserving write (TASK-4951 helper). Dry-run writes nothing.
Classification: `current` (all columns decrypt with the active key alone), `stale` (decrypt only with the full ring),
`failed` (undecryptable; untouched). Key retirement requires a full-store (no provider filter) active-only verification
with `stale == 0` and `failed == 0`. Core must not import the server package except lazily in the CLI bootstrap.

---

## Scope

- `oauth2/reencrypt.py`: `reencrypt_identities(rows, lock, *, reseal_row, verify_active, classify, providers, apply=False)
  -> Dict[str, Dict[str, int]]` plus `retirement_allowed(counts, *, provider_filter) -> bool`; `main(argv)` lazily imports
  the server helpers (`ImportError` → message + exit 2) and builds the lock from a Redis client with the same key
  template as `AbstractOAuth2Manager._lock_key`.
- No token value is ever logged/printed.
- Tests: `test_reencrypt_dry_run_counts_only`, `test_reencrypt_undecryptable_row_counted_failed`,
  `test_reencrypt_retirement_gate`, `test_reencrypt_takes_principal_lock`, plus the M10 "refresh under the new key
  before migration" gate at the job level (row stamped v2 with a v1 id_token is classified stale and resealed).

**NOT in scope**: key generation/storage (navigator-auth/session own it); the server SQL (TASK-4951).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/auth/oauth2/reencrypt.py` | CREATE | job + CLI |
| `packages/ai-parrot/tests/unit/auth/test_reencrypt.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified against `dev` @ `a848d5a73e` (2026-10-30) while writing this task.
> Use these exact imports and signatures. Anything not listed: VERIFY it exists before using it.

### Verified Imports
```python
from parrot.auth.oauth2_base import _LOCK_KEY_TEMPLATE      # TASK-4940 ("lock:oauth2:{provider}:refresh:{user_id}")
from parrot.conf import OAUTH2_REDIS_URL                    # verified: conf.py:626
```

### Existing Signatures to Use
```python
# TASK-4951 server helpers (imported lazily by main() only):
#   list_credential_rows(db_pool, providers) -> List[row]; reseal_identity_row(db_pool, row, *, cipher=None) -> None
#   (raises IdentityCredentialError, row untouched); verify_active_only(row, *, active_cipher) -> bool
# Spec skeleton (adapted: rows/classify injected so core never touches the DB API):
#   reencrypt_identities(store, db_pool, lock, *, reseal_row, verify_active, providers, active_key_id, apply=False)
```

### Does NOT Exist
- ~~filtering rows by `key_version`~~ — forbidden.
- ~~`save_linked_identity` for re-sealing~~ — forbidden.
- ~~a top-level `import parrot.services...` in core~~ — forbidden; lazy inside `main()` only.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/auth/oauth2/reencrypt.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/unit/auth/test_reencrypt.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

- The spec skeleton passes `store`/`db_pool`; this task injects `rows` (an async iterable or list) and a `classify(row)`
  callable instead so the core function is DB-agnostic and testable. Record this as a deviation in the Completion Note
  (signature adapted, behaviour identical).
- Counts per provider: {"current","stale","resealed","failed"}; `failed` rows are never written.

---

## Implementation Blueprint

> Executor-ready starting point. Write each block to its declared path, then complete every
> `# FILL IN:` marker. Business branches, edge cases and test bodies are stubs by design.
> Never change a signature, class name or file path the blueprint fixes.

### Steps (in order)
1. Write the job (block) — *why*: AC-18.
2. CLI bootstrap with lazy server import — *why*: core/server boundary.
3. Tests with fakes.

### `packages/ai-parrot/src/parrot/auth/oauth2/reencrypt.py` (CREATE)
```python
"""Identity Vault re-encryption job (FEAT-773 M10, AC-18). Dry-run by default; never prints token values."""
from __future__ import annotations

import argparse
import asyncio
import logging
from typing import Any, AsyncContextManager, Awaitable, Callable, Dict, Iterable, Literal, Optional, Sequence

logger = logging.getLogger(__name__)

RowClass = Literal["current", "stale", "failed"]


async def reencrypt_identities(rows: Iterable[Any], lock: Callable[[str, str], AsyncContextManager[Any]], *,
                               reseal_row: Callable[[Any], Awaitable[None]],
                               verify_active: Callable[[Any], bool],
                               classify: Callable[[Any], RowClass],
                               apply: bool = False) -> Dict[str, Dict[str, int]]:
    """Return {provider: {"current","stale","resealed","failed"}}."""
    # FILL IN: for row: provider = row.auth_provider; async with lock(provider, str(row.user_id)): cls = classify(row)
    #          (re-read inside reseal_row); failed → count, continue; apply and cls != "failed" → await reseal_row(row)
    #          then verify_active(row) must be True else count failed; count resealed — bounded by AC-18
    raise NotImplementedError


def retirement_allowed(counts: Dict[str, Dict[str, int]], *, provider_filter: Sequence[str]) -> bool:
    """Global key retirement only after a full-store scan with stale == 0 and failed == 0."""
    # FILL IN: provider_filter non-empty → False; any stale/failed > 0 → False; else True
    raise NotImplementedError


def main(argv: Optional[Sequence[str]] = None) -> int:
    """--apply, --provider P (repeatable). Bootstraps server helpers lazily (exit 2 when unavailable)."""
    # FILL IN: argparse; lazy import of parrot.services.identity_credential_sink helpers + authdb pool; Redis lock
    #          lock:oauth2:{provider}:refresh:{user_id}; print counts and retirement_allowed(...) result
    raise NotImplementedError


if __name__ == "__main__":
    raise SystemExit(main())
```

### FILL IN checklist
- [ ] `reencrypt_identities`
- [ ] `retirement_allowed`
- [ ] `main` bootstrap
- [ ] tests (five)

---

## Acceptance Criteria

- [ ] AC-18: dry-run by default (no writes); `--apply` re-seals every readable row in scope regardless of `key_version`, under the principal lock
- [ ] Undecryptable rows → `failed`, untouched; provider-filtered runs never authorize retirement; stale/failed > 0 blocks retirement
- [ ] No token value logged or printed; core imports no server module at import time

---

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/auth/test_reencrypt.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/auth/test_reencrypt.py
@pytest.mark.asyncio
async def test_reencrypt_dry_run_counts_only(): ...
@pytest.mark.asyncio
async def test_reencrypt_undecryptable_row_counted_failed(): ...
def test_reencrypt_retirement_gate(): ...
@pytest.mark.asyncio
async def test_reencrypt_takes_principal_lock(): ...
@pytest.mark.asyncio
async def test_refresh_under_new_key_before_migration_is_stale(): ...
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug delegated-auth-connections --feature-id FEAT-773`)
2. **Read the spec** (`sdd/specs/delegated-auth-connections.spec.md`) — at least §2, the module section named in Context, §5 and §7
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/delegated-auth-connections.json`
4. **Verify the Codebase Contract** before writing ANY code (re-grep each anchor; line numbers drift). If an entry is stale, fix the contract in this file first
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:`; never change a signature or path the blueprint fixes
7. **Verify** — run the Validation Commands with `PYTHONPATH` set to every touched `packages/<dist>/src` (the shared `.venv` imports the main checkout otherwise)
8. **Commit the code** — stage only the files listed above (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh <TASK-ID> delegated-auth-connections verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

**Completed by**: sdd-worker orchestrator; seat glm5 (nova zai.glm-5)
**Date**: 2026-10-30
**Notes**: Implemented per task; merged, engine lint clean. Merge-tier validation: expected red tests/integration/oauth2/test_e2e_web_connect.py::test_persist_credential_writes_integration_row (asserts removed row.channel; rewritten by TASK-4964) plus pre-existing test_invalid_state_returns_400 (issue:e7b7e5906b6e).
