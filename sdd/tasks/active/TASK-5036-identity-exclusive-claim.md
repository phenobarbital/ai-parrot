# TASK-5036: IdentityMappingService.claim_channel_identity — exclusive channel ownership

**Feature**: FEAT-777 — Connections — Web + Slack
**Spec**: `sdd/specs/connections-web-slack.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2 "Exclusive ownership contract (M2)": the unique index on `auth.user_identities` is
`(user_id, auth_provider, provider_user_id)` — it includes `user_id`, so it cannot stop two Navigator users from
both owning the same Slack identity `T:U`. This task adds a transactional claim that enforces one owner per
`(auth_provider, provider_user_id)` under a Postgres advisory lock, and routes the Slack branch of `upsert_identity`
through it. Consumers: link confirm handler (TASK-5041) and the Slack OAuth callback (TASK-5043). AC-5.

---

## Scope

- Add `async claim_channel_identity(*, nav_user_id, auth_provider, provider_user_id, auth_data, display_name=None, email=None) -> ClaimResult`
  to `IdentityMappingService`.
- In ONE transaction on the raw asyncpg connection: `pg_advisory_xact_lock(hashtextextended(auth_provider || ':' || provider_user_id, 0))`,
  then read **all** rows for `(auth_provider, provider_user_id)` including disabled ones, then:
  - no rows → insert (same column set as `_UPSERT_SQL`) → `ClaimResult(status="claimed")`;
  - exactly one row, `enabled`, same `user_id` → idempotent, refresh non-secret `auth_data`/display/email → `"already_owned"`;
  - anything else (other owner, disabled row, several rows) → `"conflict"`, no write.
- Same input validation as `upsert_identity` (numeric `nav_user_id`, non-empty `provider_user_id`, no secret keys in `auth_data`).
- Route `upsert_identity(..., auth_provider="slack", token=None)` through `claim_channel_identity`; a `"conflict"` result
  raises `PermissionError("channel identity already owned")` (callers already catch broad exceptions; do not leak the owner id).
- Log conflicts with a non-secret diagnostic (provider + count of rows; never the other owner's id or e-mail).
- Unit tests (validation + result mapping with a fake connection) and real-Postgres tests (skip without DSN), including the
  concurrent distinct-user race.

**NOT in scope**: the resolver's exactly-one-owner read (TASK-5037), HTTP handler (TASK-5041), Slack callback change (TASK-5043),
ownership transfer/reactivation (out of v1).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/services/identity_mapping.py` | MODIFY | `ClaimResult`, `_CLAIM_*_SQL`, `claim_channel_identity`, slack branch in `upsert_identity` |
| `packages/ai-parrot-server/tests/unit/test_identity_mapping_claim.py` | CREATE | Unit + real-Postgres tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.services.identity_mapping import IdentityMappingService, _raw_connection, _SECRET_KEYS
# verified: packages/ai-parrot-server/src/parrot/services/identity_mapping.py — class :136, _raw_connection :101, _SECRET_KEYS :98
# module already imports: dataclasses, json, logging, TYPE_CHECKING, Any, Dict, List, Optional (top of file)
from pydantic import BaseModel                                   # for ClaimResult
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/services/identity_mapping.py
_UPSERT_SQL  # INSERT INTO auth.user_identities (user_id, auth_provider, provider_user_id, auth_data, display_name, email, created_at)
             # VALUES ($1::text::bigint, $2, $3, $4::jsonb, $5, $6, NOW()) ON CONFLICT ... (partial unique index)
_SECRET_KEYS = frozenset({"access_token", "refresh_token", "id_token", "token", "client_secret"})   # :98
def _raw_connection(conn: Any) -> Any   # :101 — asyncdb wrapper → raw asyncpg conn (raises on error)
class IdentityMappingService:           # :136
    def __init__(self, db_pool: Any, identity_store=None) -> None          # :156 (self._pool, self.logger)
    async def upsert_identity(self, *, nav_user_id: str, auth_provider: str, provider_user_id: str,
                              auth_data: Dict[str, Any], display_name=None, email=None, token=None) -> None   # :173
        # numeric guard :213-218 (`if not str(nav_user_id or "").isdigit(): raise ValueError(...)`)
        # `if token is not None:` IdentityStore path; `else:` raw SQL path with `async with self._pool.acquire() as conn:`
# auth.user_identities columns (navigator_auth.models.UserIdentity): identity_id, user_id(bigint), auth_provider,
#   provider_user_id, auth_data(jsonb), display_name, email, enabled(bool default true), created_at, ...
# Real-Postgres fixture pattern: packages/ai-parrot/tests/unit/test_identity_mapping.py:105-200
#   (_dsn(): IDENTITY_PG_DSN or parrot.conf.default_dsn; asyncdb AsyncDB("pg", dsn=...); rolled-back transaction; skip if unreachable)
```

### Does NOT Exist
- ~~`IdentityMappingService.claim_channel_identity`~~, ~~`ClaimResult`~~ — created here.
- ~~A unique index on `(auth_provider, provider_user_id)`~~ — only `(user_id, auth_provider, provider_user_id) WHERE provider_user_id IS NOT NULL`.
- ~~`IdentityStore.claim*` / any navigator-auth exclusive-claim API~~ — do not look for one; no dependency change is authorized.
- ~~Ownership transfer / re-enable of a disabled row~~ — out of v1; conflict instead.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-server/src/parrot/services/identity_mapping.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/tests/unit/test_identity_mapping_claim.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/services/identity_mapping.py#IdentityMappingService",
    "sym:packages/ai-parrot-server/src/parrot/services/identity_mapping.py#IdentityMappingService.upsert_identity",
    "sym:packages/ai-parrot-server/src/parrot/services/identity_mapping.py#_raw_connection"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Lock and read in the SAME transaction (`async with raw.transaction():`), advisory lock is transaction-scoped
  (`pg_advisory_xact_lock`) so it releases on commit/rollback.
- Count disabled rows as owners — "disabled ownership returns conflict" (spec).
- DB errors propagate (callers decide; the confirm handler must never report success — spec).
- The real-DB race test needs two separate connections with committed writes: the rolled-back single-connection fixture
  cannot exercise it. FK `auth.users` is DEFERRABLE INITIALLY DEFERRED → committed rows need two **existing** user ids.

---

## Implementation Blueprint

### Steps (in order)
1. Add `ClaimResult` and the claim SQL constants below `_SECRET_KEYS` — *why*: module-level SQL constants are the file's convention.
2. Add `claim_channel_identity` right before `upsert_identity` — *why*: the slack branch of `upsert_identity` calls it.
3. Route the slack metadata branch of `upsert_identity` through it.
4. Write the tests; run them.

### `packages/ai-parrot-server/src/parrot/services/identity_mapping.py` (MODIFY — constants)
```python
# occurrences: 1 (verified: grep -c '^_SECRET_KEYS = frozenset' packages/ai-parrot-server/src/parrot/services/identity_mapping.py)
# AFTER — insert below `_SECRET_KEYS = frozenset({...})` (verified: identity_mapping.py:98)
_CLAIM_LOCK_SQL = "SELECT pg_advisory_xact_lock(hashtextextended($1 || ':' || $2, 0))"
_CLAIM_OWNERS_SQL = """
SELECT identity_id, user_id, enabled
FROM auth.user_identities
WHERE auth_provider = $1 AND provider_user_id = $2
"""


class ClaimResult(BaseModel):
    """Outcome of :meth:`IdentityMappingService.claim_channel_identity` (never carries the other owner)."""

    status: Literal["claimed", "already_owned", "conflict"]
```
(add `from typing import Literal` to the existing typing import and `from pydantic import BaseModel`).

### `packages/ai-parrot-server/src/parrot/services/identity_mapping.py` (MODIFY — method)
```python
# occurrences: 1 (verified: grep -c '    async def upsert_identity(' packages/ai-parrot-server/src/parrot/services/identity_mapping.py)
# BEFORE — insert above `    async def upsert_identity(` (verified: identity_mapping.py:173)
    async def claim_channel_identity(
        self,
        *,
        nav_user_id: str,
        auth_provider: str,
        provider_user_id: str,
        auth_data: Dict[str, Any],
        display_name: Optional[str] = None,
        email: Optional[str] = None,
    ) -> ClaimResult:
        """Exclusively claim ``(auth_provider, provider_user_id)`` for ``nav_user_id`` (FEAT-777 M2).

        One transaction: advisory lock on the identity key, read every matching row (disabled included),
        insert only when nobody owns it. Same enabled owner → idempotent. Anything else → conflict, no write.

        Raises:
            ValueError: non-numeric ``nav_user_id``, empty ``provider_user_id`` or secrets in ``auth_data``.
            Exception: database failures propagate.
        """
        # FILL IN: reuse the exact validation rules of upsert_identity (numeric id, non-empty id, _SECRET_KEYS) — bounded by AC-5
        payload = json.dumps(dict(auth_data or {}), default=str)
        async with self._pool.acquire() as conn:
            raw = _raw_connection(conn)
            async with raw.transaction():
                await raw.execute(_CLAIM_LOCK_SQL, auth_provider, str(provider_user_id))
                rows = await raw.fetch(_CLAIM_OWNERS_SQL, auth_provider, str(provider_user_id))
                # FILL IN: decide claimed / already_owned / conflict exactly per Scope; on "claimed" fetchrow(_UPSERT_SQL, ...);
                #   on "already_owned" refresh auth_data/display_name/email with the same _UPSERT_SQL (ON CONFLICT updates);
                #   on "conflict" log provider + len(rows) only — bounded by spec "Exclusive ownership contract"
                ...
```

### `packages/ai-parrot-server/src/parrot/services/identity_mapping.py` (MODIFY — slack branch)
```python
# occurrences: 1 (verified: grep -c '        payload = json.dumps(data, default=str)' packages/ai-parrot-server/src/parrot/services/identity_mapping.py)
# AFTER — insert below `        payload = json.dumps(data, default=str)` inside upsert_identity (verified: identity_mapping.py:228)
        if token is None and auth_provider == "slack":
            result = await self.claim_channel_identity(
                nav_user_id=str(nav_user_id),
                auth_provider=auth_provider,
                provider_user_id=provider_user_id,
                auth_data=data,
                display_name=display_name,
                email=email,
            )
            if result.status == "conflict":
                raise PermissionError("channel identity already owned")
            return
```
**Why**: spec — "Every in-tree Slack writer, including the generic `upsert_identity` Slack branch, must use this operation and lock."
Raising `PermissionError` keeps the existing `-> None` signature while making the conflict impossible to ignore.

### `packages/ai-parrot-server/tests/unit/test_identity_mapping_claim.py` (CREATE)
```python
"""Tests for IdentityMappingService.claim_channel_identity (FEAT-777 M2).

Real-Postgres tests skip without IDENTITY_PG_DSN / parrot.conf.default_dsn or when Postgres is unreachable.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest

from parrot.services.identity_mapping import ClaimResult, IdentityMappingService


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_id", ["", "T01:U02", "abc"])
async def test_claim_rejects_non_numeric_nav_user_id(bad_id: str) -> None:
    # FILL IN: pool double whose acquire() fails the test if reached; ValueError raised before any DB access
    ...


@pytest.mark.asyncio
async def test_claim_result_mapping_with_fake_connection() -> None:
    """No rows → claimed; one enabled same owner → already_owned; other/disabled/several → conflict (no insert)."""
    # FILL IN: fake raw connection with transaction(), execute(), fetch(rows), fetchrow() recording calls
    ...


@pytest.mark.asyncio
async def test_upsert_identity_slack_conflict_raises() -> None:
    # FILL IN: monkeypatch claim_channel_identity → ClaimResult(status="conflict"); upsert_identity(auth_provider="slack") raises PermissionError
    ...


@pytest.mark.asyncio
async def test_channel_link_exclusive_claim_real_db() -> None:
    """Two connections, two existing user ids, one provider_user_id: exactly one claimed and one conflict."""
    # FILL IN: skip without DSN or fewer than two auth.users rows; provider_user_id=f"TTEST{uuid4().hex}:U";
    #   asyncio.gather the two claims on separate connections; assert sorted statuses == ["claimed", "conflict"];
    #   same user repeats → already_owned; ALWAYS DELETE the test rows in finally — bounded by spec §4 test_channel_link_exclusive_claim
    ...


@pytest.mark.asyncio
async def test_disabled_owner_is_conflict_real_db() -> None:
    # FILL IN: insert a disabled row for user A inside a rolled-back transaction (single-conn fixture pattern), claim as A → conflict
    ...
```

### FILL IN checklist
- [ ] Validation identical to `upsert_identity` — bounded by AC-5.
- [ ] Claim decision table and SQL calls — bounded by spec "Exclusive ownership contract (M2)".
- [ ] Real-DB race test with guaranteed cleanup — bounded by spec §4 `test_channel_link_exclusive_claim`, `test_channel_link_existing_ambiguous_or_disabled_owner`.

---

## Acceptance Criteria

- [ ] Concurrent distinct-user claims of one `T:U` yield exactly one owner and one `"conflict"` (real DB).
- [ ] Same enabled owner is idempotent; disabled or multiple rows → conflict with no write.
- [ ] `upsert_identity(auth_provider="slack")` without a token goes through the claim; conflict raises `PermissionError`.
- [ ] No log line contains another owner's id or e-mail.
- [ ] Tests pass (DB tests skip cleanly without Postgres); `ruff check` clean.

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/unit/test_identity_mapping_claim.py -q`
- `pytest packages/ai-parrot/tests/unit/test_identity_mapping.py -q`

---

## Test Specification

See the CREATE test block above.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug connections-web-slack --feature-id FEAT-777`)
2. **Read the spec** (§3 Module 2 "Exclusive ownership contract", AC-5)
3. **Check dependencies** — none
4. **Verify the Codebase Contract** before writing code
5. **Update status** → `"in-progress"` and commit only the index file
6. **Implement** from the blueprint; complete every `# FILL IN:`
7. **Verify** — run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src`
8. **Commit the code** — only the listed files
9. **Close the task** with `scripts/sdd/close_task.sh TASK-5036 connections-web-slack verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
