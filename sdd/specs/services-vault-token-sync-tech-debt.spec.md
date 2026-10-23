---
type: feature
base_branch: dev
projects: [ai-parrot, ai-parrot-server, ai-parrot-integrations, ai-parrot-tools]
tags: [credentials, jira, oauth2, identity-vault, tech-debt]
---

# Feature Specification: One owner for the Jira credential

**Feature ID**: FEAT-735
**Date**: 2026-10-23
**Author**: Jesus (via /sdd-fix, escalated from `issue:2e85cce93cab`)
**Status**: draft
**Target version**: 1.2.x

> **Slug note**: the file is `services-vault-token-sync-tech-debt` because
> `/sdd-fix` requires the planner's `suggested_slug` verbatim. The planner
> derived it from the single file on the issue's `about` symbol; the feature
> is wider than that file, as §1 shows.

> **Gate 1 cleared (2026-10-23): FEAT-729 landed on `dev`** via PR #1787
> (`dev` @ `899d1fe59`). The third credential copy this feature is about now
> exists on the base branch, and all three §6 edit-site anchors re-verify on
> `dev` at the same line numbers they had on the feature branch.
>
> **Gate 2 still open: Q1 (§8) — which store owns the credential.** M2–M4 are
> contingent on that answer, so task decomposition waits for it. M1 (refresh
> propagation) is correct under either answer and can be decomposed
> independently.

---

## 1. Motivation & Business Requirements

### Problem Statement

One Atlassian 3LO grant is persisted in **three** places, written by three
different code paths, with **no propagation between them**:

| # | Store | Written by | Read by | Refreshed? |
|---|---|---|---|---|
| 1 | **Redis** (`JiraOAuthManager`, TTL 90 d) | `handle_callback` → `_write_token` (`jira_oauth.py:386`) | the live tool path: `JiraToolkit` → `OAuthCredentialResolver.resolve` → `get_valid_token` (`credentials.py:198`, `jira_oauth.py:547`) | **yes** — `_refresh_tokens` (`jira_oauth.py:642`) writes Redis |
| 2 | **Session Vault** (`auth.user_vault_secrets`) | `post_auth_jira._store_in_vault` → `VaultTokenSync.store_tokens` (`vault_token_sync.py:181`) | the integrations UI status badge: `OAuth2Service._token_status` → `read_tokens_result(user_id, "jira")` (`service.py:190`) | **no** |
| 3 | **Identity Vault** (`auth.user_identities`) | `IdentityMappingService.upsert_identity(token=…)` → `IdentityStore.save_linked_identity`, added by FEAT-729 / TASK-4664 | **nothing, anywhere** | **no** |

Two consequences follow, and both are live defects rather than aesthetics:

1. **The refresh path updates only copy 1.** `_refresh_tokens` writes Redis and
   returns; it never touches the vault or the identity row. Every Atlassian
   token rotation therefore leaves copies 2 and 3 holding a credential that no
   longer works, with nothing to detect it.
2. **The UI badge is computed from the stalest copy.** `_token_status` reports
   `connected` / `needs_reconnect` from copy 2 — the one write-once copy that
   a refresh never corrects. A user whose grant was revoked upstream can still
   read "connected", and a user whose token merely rotated is reported on
   evidence that is by construction out of date.

Copy 3 makes this worse by adding a second *write-once* copy, and it is the
one with no reader at all: it is pure liability today — a sealed credential
that can go stale and that nothing validates.

`VaultTokenSync` itself is **not** a Jira store and is not in question: it is
a generic per-user token vault shared by fireflies
(`integrations/mcp/fireflies_a2a.py:117`), workiq (`workiq_provider.py:129`),
entra (`workiq_provider.py:140`) and o365 (`o365_devicecode_provider.py:142`).
Only its **Jira path** is in scope.

### Goals

- **G1** — Exactly one store is the durable owner of the Jira credential, named
  in code and in `docs/`, with every other copy either derived from it or gone.
- **G2** — A token refresh can never leave a stale durable copy behind:
  whatever store owns the credential is updated by `_refresh_tokens`.
- **G3** — The integrations status badge is computed from the owner, not from a
  write-once copy.
- **G4** — No regression in the live tool path: `JiraToolkit` keeps resolving
  credentials through `CredentialResolver.resolve`, at the same latency
  (a per-request Postgres decrypt must not replace a Redis read).

### Non-Goals (explicitly out of scope)

- Retiring `VaultTokenSync` the class, or touching its fireflies / workiq /
  entra / o365 paths.
- Changing `CredentialResolver` or the `unified-credential-broker` design
  (`sdd/proposals/unified-credential-broker.brainstorm.md`, 2026-06-29) — this
  feature changes *where the Jira bytes live*, not the resolver abstraction.
- The three channel identity mappings (`msteams`, `slack`, `telegram`). They
  hold no credential; FEAT-729 settled them.
- `issue:a671f989e8e7` (the Slack composite `nav_user_id` is not a bigint) —
  a separate defect on the same table, **resolved** by TASK-4666 before the
  FEAT-729 merge: the callback now skips the write explicitly when the OAuth
  state carries no Navigator user id (`slack/oauth_callback.py:237`).

---

## 2. Architectural Design

### Overview

Keep **Redis as the hot cache** (it is the live read path and the only copy the
refresh already maintains) and make the **Identity Vault the durable owner**:
it is navigator-auth's canonical table, it is the same writer
`TokenExchangeAuth` uses, and it seals each token bound to
`(user_id, auth_provider, provider_user_id, column)` instead of storing it as a
flat vault key. The Jira path of the Session Vault is then redundant and is
retired.

This is the direction TASK-4664's merged Completion Note recommended. It is
written here as a recommendation, not a settled fact — **Q1 in §8 is the
decision this spec exists to force**, and M2–M4 are contingent on it. M1 is
not: the refresh must propagate under every answer.

### Component Diagram

```
                      link time                      refresh time
                          │                               │
JiraOAuthManager.handle_callback              _refresh_tokens
         │                                            │
         ├──→ Redis  (hot cache, TTL 90d) ←───────────┤   M1 adds the
         │        ↑                                   │   second arrow
         │        └── JiraToolkit reads here (G4)     │
         │                                            │
         └──→ IdentityStore (DURABLE OWNER) ←─────────┘
                  ↑
                  └── OAuth2Service._token_status reads here (M2)

   RETIRED by M3:  post_auth_jira._store_in_vault(provider="jira")
                      → VaultTokenSync → auth.user_vault_secrets
   (VaultTokenSync keeps serving fireflies / workiq / entra / o365)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `JiraOAuthManager._refresh_tokens` | extends | also persists to the durable owner (M1) |
| `OAuth2Service._token_status` | replaces backing store | reads the owner, not the vault (M2) |
| `JiraPostAuthProvider._store_in_vault` | removes the jira call | M3, only after M2 ships |
| `IdentityMappingService.upsert_identity` | uses | already the single entry point for the sealed write |
| `IdentityStore.decrypt_credential` | uses | sync, not async — see §6 |
| `VaultTokenSync` | unchanged | other providers keep using it verbatim |

### Data Models

No new persisted model. The owner's row is `navigator_auth.models.UserIdentity`
and the in-flight shape is `navigator_auth.identity.types.TokenResponse`, both
already mapped by `JiraPostAuthProvider._as_token_response`.

```python
# parrot/auth/jira_oauth.py — the only new type: an optional sink the manager
# writes the refreshed grant to, so the module keeps no import of the server
# package (ai-parrot must not depend on ai-parrot-server).
class CredentialSink(Protocol):
    """Durable store notified when a grant is minted or refreshed."""

    async def persist(self, channel: str, user_id: str, token: "JiraTokenSet") -> None:
        """Persist the grant. Raises on failure; the caller decides the policy."""
```

### New Public Interfaces

```python
class JiraOAuthManager:
    def __init__(self, ..., credential_sink: Optional[CredentialSink] = None) -> None:
        """``credential_sink``: durable store kept in step with Redis (G2).

        None keeps today's Redis-only behaviour, so every existing
        construction site is unaffected.
        """
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: refresh propagation | no | — | Needs the failure policy decided (Q2): does a sink failure fail the refresh, or log and continue? |
| M2: status probe on the owner | yes | `_token_status` keeps its `"connected"`/`"needs_reconnect"` contract and its fail-open `except`; only the backing read changes | — |
| M3: retire the vault jira write | yes | delete the `provider="jira"` call in `_store_in_vault`; leave the method for other providers | — |
| M4: docs + migration note | yes | one page under `docs/`, linked from the two touched modules | — |

### Module 1: Refresh propagation (`CredentialSink`)
- **Path**: `packages/ai-parrot/src/parrot/auth/jira_oauth.py`
- **Responsibility**: a refreshed grant reaches the durable owner, not only Redis.
- **Depends on**: nothing in this spec (ships first; it is correct under either Q1 answer).
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/auth/jira_oauth.py (modifies jira_oauth.py:642)
  class JiraOAuthManager:
      async def _refresh_tokens(self, channel: str, user_id: str,
                                token_set: JiraTokenSet) -> JiraTokenSet:
          """Refresh via Atlassian, write Redis, then notify ``credential_sink``.

          The sink is notified AFTER the Redis write succeeds, so a durable-store
          outage can never cost the user a working hot credential.
          """
  ```

### Module 2: Status probe reads the owner
- **Path**: `packages/ai-parrot/src/parrot/auth/oauth2/service.py`
- **Responsibility**: `_token_status` answers from the owner's row.
- **Depends on**: M1 (otherwise the badge moves onto a copy that is equally stale).
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/auth/oauth2/service.py (modifies service.py:173)
  class OAuth2Service:
      async def _token_status(self, user_id: str, provider_id: str,
                              request: Any) -> str:
          """``connected`` | ``needs_reconnect``, from the durable owner.

          Unchanged contract: any probe failure still returns ``connected``,
          so a store outage never hides a working integration.
          ``IdentityCredentialError`` maps to ``needs_reconnect`` — it is the
          owner's equivalent of the vault's ``unreadable``.
          """
  ```

### Module 3: Retire the Jira path of the Session Vault
- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/telegram/post_auth_jira.py`
- **Responsibility**: stop writing the second copy; it has no reader once M2 ships.
- **Depends on**: M2.
- **Interface Skeleton**:
  ```python
  # modifies post_auth_jira.py — `_store_in_vault` loses its jira call site.
  # VaultTokenSync itself is untouched: fireflies / workiq / entra / o365
  # keep calling store_tokens exactly as today.
  ```

### Module 4: Write the ownership down
- **Path**: `docs/auth/jira-credential-ownership.md` (new)
- **Responsibility**: which store owns what, why Redis stays, what a reader must
  call, and how to retire the remaining rows of the old vault key.
- **Depends on**: M1–M3.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_refresh_notifies_sink` | M1 | A refresh writes Redis AND calls the sink with the new grant |
| `test_refresh_survives_sink_failure` | M1 | A sink error leaves the refreshed Redis token usable (policy from Q2) |
| `test_no_sink_keeps_redis_only_behaviour` | M1 | `credential_sink=None` is byte-identical to today |
| `test_status_connected_from_owner` | M2 | A sealed, openable row ⇒ `connected` |
| `test_status_needs_reconnect_on_credential_error` | M2 | `IdentityCredentialError` ⇒ `needs_reconnect` |
| `test_status_fails_open` | M2 | Store outage ⇒ `connected` (contract preserved) |
| `test_jira_not_written_to_session_vault` | M3 | The combined Telegram login writes no `jira:*` vault key |
| `test_other_providers_still_use_vault` | M3 | fireflies / o365 vault writes unchanged |

### Integration Tests

| Test | Description |
|---|---|
| `test_link_then_refresh_keeps_owner_current` | Link → force-expire → resolve → the owner's row decrypts to the NEW access token (the drift this feature closes), against real Postgres |
| `test_toolkit_resolution_unchanged` | `JiraToolkit` still resolves through Redis with no added Postgres round-trip (G4) |

### Validation Contract

tests:
- packages/ai-parrot/tests/unit/test_jira_oauth.py
- packages/ai-parrot/tests/unit/test_post_auth_jira.py
- packages/ai-parrot/tests/unit/test_identity_mapping.py
- packages/ai-parrot/tests/unit/test_vault_token_sync.py
- packages/ai-parrot-server/tests/unit/test_vault_token_sync_f4_regression.py
markers: none

> The real-Postgres tests in `test_identity_mapping.py` skip unless
> `IDENTITY_PG_DSN` is set (the `TEST_STUDIO_PG_DSN` precedent). CI has no
> `auth` schema, so the integration row above is evidence a human runs
> locally until that changes.

### Test Data / Fixtures

```python
@pytest.fixture
def recording_sink():
    """CredentialSink that records calls, for the refresh-propagation tests."""
```

---

## 5. Acceptance Criteria

- [ ] **AC-1** One store is named the durable owner in `docs/` and in the
      docstrings of `jira_oauth.py` and `vault_token_sync.py`; the doc states
      which copies are derived and which were retired.
- [ ] **AC-2** `_refresh_tokens` updates the durable owner; a test proves the
      owner's stored credential decrypts to the **refreshed** access token.
- [ ] **AC-3** `_token_status` answers from the owner, keeps the
      `connected` / `needs_reconnect` vocabulary, and still fails open.
- [ ] **AC-4** No code path writes the Jira credential to
      `auth.user_vault_secrets` any more; `VaultTokenSync`'s other providers
      are untouched and their tests still pass.
- [ ] **AC-5** `JiraToolkit` credential resolution still goes through Redis —
      no new per-call Postgres read on the tool path (G4).
- [ ] **AC-6** A migration note says what to do with `jira:*` keys already in
      users' vaults (leave, or a one-off delete), and the choice is justified.
- [ ] **AC-7** `issue:2e85cce93cab` can be closed with this evidence.

---

## 6. Codebase Contract

> Written against `feat-FEAT-729-msteams-user-auth-lane` @ `13838cfb46` and
> **re-verified against `origin/dev` @ `899d1fe59`** (2026-10-23, after the
> FEAT-729 merge): every edit-site anchor below still resolves, at the same
> line numbers. `/sdd-task` must still re-run each `grep -c` — this table
> saves the search, not the check.

### Verified Imports

```python
from parrot.auth.jira_oauth import JiraOAuthManager, JiraTokenSet      # jira_oauth.py:224, :59
from parrot.services.vault_token_sync import VaultTokenSync, VaultTokenRead  # vault_token_sync.py:99, :36
from parrot.services.identity_mapping import IdentityMappingService    # identity_mapping.py
from navigator_auth.identity.store import IdentityStore, IdentityCredentialError  # store.py:151, :44
from navigator_auth.identity.types import TokenResponse                # identity/types.py
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/auth/jira_oauth.py
_TOKEN_TTL_SECONDS = 90 * 24 * 60 * 60                                   # line 42
class JiraTokenSet(BaseModel):                                           # line 59
    access_token: str; refresh_token: str; expires_at: float             # epoch float
    cloud_id: str; site_url: str; account_id: str; display_name: str
    email: Optional[str]; scopes: List[str]
    @property
    def is_expired(self) -> bool:                                        # line 76
class JiraOAuthManager:                                                  # line 224
    async def _write_token(self, key: str, token: JiraTokenSet) -> None: # line 386 — Redis SET, ex=TTL
    async def handle_callback(self, code, state) -> Tuple[JiraTokenSet, Dict]:  # line 439
    async def get_valid_token(self, channel, user_id) -> Optional[JiraTokenSet]:  # line 547
    async def _refresh_tokens(self, channel, user_id, token_set) -> JiraTokenSet:  # line 642 — THE EDIT SITE

# packages/ai-parrot/src/parrot/auth/credentials.py
class OAuthCredentialResolver:
    def __init__(self, oauth_manager: "JiraOAuthManager") -> None:       # line 194
    async def resolve(self, channel, user_id) -> Optional[Any]:          # line 197
        return await self._manager.get_valid_token(channel, user_id)     # line 198 — the live tool path

# packages/ai-parrot/src/parrot/auth/oauth2/service.py
class OAuth2Service:
    def _vault_sync(self, request: Any) -> Any:                          # line 151
    async def _token_status(self, user_id, provider_id, request) -> str: # line 173 — THE EDIT SITE
        result = await sync.read_tokens_result(user_id, provider_id)     # line 190

# packages/ai-parrot-server/src/parrot/services/vault_token_sync.py
@dataclass
class VaultTokenRead:                                                    # line 36
    tokens: Optional[Dict[str, Any]]; status: TokenReadStatus
    @property
    def needs_reconnect(self) -> bool:                                   # line 50 — status == "unreadable"
class VaultTokenSync:                                                    # line 99
    async def store_tokens(self, nav_user_id, provider, tokens) -> None: # line 181
    async def read_tokens_result(self, nav_user_id, provider) -> VaultTokenRead:  # line 244
    async def read_tokens(self, nav_user_id, provider) -> Optional[Dict]: # line 294
    async def delete_tokens(self, nav_user_id, provider) -> None:        # line 308

# navigator-auth 0.28.8 — the owner's API
class IdentityStore:                                                     # store.py:151
    async def save_linked_identity(self, user_id, provider, token: TokenResponse,
                                   userinfo: Optional[dict] = None) -> UserIdentity   # :214
    async def get_by_provider(self, user_id, provider) -> Optional[UserIdentity]
    async def get_for_provider_account(self, user_id, provider, provider_user_id)
    def decrypt_credential(self, identity) -> TokenResponse              # :444 — SYNCHRONOUS
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `CredentialSink` | `JiraOAuthManager._refresh_tokens` | injected, called after the Redis write | `jira_oauth.py:642` |
| sink implementation | `IdentityMappingService.upsert_identity(token=…)` | existing sealed-write entry point | `identity_mapping.py` |
| `_token_status` | `IdentityStore.get_by_provider` + `decrypt_credential` | replaces `read_tokens_result` | `service.py:190` |

### Does NOT Exist (Anti-Hallucination)

- ~~any reader of `auth.user_identities` in ai-parrot~~ — `get_identity`,
  `get_all_identities` and `delete_identity` have zero callers outside
  `IdentityMappingService` and its tests. M2 creates the first one.
- ~~a refresh hook on `VaultTokenSync` or `IdentityStore`~~ — neither is
  notified of a rotation today; that is the defect.
- ~~`IdentityStore.decrypt_credential` as a coroutine~~ — it is **sync**
  (`store.py:444`). TASK-4664's contract had this wrong and a test caught it.
- ~~a Jira-specific method on `VaultTokenSync`~~ — the provider is just a key
  prefix; `"jira"` is passed by the caller.
- ~~`JiraOAuthManager` importing anything from `ai-parrot-server`~~ — it must
  not: `parrot.services.*` ships from the server distribution, which is why
  M1 takes a Protocol rather than a `VaultTokenSync`/`IdentityMappingService`.

### Edit Sites (Blueprint Anchors)

Verified against `13838cfb46`.

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/auth/jira_oauth.py` | MODIFY | `    async def _refresh_tokens(self, channel: str, user_id: str, token_set: JiraTokenSet) -> JiraTokenSet:` | `jira_oauth.py:642` | 1 |
| `packages/ai-parrot/src/parrot/auth/oauth2/service.py` | MODIFY | `    async def _token_status(self, user_id: str, provider_id: str, request: Any) -> str:` | `service.py:173` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/post_auth_jira.py` | MODIFY | `        await self._store_in_vault(nav_user_id, token_set)` | `post_auth_jira.py:189` (method at `:222`) | 1 |
| `docs/auth/jira-credential-ownership.md` | CREATE | — | — | — |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- `ai-parrot` must not import `ai-parrot-server`. M1 therefore defines a
  Protocol and the application wires the concrete sink, exactly as
  `oauth2/service.py:164` already does with its guarded, lazy
  `from parrot.services.vault_token_sync import VaultTokenSync`.
- `IdentityStore` expects an **asyncdb** pool (`async with await pool.acquire()`),
  which is what `app["authdb"]` is. Do not hand it a raw asyncpg pool.
- Any new raw SQL against `auth.user_identities` goes through
  `IdentityMappingService`, not a second hand-rolled statement.

### Known Risks / Gotchas

- **Latency on the tool path (G4).** Making the toolkit resolve from Postgres
  instead of Redis would add a decrypt to every Jira tool call. Redis stays the
  read path; the owner is consulted at link, refresh and status time only.
- **Fail-open must survive M2.** `_token_status` currently swallows every probe
  error and returns `connected` on purpose, so a vault outage cannot hide a
  working integration. Keep that, and map only `IdentityCredentialError` to
  `needs_reconnect`.
- **Sink failure during refresh.** Writing the sink before Redis would let a
  Postgres outage deny the user a working token. Redis first, sink second.
- **asyncpg jsonb binding.** `$n::jsonb` with a Python `str` is encoded as a
  JSON *string scalar*; in a `||` merge that appends instead of merging
  (TASK-4664 shipped that bug). Use `$n::text::jsonb`.
- **Existing `jira:*` vault keys** stay readable after M3 and simply stop being
  written. AC-6 decides whether to delete them.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `navigator-auth` | `>=0.28.8` | `UserIdentity` accepts `id_token=None`; 0.28.7 raised "Cannot convert None to bytes" on a Jira grant (TASK-4664 shipped its real-DB test as a strict xfail because of it) |

---

## 8. Open Questions

- [ ] **Q1 — Which store owns the Jira credential?** *(the decision this spec
      exists to force; M2–M4 are contingent on it)*
      **Recommendation: the Identity Vault**, with Redis kept as the hot cache.
      It is navigator-auth's canonical table, it is the store
      `TokenExchangeAuth` already writes, and it seals each token bound to its
      identity row rather than as a flat vault key. The counter-argument on
      record (TASK-4664's re-verification) is that the Session Vault is the
      copy with a live reader today — but that reader is the stale badge of §1,
      which is itself the defect, so "it has a reader" does not make it the
      right owner. The alternative worth stating: **drop copy 3 entirely** and
      keep the Session Vault, which is less work but gives up the sealed,
      context-bound credential and leaves navigator-auth's canonical table
      empty for Jira.
- [ ] **Q2 — Does a sink failure fail the refresh?** Proposed: no. Redis is
      written first and the refreshed token is returned; a sink failure is
      logged at `error` with the user and provider. A refresh that works for
      the user must not be rolled back because the durable copy lagged — but
      the log must be loud, because silent failure is what produced
      `issue:0115386145f2` in the first place.
- [ ] **Q3 — What happens to `jira:*` keys already in users' vaults?**
      Proposed: leave them; they are inert once nothing reads them, and a bulk
      delete across every user's vault is a risk with no payoff. Revisit if an
      audit requires that revoked credentials leave no copy.
- [ ] **Q4 — Should `handle_callback` write the owner directly**, instead of
      relying on `post_auth_jira` to do it for the Telegram flow only? Today
      the sealed write happens only on the combined Telegram login; the MS
      Teams and Slack Jira callbacks write no credential at all. If the answer
      is yes, the sink of M1 covers link time as well as refresh time, and
      this feature closes a gap wider than the one `issue:2e85cce93cab`
      reported.

---

## 9. Provenance

- Escalated from `issue:2e85cce93cab` by `/sdd-fix` on 2026-10-23. The planner
  routed the issue to the **fast lane** (`minor/low tech_debt confined to a
  single file`) from the one file on its `about` symbol; the investigation
  found three stores, four readers and a refresh path that maintains none of
  the durable ones, so the user escalated it to this spec.
- Prior art: `sdd/proposals/unified-credential-broker.brainstorm.md`
  (2026-06-29) — the `CredentialResolver` abstraction this feature deliberately
  does not change.
- Sibling issue on the same table: `issue:a671f989e8e7` — closed by TASK-4666.
- FEAT-729 merged to `dev` on 2026-10-23 (PR #1787). TASK-4664 and TASK-4665
  closed `done-with-issues` / `verification: partial`; the credential-store
  duplication this spec addresses is the TASK-4664 remainder.
