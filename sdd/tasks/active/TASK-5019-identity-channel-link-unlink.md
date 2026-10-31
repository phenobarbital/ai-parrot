# TASK-5019: `IdentityMappingService.link_channel_identity` / `unlink_channel_identity` (serialized ownership)

**Feature**: FEAT-776 — Connections on Telegram
**Spec**: `sdd/specs/connections-telegram.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4 (server half), AC-1, AC-2. The `telegram` row in `auth.user_identities` is what FEAT-773's
`IdentityPrincipalResolver` reads. The existing upsert conflicts on `(user_id, auth_provider, provider_user_id)`,
so one Telegram id can be linked to two Navigator users. This task adds an exclusive link and an unlink, both
serialized by one deterministic advisory transaction lock — a transaction alone or `SELECT FOR UPDATE` on a
possibly absent row is insufficient (spec M4 "Concurrency contract").

---

## Scope

- Add `_DELETE_CHANNEL_OTHERS_SQL`, `_DELETE_CHANNEL_SQL`, a lock SQL, and a deterministic lock-key helper.
- Add `link_channel_identity(...)` and `unlink_channel_identity(...)`.
- Unit tests (fake pool/conn) + real-DB integration tests (opt-in, separate connections).

**NOT in scope**: Telegram wrapper calls (TASK-5020); any schema/constraint change (the unique index stays);
changing `upsert_identity`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/services/identity_mapping.py` | MODIFY | link/unlink + lock |
| `packages/ai-parrot-server/tests/test_identity_channel_link.py` | CREATE | unit tests (fake pool) |
| `packages/ai-parrot-server/tests/integration/test_identity_channel_link_db.py` | CREATE | real-DB concurrency + resolver tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.services.identity_mapping import IdentityMappingService             # verified: identity_mapping.py:136
from parrot.services.identity_principal import IdentityPrincipalResolver        # verified: identity_principal.py:11
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/services/identity_mapping.py
_UPSERT_SQL  # :43-57  INSERT ... VALUES ($1::text::bigint, $2, $3, $4::jsonb, $5, $6, NOW())
             #         ON CONFLICT (user_id, auth_provider, provider_user_id) WHERE provider_user_id IS NOT NULL DO UPDATE ...
_GET_SQL     # :75-82  SELECT identity_id, user_id, auth_provider, provider_user_id, auth_data, display_name, email, created_at
_SECRET_KEYS = frozenset({"access_token", "refresh_token", "id_token", "token", "client_secret"})   # :98
def _raw_connection(conn: Any) -> Any                                            # :101 (unwraps asyncdb pgPool conns)
class IdentityMappingService:                                                    # :136
    def __init__(self, db_pool: Any, identity_store: Optional["IdentityStore"] = None) -> None   # :156
    async def upsert_identity(self, *, nav_user_id, auth_provider, provider_user_id, auth_data,
                              display_name=None, email=None, token=None) -> None # :173  validation :207-225
    async def get_identity(self, nav_user_id: str, auth_provider: str) -> Optional[Dict[str, Any]]   # :270
    async def delete_identity(self, nav_user_id: str, auth_provider: str) -> None # :307
#   pattern: async with self._pool.acquire() as conn: await _raw_connection(conn).execute(...)
```

### Does NOT Exist
- ~~`link_channel_identity`, `unlink_channel_identity`, a delete-by-`provider_user_id` query~~ — created here.
- ~~A DB migration~~ — none; `auth.user_identities` is unchanged.
- ~~Python `hash()` for the lock key~~ — process-randomized; forbidden. Use a digest.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-server/src/parrot/services/identity_mapping.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/tests/test_identity_channel_link.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-server/tests/integration/test_identity_channel_link_db.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/services/identity_mapping.py#IdentityMappingService",
    "sym:packages/ai-parrot-server/src/parrot/services/identity_mapping.py#IdentityMappingService.upsert_identity",
    "sym:packages/ai-parrot-server/src/parrot/services/identity_mapping.py#_raw_connection",
    "sym:packages/ai-parrot-server/src/parrot/services/identity_principal.py#IdentityPrincipalResolver"
  ]
}
```

---

## Implementation Notes

- Lock: `SELECT pg_advisory_xact_lock($1::bigint)` as the FIRST statement inside `conn.transaction()`, on the
  same connection as the delete/upsert. Key = first 8 bytes of `sha256(b"parrot:channel-identity\0" + provider + b"\0" + provider_user_id)`
  read as a **signed** big-endian int (`int.from_bytes(..., "big", signed=True)`) — namespaced and unambiguous.
- Validation mirrors `upsert_identity` (numeric `nav_user_id`, non-empty `provider_user_id`, no `_SECRET_KEYS`).
  Token-bearing providers are rejected: link only channel rows — accept `token` nowhere in the signature.
- Real-DB tests follow `tests/integration/test_identity_vault_store_db.py` (opt-in env `IDENTITY_PG_DSN`,
  `importorskip("asyncpg")`, skip when unreachable). Need **two** test user ids (env `IDENTITY_TEST_USER_ID` and
  `IDENTITY_TEST_USER_ID_2`). A skip is **blocked validation**, never a pass — say so in the Completion Note.

---

## Implementation Blueprint

### Steps (in order)
1. Add SQL constants + `_channel_lock_key()` below `_SECRET_KEYS` — *why*: one shared key derivation for both mutations.
2. Extract the validation of `upsert_identity` into a private `_validate_identity_input(...)` used by both — *why*:
   identical rules (spec: "same validation as upsert_identity").
3. Add both methods after `delete_identity` — *why*: Edit Sites anchor.
4. Unit tests with a fake connection that records the statement order; real-DB tests with two pools.

### `packages/ai-parrot-server/src/parrot/services/identity_mapping.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    async def delete_identity(' packages/ai-parrot-server/src/parrot/services/identity_mapping.py)
# module level — AFTER `_SECRET_KEYS = frozenset({...})` (verified: identity_mapping.py:98):
_CHANNEL_LOCK_SQL = "SELECT pg_advisory_xact_lock($1::bigint)"
_DELETE_CHANNEL_OTHERS_SQL = """DELETE FROM auth.user_identities
    WHERE auth_provider = $1 AND provider_user_id = $2 AND user_id <> $3::text::bigint"""
_DELETE_CHANNEL_SQL = "DELETE FROM auth.user_identities WHERE auth_provider = $1 AND provider_user_id = $2"


def _channel_lock_key(auth_provider: str, provider_user_id: str) -> int:
    """Return a stable signed-bigint advisory-lock key for one channel account."""
    raw = b"parrot:channel-identity\0" + auth_provider.encode() + b"\0" + str(provider_user_id).encode()
    return int.from_bytes(hashlib.sha256(raw).digest()[:8], "big", signed=True)
# imports: add `import hashlib` next to `import json` (:29)

# AFTER the whole `delete_identity` method (anchor `    async def delete_identity(`, verified :307):
    async def link_channel_identity(
        self,
        *,
        nav_user_id: str,
        auth_provider: str,
        provider_user_id: str,
        auth_data: Dict[str, Any],
        display_name: Optional[str] = None,
        email: Optional[str] = None,
    ) -> None:
        """Make ``nav_user_id`` the sole owner of a channel account, atomically.

        One transaction: advisory lock → delete rows owned by other users → upsert.

        Raises:
            ValueError: invalid input (same rules as ``upsert_identity``) or secrets in ``auth_data``.
        """
        # FILL IN: _validate_identity_input(...) → provider_user_id str, payload json
        async with self._pool.acquire() as conn:
            raw = _raw_connection(conn)
            async with raw.transaction():
                await raw.execute(_CHANNEL_LOCK_SQL, _channel_lock_key(auth_provider, provider_user_id))
                await raw.execute(_DELETE_CHANNEL_OTHERS_SQL, auth_provider, provider_user_id, str(nav_user_id))
                row = await raw.fetchrow(
                    _UPSERT_SQL, str(nav_user_id), auth_provider, provider_user_id, payload, display_name, email
                )
                # FILL IN: row is None → RuntimeError (rolls the transaction back)
        self.logger.info("IdentityMappingService: linked %s account to user=%s", auth_provider, nav_user_id)

    async def unlink_channel_identity(self, auth_provider: str, provider_user_id: str) -> int:
        """Delete every row for a channel account under the shared lock; return the count (0 when absent)."""
        async with self._pool.acquire() as conn:
            raw = _raw_connection(conn)
            async with raw.transaction():
                await raw.execute(_CHANNEL_LOCK_SQL, _channel_lock_key(auth_provider, str(provider_user_id)))
                status = await raw.execute(_DELETE_CHANNEL_SQL, auth_provider, str(provider_user_id))
        # FILL IN: parse asyncpg status "DELETE <n>" → int; log; return
```
**Why**: spec M4 concurrency contract — lock before reading/mutating, same connection/transaction, works for
first links with no row. Do not log `provider_user_id` together with the user id at INFO beyond what
`upsert_identity` already logs.

### `packages/ai-parrot-server/tests/test_identity_channel_link.py` (CREATE)
```python
"""FEAT-776 M4 unit tests: channel link/unlink (fake pool)."""
import pytest

from parrot.services.identity_mapping import IdentityMappingService


@pytest.mark.asyncio
async def test_link_channel_identity_moves_ownership() -> None: ...       # FILL IN (in-memory fake conn applying the SQL semantics)
@pytest.mark.asyncio
async def test_channel_identity_lock_shared_by_mutations() -> None: ...   # FILL IN: same key, lock is first statement, inside transaction()
@pytest.mark.asyncio
async def test_link_channel_identity_rejects_bad_input() -> None: ...     # FILL IN: non-numeric id, empty provider id, secret key
@pytest.mark.asyncio
async def test_unlink_channel_identity_counts() -> None: ...              # FILL IN: "DELETE 1" → 1, "DELETE 0" → 0
```

### `packages/ai-parrot-server/tests/integration/test_identity_channel_link_db.py` (CREATE)
```python
"""FEAT-776 M4 real-DB tests (opt-in: IDENTITY_PG_DSN, IDENTITY_TEST_USER_ID, IDENTITY_TEST_USER_ID_2)."""
import pytest

asyncpg = pytest.importorskip("asyncpg")

# FILL IN: fixture modelled on test_identity_vault_store_db.py::store_db, yielding two services on two pools
# and a unique provider_user_id per test (cleanup in finally via unlink_channel_identity).

@pytest.mark.asyncio
async def test_db_concurrent_channel_identity_links() -> None: ...  # FILL IN: competing first links + relinks → one owner; failed replacement rolls back; link/unlink serialize
@pytest.mark.asyncio
async def test_e2e_telegram_login_link_resolves() -> None: ...      # FILL IN: link → IdentityPrincipalResolver(pool).resolve("telegram", id).user_id; unlink → None
```

### FILL IN checklist
- [ ] `_validate_identity_input` extraction keeps `upsert_identity` behaviour byte-for-byte (its tests in `packages/ai-parrot/tests/unit/test_identity_mapping.py` still pass)
- [ ] Rollback test: force the upsert to fail after the delete; the other user's row must survive
- [ ] Completion Note states whether the real-DB tests ran or were skipped (skip = blocked, AC-1 not evidenced)

---

## Acceptance Criteria

- [ ] AC-1 (service half): exclusive ownership under competing first links/relinks, proved on a real DB
- [ ] `unlink_channel_identity` returns the deleted count, 0 when absent
- [ ] `ruff check` clean

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/test_identity_channel_link.py -q`
- `pytest packages/ai-parrot-server/tests/integration/test_identity_channel_link_db.py -q`
- `pytest packages/ai-parrot/tests/unit/test_identity_mapping.py -q`

---

## Test Specification

Blueprint test files; names fixed by spec §4 (M4 rows + `test_db_concurrent_channel_identity_links`, `test_e2e_telegram_login_link_resolves`).

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug connections-telegram --feature-id FEAT-776`)
2. Verify the Codebase Contract first; implement from the blueprint
3. Validate with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src`
4. Commit only the listed files; close with `scripts/sdd/close_task.sh TASK-5019 connections-telegram verified`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
