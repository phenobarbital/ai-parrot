# TASK-4668: Propagate a refreshed Jira grant to the Identity Vault (CredentialSink)

**Feature**: FEAT-735 — One owner for the Jira credential
**Spec**: `sdd/specs/services-vault-token-sync-tech-debt.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: `issue:2e85cce93cab`

---

## Context

Implements **spec §3 Module 1**. Closes the live half of
`issue:2e85cce93cab`: `JiraOAuthManager._refresh_tokens`
(`jira_oauth.py:642`) writes the rotated grant to **Redis only**
(`_write_token`, `jira_oauth.py:386`) and returns. Nothing else is notified,
so every Atlassian token rotation strands the durable copy in
`auth.user_identities` that FEAT-729 / TASK-4664 started writing — a sealed
credential that silently stops matching the real one, with no detector.

Q1 is answered (spec §8): **the Identity Vault is the durable owner, Redis
stays the hot cache.** This task does not move any reader (that is M2) and
does not retire the Session Vault's Jira path (M3). It only makes the owner
current.

### The two findings that decide the implementation

1. **`_refresh_tokens` does not know the Navigator user.** Its `user_id`
   argument is the **channel's** id (a Telegram id, an AAD object id) — see
   `_token_key(channel, user_id)` at `jira_oauth.py:354` — and
   `JiraTokenSet` has no `nav_user_id` field. The sink therefore resolves the
   owner from the Atlassian account id, which both sides do have:
   `IdentityStore.find_user_by_provider_account("jira", token.account_id)`
   returns the Navigator `user_id` of the enabled identity for that account.
2. **A refresh must call `update_tokens`, never `save_linked_identity`.**
   `save_linked_identity` sets `auth_data` to `_identity_profile(userinfo)`
   (`store.py:246`), so calling it on a refresh with no `userinfo` would
   **wipe** `account_id` / `cloud_id` / `site_url` off the row.
   `update_tokens` (`store.py:408`) re-seals only the token columns and
   leaves `auth_data` untouched.

---

## Scope

- Add a `CredentialSink` Protocol and an optional `credential_sink` constructor
  argument to `JiraOAuthManager`.
- Notify the sink from `_refresh_tokens`, **after** the Redis write succeeds.
  A sink failure is logged at `error` and never changes the return value
  (spec Q2).
- Add `IdentityVaultCredentialSink` in **ai-parrot-server**, which resolves the
  Navigator user from `token.account_id` and re-seals the rotated grant with
  `IdentityStore.update_tokens`.
- Wire the sink at both `JiraOAuthManager(...)` construction sites in
  `integrations/manager.py`, only when `app["authdb"]` exists.

**NOT in scope**: moving `OAuth2Service._token_status` onto the owner (M2);
removing the Session Vault's Jira write (M3); the ownership doc (M4);
notifying the sink from `handle_callback` at link time (spec §8 Q4 — still
open, do not implement it here); any change to `VaultTokenSync` or to the
fireflies / workiq / entra / o365 paths.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/auth/jira_oauth.py` | MODIFY | `CredentialSink` Protocol, `credential_sink` ctor arg, notify after `_write_token` |
| `packages/ai-parrot-server/src/parrot/services/identity_credential_sink.py` | CREATE | `IdentityVaultCredentialSink` |
| `packages/ai-parrot-integrations/src/parrot/integrations/manager.py` | MODIFY | Pass the sink at both construction sites |
| `packages/ai-parrot/tests/unit/test_jira_oauth_manager.py` | MODIFY | Sink notified / failure tolerated / absent-sink parity |
| `packages/ai-parrot-server/tests/unit/test_identity_credential_sink.py` | CREATE | Sink unit + real-Postgres round trip |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `origin/dev` @ `899d1fe59` (after the FEAT-729 merge),
> 2026-10-23. Re-grep every anchor before editing.

### Verified Imports

```python
from parrot.auth.jira_oauth import JiraOAuthManager, JiraTokenSet   # jira_oauth.py:224, :59
from navigator_auth.identity.store import IdentityStore             # store.py:151
from navigator_auth.identity.types import TokenResponse             # identity/types.py
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/auth/jira_oauth.py
_REFRESH_LOCK_TIMEOUT = 10            # line 44 — seconds the lock is held
_REFRESH_LOCK_BLOCKING_TIMEOUT = 5    # line 45

class JiraTokenSet(BaseModel):                                   # line 59
    access_token: str
    refresh_token: str
    expires_at: float                 # epoch seconds, NOT a datetime
    cloud_id: str
    site_url: str
    account_id: str                   # the Atlassian account — the sink's key
    display_name: str
    email: Optional[str] = None
    scopes: List[str]
    granted_at: float = 0.0
    last_refreshed_at: float = 0.0

class JiraOAuthManager:                                          # line 224
    def __init__(self, client_id: str, client_secret: str, redirect_uri: str, *,
                 app: Optional[web.Application] = None,
                 redis_url: Optional[str] = None,
                 redis_client: Any = None,
                 scopes: Optional[List[str]] = None,
                 http_session: Optional[aiohttp.ClientSession] = None) -> None:
        # all optionals are keyword-only — add credential_sink to that group
    @staticmethod
    def _token_key(channel: str, user_id: str) -> str:           # line 354
    async def _write_token(self, key: str, token: JiraTokenSet) -> None:   # line 386
    async def _refresh_tokens(self, channel, user_id, token_set) -> JiraTokenSet:  # line 642

# navigator-auth 0.28.8
class IdentityStore:                                             # store.py:151
    def __init__(self, db_pool: Any, cipher: Optional[IdentityCipher] = None)      # :153
    async def find_user_by_provider_account(self, provider: str,
                                            provider_user_id: str) -> Optional[Any]  # :497
    async def get_for_provider_account(self, user_id: Any, provider: str,
                                       provider_user_id: Optional[str]) -> Optional[UserIdentity]
    async def update_tokens(self, identity: UserIdentity,
                            token: TokenResponse) -> UserIdentity   # :408
    def decrypt_credential(self, identity) -> TokenResponse         # :444 — SYNCHRONOUS

# packages/ai-parrot-integrations/src/parrot/integrations/manager.py
jira_oauth_manager = JiraOAuthManager(                           # lines 338 and 896 — 2 sites
    client_id=config.jira_client_id,
    client_secret=config.jira_client_secret,
    redirect_uri=config.jira_redirect_uri,
    app=app,
)
```

### The exact edit site in `_refresh_tokens`

```python
# jira_oauth.py, inside the lock's try block, at the END of the happy path:
            await self._write_token(key, refreshed)
            return refreshed            # <- the sink call goes between these two
```

### Does NOT Exist

- ~~`JiraTokenSet.nav_user_id`~~ — the model has no Navigator user id; see
  finding 1. Do not add one: the account id already resolves the owner, and a
  new field would need a Redis migration for every stored token.
- ~~`IdentityStore.upsert_identity` / `.save` / `.put`~~ — the write API is
  `save_linked_identity` and `update_tokens`, nothing else.
- ~~`await store.decrypt_credential(...)`~~ — it is **synchronous**
  (`store.py:444`). Awaiting it raises `TypeError: object TokenResponse can't
  be used in 'await' expression` (TASK-4664 hit exactly this).
- ~~an existing `CredentialSink` / `credential_sink` anywhere~~ — this task
  introduces the name. `parrot.auth.credentials.CredentialResolver` is the
  unrelated *read* abstraction; do not extend it.
- ~~importing `parrot.services.*` from `parrot.auth.jira_oauth`~~ —
  `ai-parrot` must not import `ai-parrot-server`. The Protocol is satisfied
  structurally; the concrete sink is injected by the application.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/auth/jira_oauth.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/src/parrot/services/identity_credential_sink.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-integrations/src/parrot/integrations/manager.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/unit/test_jira_oauth_manager.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/tests/unit/test_identity_credential_sink.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/auth/jira_oauth.py#JiraOAuthManager._refresh_tokens",
    "sym:packages/ai-parrot/src/parrot/auth/jira_oauth.py#JiraOAuthManager.__init__",
    "sym:packages/ai-parrot-server/src/parrot/services/identity_credential_sink.py#IdentityVaultCredentialSink"
  ]
}
```

---

## Implementation Notes

### Ordering is load-bearing
Redis is written first and the sink second. The reverse would let a Postgres
outage cost the user a working hot credential — and Redis is the live read
path for `JiraToolkit`. The sink call sits inside the existing refresh lock,
immediately after `_write_token`: it is one indexed lookup plus one update,
well inside `_REFRESH_LOCK_TIMEOUT` (10 s). Do **not** restructure the lock.

### Failure policy (spec Q2)
`except Exception` around the sink call, logged at `error` with channel, user
and account id — then carry on and return `refreshed`. This is the one place
a broad except is correct here, and it must be loud: a silent
`logger.exception` on an identity write is what hid `issue:0115386145f2` for
the lifetime of that code.

### The sink resolves the owner, the manager does not
`persist(channel, user_id, token)` keeps `channel`/`user_id` for log context
only. The lookup key is `token.account_id`. When
`find_user_by_provider_account` returns `None` the user linked Jira before
FEAT-729 and has no row: log at `warning` and return — it is not an error,
and the sink must not create a row (a create needs the `userinfo` a refresh
does not carry).

### `expires_at` conversion
`JiraTokenSet.expires_at` is an **epoch float**; `TokenResponse.expires_at`
is an aware datetime. `JiraPostAuthProvider._as_token_response`
(`post_auth_jira.py`) already does this mapping — reuse that shape rather
than inventing a second one.

### Wiring
Both sites in `manager.py` construct the manager with `app=app` inside a
`try/except` that only warns. Build the sink from `app.get("authdb")` and
pass `credential_sink=...` only when the pool exists, so a deployment without
`authdb` keeps today's behaviour instead of failing to construct the manager.

---

## Implementation Blueprint

### `packages/ai-parrot/src/parrot/auth/jira_oauth.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -c '            await self._write_token(key, refreshed)' …/jira_oauth.py)
# AFTER — add near the other module-level types:

class CredentialSink(Protocol):
    """Durable store kept in step with the Redis hot cache.

    Implemented structurally — ``ai-parrot`` must not import
    ``ai-parrot-server``, where the Identity Vault implementation lives.
    """

    async def persist(self, channel: str, user_id: str, token: "JiraTokenSet") -> None:
        """Persist a freshly refreshed grant. Raises on failure."""
        ...

# FILL IN: add `credential_sink: Optional[CredentialSink] = None` to the
# keyword-only group of __init__ (line ~237) and store it as
# `self._credential_sink`. Default None must keep every existing
# construction site byte-identical. Bounded by AC-4.

# FILL IN: in _refresh_tokens, between `await self._write_token(key, refreshed)`
# and `return refreshed`, notify the sink:
#   if self._credential_sink is not None:
#       try: await self._credential_sink.persist(channel, user_id, refreshed)
#       except Exception: self.logger.error(..., exc_info=True)
# Never re-raise; never move the _write_token call. Bounded by AC-1, AC-2, AC-3.
```

### `packages/ai-parrot-server/src/parrot/services/identity_credential_sink.py` (CREATE)

```python
class IdentityVaultCredentialSink:
    """``CredentialSink`` backed by navigator-auth's Identity Vault."""

    def __init__(self, db_pool: Any, provider: str = "jira") -> None:
        """``db_pool``: the asyncdb ``authdb`` pool (``app['authdb']``)."""

    async def persist(self, channel: str, user_id: str, token: Any) -> None:
        """Re-seal the rotated grant on the owner's identity row.

        Resolves the Navigator user from ``token.account_id``; a miss is a
        logged no-op. Uses ``update_tokens`` so ``auth_data`` is preserved.
        """
        # FILL IN:
        #   nav_user_id = await store.find_user_by_provider_account(provider, token.account_id)
        #   if nav_user_id is None: log warning; return
        #   identity = await store.get_for_provider_account(nav_user_id, provider, token.account_id)
        #   if identity is None: log warning; return
        #   await store.update_tokens(identity, TokenResponse(...))
        # Bounded by AC-2, AC-5, AC-6.
```

### FILL IN checklist
- [ ] `CredentialSink` Protocol + ctor arg + stored attribute; bounded by AC-4
- [ ] the notify block in `_refresh_tokens`, after `_write_token`; AC-1, AC-3
- [ ] `IdentityVaultCredentialSink.persist`; AC-2, AC-5, AC-6
- [ ] both `manager.py` wiring sites, guarded on `app["authdb"]`; AC-7

---

## Acceptance Criteria

- [ ] AC-1 `_refresh_tokens` notifies the sink **after** a successful
      `_write_token`, and only then
- [ ] AC-2 after a refresh, the identity row's sealed credential decrypts to
      the **refreshed** access token (the drift this task closes), proven
      against real Postgres
- [ ] AC-3 a sink that raises does not change `_refresh_tokens`' return value,
      and the failure is logged at `error`
- [ ] AC-4 `credential_sink=None` (every existing construction site) behaves
      exactly as before — Redis only, no new calls
- [ ] AC-5 `auth_data` (`account_id` / `cloud_id` / `site_url`) is **unchanged**
      by a refresh — the `update_tokens`-not-`save_linked_identity` guarantee
- [ ] AC-6 an account with no identity row is a logged no-op: no row is
      created, no exception escapes
- [ ] AC-7 both `manager.py` sites pass the sink when `app["authdb"]` exists,
      and construct the manager unchanged when it does not
- [ ] `pytest packages/ai-parrot/tests/unit/test_jira_oauth_manager.py -q` passes
- [ ] `ledger issue:2e85cce93cab` keeps its remaining scope (M2–M4) and is NOT
      closed by this task alone

---

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/test_jira_oauth_manager.py -q`
- `pytest packages/ai-parrot-server/tests/unit/test_identity_credential_sink.py -q`
- `pytest packages/ai-parrot/tests/unit/test_post_auth_jira.py -q`
- `pytest packages/ai-parrot/tests/unit/test_identity_mapping.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/test_jira_oauth_manager.py (extend)

class TestRefreshCredentialSink:
    async def test_sink_notified_after_redis_write(self):
        """The sink sees the refreshed grant, and only after _write_token."""
        # FILL IN: recording sink + a stub asserting call order

    async def test_sink_failure_does_not_break_refresh(self):
        """A raising sink is logged at error; the refreshed token still returns."""
        # FILL IN: caplog at ERROR

    async def test_no_sink_is_redis_only(self):
        """credential_sink=None performs no extra call (AC-4)."""
        # FILL IN


# packages/ai-parrot-server/tests/unit/test_identity_credential_sink.py (new)

class TestIdentityVaultCredentialSink:
    async def test_refreshed_token_round_trips(self, authdb_pool):
        """decrypt_credential returns the REFRESHED access token (AC-2)."""
        # FILL IN: link a row, persist a rotated grant, decrypt. Real Postgres,
        # unique provider per run, skip when IDENTITY_PG_DSN is unset — follow
        # packages/ai-parrot/tests/unit/test_identity_mapping.py.

    async def test_auth_data_survives_a_refresh(self, authdb_pool):
        """account_id/cloud_id/site_url are untouched (AC-5) — the
        save_linked_identity trap."""
        # FILL IN

    async def test_unknown_account_is_a_noop(self, authdb_pool):
        """No row for the account: warning, no insert, no raise (AC-6)."""
        # FILL IN
```

---

## Agent Instructions

1. **Work in the feature worktree** — never on `dev`:
   `python -m scripts.sdd.ensure_worktree --slug services-vault-token-sync-tech-debt --feature-id FEAT-735`
2. **Read the spec** — especially §3 M1 and §8 Q1/Q2, which are now answered.
3. **Check dependencies** — none; this task is the first of FEAT-735.
4. **Verify the Codebase Contract** before writing code. It was taken on
   `origin/dev @ 899d1fe59`, right after the FEAT-729 merge; re-grep every
   anchor.
5. **Update status** in `sdd/tasks/index/services-vault-token-sync-tech-debt.json`
   → `"in-progress"` with `started_at`, and commit only that file.
6. **Implement** from the Blueprint; complete every `# FILL IN:`.
7. **Validate** with the commands above and
   `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src:packages/ai-parrot-integrations/src`
   (the shared `.venv` is editable-installed against the MAIN checkout).
   The real-Postgres tests need `IDENTITY_PG_DSN`.
8. **Commit the code** — stage only the files this task lists.
9. **Close the task**:
   `scripts/sdd/close_task.sh TASK-4668 services-vault-token-sync-tech-debt verified`
10. **Fill in the Completion Note**, then commit the staged SDD state.

---

## Completion Note

**Completed 2026-10-23** (verification: verified) — commit `e8f043d0f`.

Implemented as specified. Three pieces:

1. `jira_oauth.py` — a `CredentialSink` Protocol (structural, so `ai-parrot`
   keeps no import of `ai-parrot-server`), a keyword-only `credential_sink`
   constructor argument stored as `self._credential_sink`, and a notify block
   between `await self._write_token(key, refreshed)` and `return refreshed`.
   The block swallows every exception and logs at `error` with channel + user.
2. `identity_credential_sink.py` (new) — `IdentityVaultCredentialSink`,
   resolving the Navigator user with `find_user_by_provider_account` and
   re-sealing with `update_tokens`. A token with no `account_id`, an account
   with no owner, or a missing provider row are each a logged no-op.
3. `manager.py` — `_build_jira_credential_sink(app)` guarded on
   `app["authdb"]`, passed at both construction sites (MS Teams, Slack).

**Evidence**: `pytest test_jira_oauth_manager.py -q` → 40 passed (3 new);
`pytest test_identity_credential_sink.py -q` → 5 passed (new file);
`test_post_auth_jira.py`, `test_vault_token_sync_f4_regression.py` and
`test_jira_oauth_helpers.py` → 31 passed; `ruff check` clean on all five files.

**Deviation from the task's blueprint** — the blueprint sketched the sink's
`persist` as resolve → `get_for_provider_account` → `update_tokens`. The
implementation adds one guard the blueprint did not list: a token with an
empty `account_id` returns before any lookup, because
`find_user_by_provider_account("jira", "")` would otherwise ask the database
to match the empty string. Covered by
`test_token_without_account_id_is_a_noop`.

**Not closed by this task**: `issue:2e85cce93cab` keeps its remaining scope —
TASK-4669 (link time), TASK-4670 (the badge), TASK-4671 (retire the two
redundant writers), TASK-4672 (document it).
