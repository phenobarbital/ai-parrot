# TASK-4669: Write the owner at link time too (handle_callback → CredentialSink)

**Feature**: FEAT-735 — One owner for the Jira credential
**Spec**: `sdd/specs/services-vault-token-sync-tech-debt.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4668
**Assigned-to**: unassigned
**Discovered-from**: `issue:2e85cce93cab`

---

## Context

Implements **spec §3 Module 1b**, the half of the sink that Q4 added
(spec §8, answered 2026-10-23): the durable owner must be written when a grant
is **minted**, not only when it is refreshed.

Today the sealed write happens in exactly one place — `post_auth_jira`, on the
combined Telegram login. A user who links Jira from MS Teams or Slack gets a
Redis token and **no durable copy at all**. TASK-4668 put the sink behind the
refresh; this task puts the same sink behind the callback, so
`JiraOAuthManager` becomes the single writer of the durable copy wherever a
grant appears (G5).

### The resolution constraint (verified — do not design around it)

`handle_callback` knows the OAuth state payload, and **only the Telegram flow
puts a Navigator user id in it**:

| Flow | What it puts in `extra_state` | Verified at |
|---|---|---|
| Telegram | `nav_user_id`, `nav_display_name`, `nav_email` | `post_auth_jira.py:120` |
| Slack | `channel`, `team_id`, `slack_user_id` — **no Navigator id** | `slack/commands/jira_commands.py:91` |
| MS Teams | `channel`, `user_id` (an **AAD GUID**), `conversation_reference` | `msteams/commands/jira_commands.py:214` |

So the owner is resolved in this order, and the third case is a **no-op, not an
error**:

1. `state_payload["extra"]["nav_user_id"]` — the Telegram flow, and any future
   caller that carries it;
2. `find_user_by_provider_account("jira", token.account_id)` — a **re-link** of
   an Atlassian account that already owns a row;
3. neither ⇒ log at `warning` and return.

Inventing an id for case 3 is exactly what `issue:a671f989e8e7` (a composite
`team:user` string) and `issue:187ce3fe3b93` (an AAD GUID against a `bigint`
cast) already cost this table. Carrying a Navigator id into the Slack / Teams
authorize state is `issue:187ce3fe3b93`'s fix and is **not** this task.

### Why `save_linked_identity` here, and `update_tokens` in TASK-4668

They are mirrors, and swapping them is the bug TASK-4664 shipped:

- **Link time (this task)** has `userinfo` — account id, cloud id, site url,
  display name — so the full sealed write is correct, and it is the call that
  **creates** the row on a first link.
- **Refresh time (TASK-4668)** has no `userinfo`; `save_linked_identity` would
  reset `auth_data` to `_identity_profile(None)` (`store.py:246`) and **wipe**
  `account_id` / `cloud_id` / `site_url` off the row.

---

## Scope

- Add `persist_minted` to the `CredentialSink` Protocol that TASK-4668
  introduces in `jira_oauth.py`.
- Call it from `handle_callback`, after the existing `_write_token` succeeds.
- Implement `persist_minted` on `IdentityVaultCredentialSink` with the
  three-step resolution above.
- Tests for: the happy path, the state-wins-over-lookup order, and the logged
  no-op.

### NOT in scope

- Changing what any channel puts in `extra_state` (that is
  `issue:187ce3fe3b93`).
- The refresh path, the Protocol itself, the ctor parameter or the `manager.py`
  wiring — all TASK-4668.
- Moving any reader (TASK-4670) or removing any writer (TASK-4671).
- `JiraTokenSet` gaining a `nav_user_id` field — see "Does NOT Exist".

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/auth/jira_oauth.py` | MODIFY | `persist_minted` on the Protocol; notify after `_write_token` in `handle_callback` |
| `packages/ai-parrot-server/src/parrot/services/identity_credential_sink.py` | MODIFY | `IdentityVaultCredentialSink.persist_minted` |
| `packages/ai-parrot/tests/unit/test_jira_oauth_manager.py` | MODIFY | Callback notifies the sink; a sink failure does not fail the link |
| `packages/ai-parrot-server/tests/unit/test_identity_credential_sink.py` | MODIFY | Resolution order and the logged no-op |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `52f1ccd2e`, 2026-10-23. Re-grep every anchor before
> editing: TASK-4668 lands in these same two source files first, so line
> numbers WILL have moved by the time this task runs.

### Verified Imports

```python
from parrot.auth.jira_oauth import JiraOAuthManager, JiraTokenSet   # jira_oauth.py:224, :59
from navigator_auth.identity.store import IdentityStore             # store.py:151
from navigator_auth.identity.types import TokenResponse             # identity/types.py
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/auth/jira_oauth.py
class JiraOAuthManager:                                              # line 224
    async def handle_callback(self, code: str, state: str) -> Tuple[JiraTokenSet, Dict[str, Any]]:  # line 439
    async def consume_state(self, state: str) -> Dict[str, Any]:     # line 507 — returns channel / user_id / extra
    @staticmethod
    def _token_key(channel: str, user_id: str) -> str:               # line 354
    async def _write_token(self, key: str, token: JiraTokenSet) -> None:  # line 386

# the state payload handle_callback already holds (built at line 462):
#   state_payload = {"channel": ..., "user_id": ..., "extra": {...}}
#   channel  = state_payload.get("channel")      # line 464
#   user_id  = state_payload.get("user_id")      # line 465 — the CHANNEL's id

# navigator-auth 0.28.8 — verified by introspection on the installed package
class IdentityStore:                                                 # store.py:151
    def __init__(self, db_pool: Any, cipher: Optional[IdentityCipher] = None)   # :153
    async def find_user_by_provider_account(self, provider: str,
                                            provider_user_id: str) -> Optional[Any]    # :497
    async def save_linked_identity(self, user_id: Any, provider: str,
                                   token: TokenResponse,
                                   userinfo: Optional[dict] = None) -> UserIdentity    # :214
    def decrypt_credential(self, identity) -> TokenResponse          # :444 — SYNCHRONOUS

# created by TASK-4668 — this task ADDS a method, it does not rewrite the class
class IdentityVaultCredentialSink:
    def __init__(self, db_pool: Any, provider: str = "jira") -> None: ...
    async def persist(self, channel: str, user_id: str, token: Any) -> None: ...
```

### Edit Sites

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `jira_oauth.py` | MODIFY | `        await self._write_token(self._token_key(channel, user_id), token)` | `jira_oauth.py:498` | 1 (`grep -c`, 2026-10-23) |
| `identity_credential_sink.py` | MODIFY | `    async def persist(self, channel: str, user_id: str, token: Any) -> None:` | created by TASK-4668 | re-grep |

### Does NOT Exist

- ~~`JiraTokenSet.nav_user_id`~~ — the model carries no Navigator id, and must
  not gain one: every token already in Redis would need a migration.
- ~~a Navigator user id in the Slack or MS Teams OAuth state~~ — verified
  absent at the two call sites in the table above. Case 3 is real, not
  theoretical; do not "fix" it by reaching for `state_payload["user_id"]`,
  which is a Slack/Teams channel id and will fail the `bigint` cast
  (`issue:187ce3fe3b93`).
- ~~`IdentityStore.upsert_identity` / `.save` / `.put`~~ — the write API is
  `save_linked_identity` and `update_tokens`, nothing else.
- ~~`await store.decrypt_credential(...)`~~ — **synchronous** (`store.py:444`).
- ~~`IdentityMappingService` being usable from `jira_oauth.py`~~ — it ships
  from `ai-parrot-server`; `ai-parrot` must not import it. The Protocol is
  satisfied structurally and the sink is injected.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/auth/jira_oauth.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/src/parrot/services/identity_credential_sink.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/unit/test_jira_oauth_manager.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/tests/unit/test_identity_credential_sink.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/auth/jira_oauth.py#JiraOAuthManager",
    "sym:packages/ai-parrot/src/parrot/auth/jira_oauth.py#JiraTokenSet",
    "sym:packages/ai-parrot-server/src/parrot/services/identity_credential_sink.py#IdentityVaultCredentialSink"
  ]
}
```

---

## Implementation Notes

- **Order is load-bearing**: the sink runs *after* `_write_token`, never before.
  A Postgres outage must not cost the user a working Redis credential.
- **Never re-raise** (Q2): a sink failure is logged at `error` with channel and
  user, and `handle_callback` still returns `(token, state_payload)`. A link
  that worked for the user must not fail because the durable copy lagged.
- The sink needs the state payload to resolve the owner, so `persist_minted`
  takes it as a parameter. Do not stash it on the manager.
- `ai-parrot` must not import `ai-parrot-server`: the Protocol gains a method,
  the import direction does not change.

---

## Implementation Blueprint

### `packages/ai-parrot/src/parrot/auth/jira_oauth.py` (MODIFY)

```python
# MODIFY — add to the CredentialSink Protocol that TASK-4668 creates.
# occurrences: re-grep `class CredentialSink(Protocol):` (created by TASK-4668)
class CredentialSink(Protocol):
    ...  # persist() — TASK-4668

    async def persist_minted(
        self,
        channel: str,
        user_id: str,
        token: "JiraTokenSet",
        state_payload: Dict[str, Any],
    ) -> None:
        """Persist a freshly minted grant. Raises on failure.

        ``state_payload`` is the decoded OAuth state; the implementation reads
        ``extra.nav_user_id`` from it when the channel supplied one.
        """
        ...
```

```python
# AFTER — insert below `await self._write_token(self._token_key(channel, user_id), token)`
# (verified: packages/ai-parrot/src/parrot/auth/jira_oauth.py:498)
# occurrences: 1 (verified: grep -c, 2026-10-23)

# FILL IN: notify the sink, mirroring TASK-4668's refresh-side block —
#   if self._credential_sink is not None:
#       try:
#           await self._credential_sink.persist_minted(channel, user_id, token, state_payload)
#       except Exception:
#           self.logger.error("Jira credential sink failed at link time for %s:%s",
#                             channel, user_id, exc_info=True)
# Never re-raise and never move the _write_token call above it: the durable
# write is strictly downstream of the hot write. Bounded by AC-1, AC-3.
```

**Why**: `handle_callback` is the only place a grant is minted, for every
channel, so one call here covers Telegram, Slack and MS Teams at once —
whereas `post_auth_jira` only ever saw the Telegram flow.

### `packages/ai-parrot-server/src/parrot/services/identity_credential_sink.py` (MODIFY)

```python
# AFTER — insert below `async def persist(...)` (created by TASK-4668; re-grep)
    async def persist_minted(
        self,
        channel: str,
        user_id: str,
        token: Any,
        state_payload: Dict[str, Any],
    ) -> None:
        """Seal a newly minted grant on the owner's identity row.

        Resolution order: the Navigator id carried in the OAuth state, else the
        Atlassian account's existing row, else a logged no-op.
        """
        # FILL IN: resolve, then write — bounded by AC-2, AC-4, AC-5.
        #   nav_user_id = (state_payload.get("extra") or {}).get("nav_user_id")
        #   if not nav_user_id:
        #       nav_user_id = await store.find_user_by_provider_account(
        #           self._provider, token.account_id)
        #   if not nav_user_id:
        #       self.logger.warning(
        #           "Jira link for %s:%s carries no Navigator user and account %s "
        #           "owns no identity row — durable copy skipped",
        #           channel, user_id, token.account_id)
        #       return
        #   await store.save_linked_identity(
        #       user_id=nav_user_id, provider=self._provider,
        #       token=TokenResponse(...),         # same shape TASK-4668 builds
        #       userinfo={"account_id": ..., "cloud_id": ..., "site_url": ...,
        #                 "display_name": ..., "email": ...})
        # Use save_linked_identity, NOT update_tokens: at link time there IS
        # userinfo, and this call must create the row on a first link.
```

**Why**: the state-first order matters — on a Telegram re-link the account
lookup would also succeed, but the state is the authoritative answer for *this*
login, and it is the only one that works when the account has no row yet.

### Steps (in order)

1. Add `persist_minted` to the Protocol — the manager must type-check against
   it before anything calls it.
2. Add the notify block under `jira_oauth.py:498`, copying TASK-4668's
   try/except shape so both call sites fail identically.
3. Implement `persist_minted` on the sink with the three-step resolution.
4. Write the four tests below; run them.

### FILL IN checklist

- [ ] `persist_minted` on the `CredentialSink` Protocol; AC-1
- [ ] the notify block after `_write_token` in `handle_callback`; AC-1, AC-3
- [ ] `IdentityVaultCredentialSink.persist_minted` resolution order; AC-2, AC-4
- [ ] the logged no-op when neither source resolves; AC-5

---

## Acceptance Criteria

- [ ] AC-1 `handle_callback` notifies the sink **after** a successful
      `_write_token`, and only then
- [ ] AC-2 a minted grant reaches the owner's row on a channel that is **not**
      Telegram, given a resolvable Atlassian account (G5)
- [ ] AC-3 a sink that raises does not change `handle_callback`'s return value
      and does not prevent the Redis write; the failure is logged at `error`
- [ ] AC-4 `extra.nav_user_id` in the state **wins** over the account lookup
- [ ] AC-5 no `nav_user_id` and no matching account ⇒ no write, no exception,
      exactly one `warning`
- [ ] AC-6 `credential_sink=None` leaves `handle_callback` byte-identical to
      today

---

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/test_jira_oauth_manager.py -q`
- `pytest packages/ai-parrot-server/tests/unit/test_identity_credential_sink.py -q`

---

## Test Specification

| Test | File | Description |
|---|---|---|
| `test_link_notifies_sink` | `test_jira_oauth_manager.py` | Callback writes Redis AND calls `persist_minted` with the minted grant |
| `test_link_survives_sink_failure` | `test_jira_oauth_manager.py` | A raising sink leaves the return value and the Redis write intact |
| `test_link_resolves_nav_user_from_state` | `test_identity_credential_sink.py` | `extra.nav_user_id` wins; `find_user_by_provider_account` is not called |
| `test_link_without_nav_user_is_a_logged_noop` | `test_identity_credential_sink.py` | No id, no account row ⇒ `save_linked_identity` never called, one warning, no raise |

Use the `recording_sink` fixture pattern from spec §4; the real-Postgres case
stays behind `IDENTITY_PG_DSN` like TASK-4668's.

---

## Agent Instructions

TASK-4668 edits the same two source files **first**. Re-grep every anchor
before you edit — the line numbers in this contract are from `dev` @
`52f1ccd2e`, before TASK-4668 landed. Do not reorder, rewrite or "improve"
TASK-4668's `persist`; add `persist_minted` beside it. Touch no other file.

---

## Completion Note

**Completed 2026-10-23** (verification: verified).

`handle_callback` notifies the sink after its existing `_write_token`, with
the same try/except/log-at-error shape as the refresh path, and
`IdentityVaultCredentialSink.persist_minted` implements the three-step
resolution: state `extra.nav_user_id` → `find_user_by_provider_account` →
logged no-op. Link time calls `save_linked_identity` (it has the userinfo and
must create the row); refresh keeps `update_tokens`.

**Evidence**: `pytest test_jira_oauth_manager.py test_identity_credential_sink.py -q`
→ 53 passed (8 new: 3 manager, 5 sink); `ruff check` clean.

**Verified, not assumed** — the claim that only Telegram carries a Navigator
id was checked at all three call sites before writing the fallback:
`post_auth_jira.py:120` sets `extra_state["nav_user_id"]`;
`slack/commands/jira_commands.py:91` sends `team_id`/`slack_user_id`;
`msteams/commands/jira_commands.py:214` sends the AAD object id. The gap for
a first-ever Slack/Teams link therefore stands and is documented, not closed:
it needs those flows to carry a Navigator id (`issue:187ce3fe3b93`).

**Deviation**: none from the blueprint. The task's `_persist_to_sink` helper
idea was not used — both call sites keep their own inline block, matching
TASK-4668's shipped shape, so the two paths read identically.
