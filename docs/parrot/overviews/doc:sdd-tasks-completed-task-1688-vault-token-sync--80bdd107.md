---
type: Wiki Overview
title: 'TASK-1688: Close `VaultTokenSync.store_tokens` partial-write / forever-valid-on-missing-`expires_at`
  gap'
id: doc:sdd-tasks-completed-task-1688-vault-token-sync-atomic-persist-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: FEAT-266 code review flagged that `VaultTokenSync.store_tokens()`
---

# TASK-1688: Close `VaultTokenSync.store_tokens` partial-write / forever-valid-on-missing-`expires_at` gap

**Feature**: FEAT-267 — O365 Device-Code Follow-ups
**Spec**: `sdd/specs/o365-devicecode-followups.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (2-3h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

FEAT-266 code review flagged that `VaultTokenSync.store_tokens()`
(`packages/ai-parrot-server/src/parrot/services/vault_token_sync.py:131-164`) writes each
`tokens[key]` via an individual `await vault.set(...)` inside a loop, wrapped in one broad
`except Exception` that logs and swallows. A failure partway through (e.g. `access_token`
persisted but `expires_at` write fails) leaves a token set missing `expires_at`.
`O365DeviceCodeCredentialResolver.resolve()`'s cache-hit check
(`packages/ai-parrot/src/parrot/auth/oauth2/o365_devicecode_provider.py:145`)
(`expires_at is None or expires_at > time.time() + _EXPIRY_SKEW_SECONDS`) treats a missing
`expires_at` as **valid forever** — the same fallback intentionally used in `is_connected()`
(line 188) for the "field legitimately absent" case. FEAT-266 is the first production writer of
`o365:*` keys, so this is the first place the gap gets exercised: a stale/dead token could be
trusted indefinitely with no re-validation on a real 401 from Graph.

---

## Scope

- In `VaultTokenSync.store_tokens()`: reorder or batch the writes so a partial failure cannot
  produce a token set that reads as permanently valid. Concretely:
  1. Check whether the underlying vault object (returned by `_load_vault`) exposes any
     multi-key/transactional write primitive — read `_load_vault`'s return type and the vault
     class it comes from (`navigator_session.vault.SessionVault` or equivalent — verify the
     actual import/class during implementation) before assuming none exists.
  2. If a bulk-write exists, use it. If not, write `expires_at` **first** (before `access_token`
     and other fields) so that a mid-loop failure either leaves `expires_at` already correctly
     set, or leaves `access_token` never written (so a subsequent read returns `None`/incomplete
     rather than a token that looks perpetually fresh).
  3. Add a distinguishable log line (not just the existing generic `logger.exception`) when the
     loop does not complete fully — e.g. count expected vs. written keys and warn if they differ.
- In `O365DeviceCodeCredentialResolver`'s cache-hit path
  (`o365_devicecode_provider.py` around line 144-145): change the interpretation for the `o365`
  provider specifically so that a **missing** `expires_at` on a read token set is treated as
  *expired* (triggers refresh-or-device-flow), not *valid forever* — since `expires_at` is
  always part of a successful device-flow/refresh persist per the FEAT-266 field contract, its
  absence on read is always anomalous for this provider.
  - Do NOT change `is_connected()`'s existing fallback semantics unless it also reads from the
    same `o365:*` contract in a way that would produce user-visible regressions — check its
    current callers/tests first (`test_o365_devicecode_resolver.py`) before touching it, and if
    changed, update its docstring to match.
- Update/add unit tests: partial `store_tokens` failure (mock `vault.set` to raise partway
  through a multi-key store) must not result in a subsequent `resolve()` cache-hit; missing
  `expires_at` on a normal read must trigger refresh/device-flow, not a cached return.

**NOT in scope**: building a reactive token-invalidation path for live Graph 401s, any change to
Telegram/jira/fireflies/workiq `VaultTokenSync` call sites' behavior, changes to
`O365OAuthManager.get_valid_token()` internals.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/services/vault_token_sync.py` | MODIFY | Reorder/batch `store_tokens` writes; add partial-write warning log |
| `packages/ai-parrot/src/parrot/auth/oauth2/o365_devicecode_provider.py` | MODIFY | Cache-hit path: missing `expires_at` on read = expired, not forever-valid |
| `packages/ai-parrot/tests/auth/test_o365_devicecode_resolver.py` | MODIFY | Update/add test for missing-`expires_at` = expired |
| `packages/ai-parrot-server/tests/**/test_vault_token_sync*.py` (locate existing test file first; create only if none exists) | MODIFY/CREATE | Partial-write test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports / Signatures (read these before editing)
```python
# packages/ai-parrot-server/src/parrot/services/vault_token_sync.py
class VaultTokenSync:                                            # line 71
    async def _load_vault(self, nav_user_id: str) -> Optional[Any]: ...   # line 107
    async def store_tokens(self, nav_user_id: str, provider: str, tokens: Dict[str, Any]) -> None: ...  # line 131
    async def read_tokens(self, nav_user_id: str, provider: str) -> Optional[Dict[str, Any]]: ...       # line 166

# packages/ai-parrot/src/parrot/auth/oauth2/o365_devicecode_provider.py
async def resolve(self, channel: str, user_id: str) -> Optional[str]: ...   # line 117
    # cache-hit check at line 144-145:
    #   expires_at = self._coerce_epoch(tokens.get("expires_at"))
    #   if expires_at is None or expires_at > time.time() + _EXPIRY_SKEW_SECONDS: ...
async def is_connected(self, channel: str, user_id: str) -> bool: ...      # line 180
    # line 187-188 uses the SAME None-is-valid fallback — read before deciding whether to touch it
```

### Does NOT Exist
- No known bulk/transactional `vault.set()` variant has been confirmed — this must be verified
  by reading the actual vault class returned by `_load_vault` during implementation; do not
  assume one exists or invent an API.
- No existing "partial write" detection/logging in `store_tokens` today — must be added new.

---

## Implementation Notes

### Key Constraints
- Async throughout; `self.logger` for lifecycle; never log token values.
- Must remain backward-compatible for all other `VaultTokenSync` callers (Telegram/jira/
  fireflies/workiq) — do not change `read_tokens()`'s general contract, only how the
  `o365_devicecode_provider.py` resolver interprets a missing `expires_at` for the `o365`
  provider specifically (the fix belongs at the resolver's interpretation layer, not by making
  `read_tokens` itself provider-aware).
- Re-run the full FEAT-266 test suite after this change (`test_o365_devicecode_resolver.py`,
  `test_credentials_devicecode.py`, `test_broker_devicecode.py`, `test_o365_refresh.py`,
  `test_cli_devicecode_e2e.py`) to confirm no regression.

### References in Codebase
- `packages/ai-parrot/src/parrot/auth/oauth2/o365_devicecode_provider.py` — resolver under fix.
- `packages/ai-parrot-server/src/parrot/services/vault_token_sync.py` — persistence under fix.
- `packages/ai-parrot/tests/auth/test_o365_devicecode_resolver.py` — existing test patterns
  (mock `VaultTokenSync`) to extend.

---

## Acceptance Criteria

- [ ] `store_tokens` writes `expires_at` first (or uses a genuine atomic/bulk write if the vault
      supports one) so a partial failure cannot leave `access_token` persisted without
      `expires_at`.
- [ ] A distinguishable warning log fires when `store_tokens` does not persist all expected keys.
- [ ] `O365DeviceCodeCredentialResolver.resolve()`'s cache-hit path treats a missing `expires_at`
      on a freshly-read `o365:*` token set as expired, triggering refresh-or-device-flow instead
      of returning a cached `access_token`.
- [ ] `is_connected()` semantics are either left unchanged (with rationale noted in the
      completion note) or updated consistently with a docstring update — no silent divergence
      between the two methods' interpretation of the same field.
- [ ] All existing FEAT-266 tests pass unmodified in behavior, except any test that explicitly
      asserted the old "missing `expires_at` = valid forever" semantics, which must be updated
      to match the new contract.
- [ ] New tests cover: partial `store_tokens` failure does not yield a cache-hit on next
      `resolve()`; a normal read with `expires_at` missing is treated as expired.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/auth/ -v` and the relevant
      `ai-parrot-server` vault test path.

## Test Specification
```python
async def test_missing_expires_at_on_read_is_treated_as_expired():
    # VaultTokenSync.read_tokens returns {"access_token": "tok", "refresh_token": "rt"}
    # (no expires_at) -> resolve() must NOT return "tok" directly; must attempt refresh
    # (mocked) or device flow, not a silent cache-hit.
    ...

async def test_partial_store_tokens_failure_does_not_leave_forever_valid_token():
    # vault.set raises after writing access_token but before expires_at (or whichever
    # field is written second under the new ordering) -> subsequent read_tokens()
    # must not produce a token set that resolve() treats as a valid cache-hit.
    ...
```

## Output
When complete, the agent must:
1. Move this file to `sdd/tasks/completed/`
2. Update `sdd/tasks/index/o365-devicecode-followups.json` status to "done"
3. Add a brief completion note below

### Completion Note

Implemented as specified. Verified `SessionVault`'s public interface
(`navigator_session.vault.SessionVault`) exposes only
`get`/`set`/`delete`/`keys`/`exists` — no bulk/transactional write
primitive — so the fix is write-ordering, not batching.

`VaultTokenSync.store_tokens` (`vault_token_sync.py`): added a
`_WRITE_FIRST_FIELD = "expires_at"` class constant; the write loop now
writes `expires_at` first (via `sorted(..., key=lambda item: item[0] !=
_WRITE_FIRST_FIELD)`) so a mid-loop failure either leaves `expires_at`
already correctly persisted, or leaves other fields (e.g. `access_token`)
never written at all. Added a `finally` block that compares expected vs.
written keys and logs a distinguishable `"PARTIAL WRITE"` warning
(`logger.warning`, separate from the existing `logger.exception`) whenever
they differ — including total failure (0 written).

`O365DeviceCodeCredentialResolver` (`o365_devicecode_provider.py`):
`resolve()`'s cache-hit check now requires `expires_at is not None` (was
`is None or ...`), i.e. a missing `expires_at` on a freshly-read `o365:*`
token set is treated as expired, triggering refresh-or-device-flow instead
of a silent cache-hit. `is_connected()` was updated to match (same `is not
None and ...` condition) — chose to update rather than leave it diverging,
since both methods read the exact same `o365:*` field contract for the
same provider and no callers/tests anywhere in the repo exercise
`is_connected()`'s prior fallback semantics (grepped; only
`storage/backends/*`'s unrelated `is_connected` properties exist), so there
was no regression risk in making the two consistent. Docstrings on both
methods updated to document the FEAT-267 rationale.

Tests: extended `test_o365_devicecode_resolver.py` with 4 new tests
(missing-`expires_at` triggers refresh; missing-`expires_at` + no
refresh_token falls back to device flow; `is_connected()` false/true
matching the new semantics). No existing test in that file asserted the
old "missing = valid forever" semantics, so none needed changing — all 7
pre-existing tests pass unmodified.

New file `packages/ai-parrot-server/tests/unit/test_vault_token_sync_atomic_persist.py`
(no prior `test_vault_token_sync*.py` existed — verified via `find`) covers:
`expires_at` written first; a failure after 1 successful write (`expires_at`)
never persists `access_token`; the partial-write warning fires on partial
failure; no partial-write warning fires on a fully successful write.

Full FEAT-266 regression suite (`test_o365_devicecode_resolver.py`,
`test_credentials_devicecode.py`, `test_broker_devicecode.py`,
`test_o365_refresh.py`, `test_cli_devicecode_e2e.py`) — 34 tests, all pass.
`ruff check` clean on all touched/created files.
