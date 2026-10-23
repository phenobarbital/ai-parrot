# TASK-4671: Retire the two redundant Jira credential writers in post_auth_jira

**Feature**: FEAT-735 — One owner for the Jira credential
**Spec**: `sdd/specs/services-vault-token-sync-tech-debt.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (1-2h)
**Depends-on**: TASK-4669, TASK-4670
**Assigned-to**: unassigned
**Discovered-from**: `issue:2e85cce93cab`

---

## Context

Implements **spec §3 Module 3**, widened by Q4. `JiraPostAuthProvider` is the
Telegram combined-login hook, and it writes the Jira credential **twice**:

1. `_store_in_vault` (`post_auth_jira.py:189` → `:222`) → `VaultTokenSync` →
   `auth.user_vault_secrets`, as flat `jira:*` keys. Its only reader was the
   integrations badge, which **TASK-4670 moved** onto the owner. After that
   task, nothing reads this copy.
2. `_write_identity_records` passes `token=_build_token_response(token_set)`
   (`post_auth_jira.py:285`) → `IdentityStore.save_linked_identity` → the
   owner's own row. **TASK-4669 now does this** for every channel, from
   `handle_callback`.

Both are redundant once their respective predecessor task lands, and leaving
them is not harmless: two writers of one credential is precisely the defect
`issue:2e85cce93cab` reports. Removing only the vault copy would move the two
writers *inside* the owner's table rather than remove them.

What stays: the **mapping** row. `_write_identity_records` still upserts the
`jira` identity with its non-secret `auth_data` (account id, cloud id, site
url, display name) and still upserts the `telegram` identity — those rows are
FEAT-729's channel mappings, not credentials.

---

## Scope

- Delete the `_store_in_vault` call site and the now-dead method.
- Drop `token=` from the `jira` upsert; keep the upsert and all its non-secret
  fields.
- Keep the `vault_sync` constructor parameter (its construction sites are out
  of scope) and say in its docstring that it is retained for the disconnect
  path only.
- Tests proving neither write happens and the mapping rows are unchanged.

### NOT in scope

- `VaultTokenSync` itself, or any of its fireflies / workiq / entra / o365
  callers — untouched, their tests must still pass.
- Deleting the `jira:*` keys already in users' vaults. Q3 (spec §8) decided:
  **leave them**, inert once unread.
- The `telegram` identity upsert.
- Changing `JiraPostAuthProvider.__init__`'s signature.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/post_auth_jira.py` | MODIFY | Remove the vault write and the `token=` argument |
| `packages/ai-parrot/tests/unit/test_post_auth_jira.py` | MODIFY | No vault write, no sealed token, mapping rows intact |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `52f1ccd2e`, 2026-10-23.
> `sha256(post_auth_jira.py) = 5717e109c465cfbc3c25…`

### Verified Imports

```python
from parrot.auth.jira_oauth import JiraTokenSet              # TYPE_CHECKING in this file
from parrot.services.vault_token_sync import VaultTokenSync  # post_auth_jira.py:34, TYPE_CHECKING
```

### Existing Signatures to Use

```python
# packages/ai-parrot-integrations/src/parrot/integrations/telegram/post_auth_jira.py
class JiraPostAuthProvider:
    def __init__(self, ..., vault_sync: "VaultTokenSync", ...) -> None:  # line 76
        self._vault = vault_sync                                          # line 80
    async def handle_result(...)                                          # the caller
        await self._store_in_vault(nav_user_id, token_set)                # line 189 — DELETE
        await self._write_identity_records(...)                           # line 192 — KEEP
    async def _store_in_vault(self, nav_user_id: Optional[str],
                              token_set: "JiraTokenSet") -> None:         # line 222 — DELETE
        await self._vault.store_tokens(nav_user_id=..., provider=self.provider_name,
                                       tokens={...})                      # line 239
    async def _write_identity_records(self, nav_user_id, token_set,
                                      session, primary_auth_data) -> None:  # line 253
        await self._identity.upsert_identity(..., auth_provider="telegram", ...)  # line 269 — KEEP
        await self._identity.upsert_identity(                             # line 279 — KEEP
            ..., auth_provider=self.provider_name,
            provider_user_id=token_set.account_id,
            token=_build_token_response(token_set),                       # line 285 — DELETE THIS ARG
            auth_data={...}, display_name=..., email=...)
```

`self._vault` occurs exactly twice in the file (`:80` assignment, `:239` use);
deleting `_store_in_vault` leaves only the assignment, which is intentional.

### Edit Sites

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `post_auth_jira.py` | MODIFY | `        await self._store_in_vault(nav_user_id, token_set)` | `:189` | 1 (`grep -c`, 2026-10-23) |
| `post_auth_jira.py` | MODIFY | `    async def _store_in_vault(` | `:222` | 1 |
| `post_auth_jira.py` | MODIFY | `                token=_build_token_response(token_set),` | `:285` | 1 |

> **Note**: spec §6 lists this last anchor at `:279`. The verified line is
> **`:285`** (`grep -n`, 2026-10-23) — the spec's number was off; the anchor
> text is correct and unique. Use the anchor, not the number.

### Does NOT Exist

- ~~another caller of `_store_in_vault`~~ — one call site, line 189
  (`grep -c`, 2026-10-23). Deleting the method breaks nothing else.
- ~~a Jira reader of `auth.user_vault_secrets` after TASK-4670~~ — the badge
  was the last one. Re-verify with `grep -rn "read_tokens\|read_tokens_result"`
  before deleting, and STOP if a new reader appeared.
- ~~`VaultTokenSync` being Jira-specific~~ — `provider` is just a key prefix;
  fireflies / workiq / entra / o365 pass their own. Do not touch the class.
- ~~`_build_token_response` being used elsewhere in the file~~ — verify with
  `grep -c "_build_token_response"`; if line 285 is its only *call*, the helper
  becomes dead and should go with it. If it has another caller, keep it.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-integrations/src/parrot/integrations/telegram/post_auth_jira.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/unit/test_post_auth_jira.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/telegram/post_auth_jira.py#JiraPostAuthProvider"
  ]
}
```

---

## Implementation Notes

- **Order matters across tasks, not inside this one.** Both removals are safe
  only because TASK-4670 moved the reader and TASK-4669 moved the writer. If
  either is not `done` when you start, stop and say so.
- Keep `vault_sync` in `__init__`: changing the signature would ripple into
  construction sites this task does not own.
- The `jira` upsert keeps `provider_user_id=token_set.account_id` — that is the
  key TASK-4669's sink resolves on. Removing it would strand the sink.

---

## Implementation Blueprint

### `packages/ai-parrot-integrations/src/parrot/integrations/telegram/post_auth_jira.py` (MODIFY)

```python
# DELETE — the call site
# anchor: `        await self._store_in_vault(nav_user_id, token_set)`
# (verified: post_auth_jira.py:189) occurrences: 1
#
# Also delete the two comment lines above it:
#   `        # Best-effort Vault write. The JiraOAuthManager already wrote to Redis.`
# FILL IN: remove the call and its comment; leave the `_write_identity_records`
# call below untouched. Bounded by AC-1.

# DELETE — the whole method
# anchor: `    async def _store_in_vault(` (verified: post_auth_jira.py:222) occurrences: 1
# FILL IN: remove the method through the end of its `except` block (the next
# `async def _write_identity_records(` is the boundary). Bounded by AC-1, AC-4.

# MODIFY — the jira upsert loses its credential argument
# anchor: `                token=_build_token_response(token_set),`
# (verified: post_auth_jira.py:285) occurrences: 1
# FILL IN: delete that one line, and the two comment lines above it that
# explain the ciphering. Every other argument of the upsert stays exactly as
# it is. Bounded by AC-2, AC-3.
```

**Why**: the credential now has exactly one writer — the sink behind
`JiraOAuthManager` — while the mapping row keeps the non-secret identity data
the Telegram session needs for prompt enrichment.

```python
# MODIFY — the constructor docstring, so the retained parameter is explained
# anchor: `        vault_sync: :class:`VaultTokenSync` for encrypted token persistence.`
# (verified: post_auth_jira.py:67) occurrences: 1
# FILL IN: reword to say the Jira credential is owned by the Identity Vault
# (FEAT-735) and this parameter is retained for the disconnect path only.
# Bounded by AC-5.
```

### Steps (in order)

1. Confirm TASK-4669 and TASK-4670 are `done` in the per-spec index; stop if
   not.
2. Re-grep for any new reader of the Jira vault keys; stop if one appeared.
3. Delete the call site, then the method, then the `token=` argument.
4. Check whether `_build_token_response` still has a caller; remove it only if
   it does not.
5. Update the tests and run them.

### FILL IN checklist

- [ ] `_store_in_vault` call site and method removed; AC-1
- [ ] `token=` dropped from the `jira` upsert, every other argument intact; AC-2, AC-3
- [ ] `_build_token_response` removed **only** if it has no other caller; AC-4
- [ ] constructor docstring explains the retained `vault_sync`; AC-5

---

## Acceptance Criteria

- [ ] AC-1 The combined Telegram login writes **no** `jira:*` key to
      `auth.user_vault_secrets`
- [ ] AC-2 The `jira` identity upsert passes **no** `token=`, and still passes
      `provider_user_id`, `auth_data`, `display_name` and `email`
- [ ] AC-3 The `telegram` identity upsert is **unchanged**
- [ ] AC-4 No dead code is left behind: `_store_in_vault` is gone, and
      `_build_token_response` is gone iff it has no remaining caller
- [ ] AC-5 `JiraPostAuthProvider.__init__`'s signature is unchanged and its
      docstring explains why `vault_sync` is retained
- [ ] AC-6 `VaultTokenSync`'s other providers are untouched and
      `test_vault_token_sync_f4_regression.py` still passes

---

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/test_post_auth_jira.py -q`
- `pytest packages/ai-parrot-server/tests/unit/test_vault_token_sync_f4_regression.py -q`

---

## Test Specification

| Test | File | Description |
|---|---|---|
| `test_jira_not_written_to_session_vault` | `test_post_auth_jira.py` | `store_tokens` is never called for `jira` on a combined login |
| `test_post_auth_jira_upsert_carries_no_token` | `test_post_auth_jira.py` | The `jira` upsert kwargs contain no `token`, and still carry `auth_data` + `provider_user_id` |
| `test_telegram_identity_upsert_unchanged` | `test_post_auth_jira.py` | The `telegram` upsert call is byte-identical to today's |
| _(existing suite)_ | `test_vault_token_sync_f4_regression.py` | Not modified — run as a regression guard that fireflies / o365 vault writes are unchanged |

---

## Agent Instructions

This is a deletion task: remove exactly the three things listed and nothing
else. Do not refactor `_write_identity_records`, do not touch `VaultTokenSync`,
do not change the constructor signature, and do not delete anyone's existing
vault data.

---

## Completion Note

**Completed 2026-10-23** (verification: verified).

All three removals plus the dead helper: the `_store_in_vault` call site and
method, `token=` on the `jira` upsert, and `_build_token_response` (its only
caller was that argument — confirmed by `grep -rn` across `packages/*/src`
before deleting, per AC-4). The now-unused `from datetime import ...` went
with it. `vault_sync` stays on the constructor, documented as retained for
the disconnect path.

**Pre-deletion safety check (the task's step 2), done and recorded**: no
reader of the Jira Session Vault copy remains.
`integrations/mcp/fireflies_a2a.py:117` reads its own `PROVIDER`;
`auth/broker/factory.py:237,260` are the generic `static_key` / `mcp`
resolvers, keyed by a configured `vault_key` that defaults to
`<provider>:api_key` / `<provider>:token` — neither matches the flat keys
this provider wrote, and their `vault` object has a different `read_tokens`
signature entirely. `service.py:273` is the vault branch TASK-4670 left for
non-Jira providers.

**Three existing tests asserted the write that is now gone** and were
rewritten rather than deleted: `test_vault_called_with_jira_provider_and_flat_keys`
became `test_jira_not_written_to_session_vault` (same subject, inverted
expectation, with the reasoning in its docstring);
`test_returns_true_on_clean_exchange` now asserts `store_tokens` is *not*
awaited; `test_falls_back_to_extra_state_user_id` asserts the fallback on the
identity rows, since the vault call it used to read is gone. Added
`test_post_auth_jira_upsert_carries_no_token`.

**Evidence**: `pytest test_post_auth_jira.py test_vault_token_sync_f4_regression.py -q`
→ 20 passed. Whole feature contract (7 files) → **101 passed, 6 skipped**
(the skips are the real-Postgres cases, gated on `IDENTITY_PG_DSN`).
`ruff check` clean.
