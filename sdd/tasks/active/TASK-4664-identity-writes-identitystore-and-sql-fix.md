# TASK-4664: Make all four identity writes land: IdentityStore for Jira, fixed SQL for channel providers

**Feature**: FEAT-729 — MS Teams user authentication lane
**Spec**: `sdd/specs/msteams-user-auth-lane.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements **spec §3 Module 6**, in the shape that the data model actually
allows. This task fixes a **live bug**: `ledger issue:0115386145f2`.

`IdentityMappingService.upsert_identity()` fails on **every** call, for two
independent reasons:

1. `_UPSERT_SQL` (`identity_mapping.py:26`) targets
   `ON CONFLICT (user_id, auth_provider)`. Postgres requires a unique index on
   exactly those columns. `auth.user_identities` has PK `(user_id, uid)`, a
   partial unique on `(user_id, auth_provider, provider_user_id) WHERE
   provider_user_id IS NOT NULL`, and a **non-unique** index on
   `(user_id, auth_provider)`. None can arbitrate ⇒ error **42P10**. This fails
   against the canonical DDL too, so no migration fixes it.
2. The SQL also uses `identity_id`, `display_name` and `email`, which the
   deployed legacy table lacked. navigator-auth **0.28.8** (FEAT-103 Module 0,
   `TASK-102-identity-base-columns-migration`) reconciles that half.

All four call sites swallow the failure in `except Exception:
logger.exception(...)` — *"identity write must not break browser flow"* — so a
user sees "Jira connected" while **no row is written**. Nothing reads the data
today (`get_identity`, `get_all_identities`, `delete_identity` have zero
callers), which is why nobody noticed. The unit tests mock the pool, so no SQL
ever reaches Postgres.

> ### Scope correction — read this before following spec §3 M6
> The spec's M6 skeleton routes all four call sites through
> `IdentityStore.save_linked_identity`. **That is not implementable**, and the
> verification is in this task's contract: `save_linked_identity(user_id,
> provider, token: TokenResponse, userinfo)` **requires a `TokenResponse` whose
> `access_token` is mandatory**, and `IdentityStore` has **no metadata-only
> write path** at all. But three of the four sites are channel↔Navigator identity
> mappings with no credential in existence:
>
> | Site | `auth_provider` | Payload | Token? |
> |---|---|---|---|
> | `packages/ai-parrot-integrations/src/parrot/integrations/msteams/oauth_callback.py:248` | `"msteams"` | `{aad_object_id, tenant_id}` | none exists |
> | `packages/ai-parrot-integrations/src/parrot/integrations/slack/oauth_callback.py:232` | `"slack"` | Slack ids | none exists |
> | `packages/ai-parrot-integrations/src/parrot/integrations/telegram/post_auth_jira.py:256` | `"telegram"` | `{telegram_id, username}` | none exists |
> | `packages/ai-parrot-integrations/src/parrot/integrations/telegram/post_auth_jira.py:273` | `"jira"` | `{account_id, cloud_id, …}` | **yes** — `token_set.access_token` (line 220) |
>
> **Decided 2026-10-23 by the user**: adopt `IdentityStore` where a real token
> exists (the Jira site) and fix the raw SQL properly for the three channel
> mappings. Every site ends up writing a real row, which is what G5 is for.
> Spec G5's wording is superseded by this task.

---

## Scope

- Fix `_UPSERT_SQL`: arbitrate on `(user_id, auth_provider, provider_user_id)`
  to match the partial unique index, and pass a non-NULL `provider_user_id` at
  every call site (the index is partial — a NULL excludes the row from it, so a
  NULL `provider_user_id` would re-break the upsert).
- Thread the channel id through as `provider_user_id`: `aad_object_id` for
  `msteams`, the Slack user id for `slack`, `telegram_id` for `telegram`.
- Route the **Jira** site through `IdentityStore.save_linked_identity` with a
  real `TokenResponse` built from `token_set`.
- Decide and record which store owns the Jira credential — `IdentityStore` or the
  existing `VaultTokenSync` (`packages/ai-parrot-server/src/parrot/services/vault_token_sync.py`). Both would now
  hold it; that duplication must not ship unexamined.
- Replace the pool-mocking tests with assertions that a row **lands and reads
  back**, against a real Postgres.

**NOT in scope**: anything in the Teams auth lane (TASK-4659..4663); adding a
unique index on `(user_id, auth_provider)` — see Does NOT Exist; migrating the
three channel mappings into `IdentityStore` (it cannot represent them).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/services/identity_mapping.py` | MODIFY | Correct arbiter, `provider_user_id`, `IdentityStore` path for token-bearing providers |
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/oauth_callback.py` | MODIFY | Pass `provider_user_id` |
| `packages/ai-parrot-integrations/src/parrot/integrations/slack/oauth_callback.py` | MODIFY | Pass `provider_user_id` |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/post_auth_jira.py` | MODIFY | `provider_user_id` for telegram; real token for jira |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py` | MODIFY | Construction site, if the signature changes |
| `packages/ai-parrot/tests/unit/test_identity_mapping.py` | MODIFY | Real-Postgres round-trip tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from navigator_auth.identity.store import IdentityStore          # verified: navigator_auth/identity/store.py:49
from navigator_auth.identity.types import TokenResponse          # verified: navigator_auth/identity/types.py
```

### Existing Signatures to Use
```python
# navigator_auth 0.28.8 — the FULL write surface. There is no other.
class IdentityStore:                                                        # store.py:49
    async def save_linked_identity(self, user_id: Any, provider: str,
                                   token: TokenResponse,
                                   userinfo: Optional[dict] = None) -> UserIdentity
    async def update_tokens(self, identity: UserIdentity,
                            token: TokenResponse) -> UserIdentity
    async def get_by_provider(self, user_id: Any, provider: str) -> Optional[UserIdentity]
    async def get_for_provider_account(self, user_id: Any, provider: str,
                                       provider_user_id: Optional[str]) -> Optional[UserIdentity]
    async def find_user_by_provider_account(self, provider: str,
                                            provider_user_id: str) -> Optional[Any]
    async def decrypt_credential(self, identity: UserIdentity) -> TokenResponse
    async def delete(self, user_id: Any, identity_id: Any) -> bool
    async def list_for_user(self, user_id: Any) -> list[dict]
    def masked(self, identity: UserIdentity) -> dict

@dataclass
class TokenResponse:                      # navigator_auth/identity/types.py
    access_token: str                     # REQUIRED — no default
    token_type: str = "Bearer"
    refresh_token: Optional[str] = None
    id_token: Optional[str] = None
    expires_in: Optional[int] = None
    expires_at: Optional[datetime] = None
    issued_at: Optional[datetime] = None
    scopes: list                          # default_factory
    provider_user_id: Optional[str] = None
    raw: dict                             # default_factory

# packages/ai-parrot-server/src/parrot/services/identity_mapping.py
_UPSERT_SQL   # line 26 — "ON CONFLICT (user_id, auth_provider)"  <- the 42P10
class IdentityMappingService:                                    # line 76
    def __init__(self, db_pool: Any) -> None:                    # line 95
    async def upsert_identity(self, ...)                         # line 99
    async def get_identity(self, ...)                            # line 136
    async def get_all_identities(self, ...)                      # line 157
    async def delete_identity(self, ...)                         # line 173

# The four call sites, verified on 0eb59926a:
# packages/ai-parrot-integrations/src/parrot/integrations/msteams/oauth_callback.py:246   await identity_service.upsert_identity(
#   auth_provider="msteams" (line 248), auth_data={"aad_object_id": nav_user_id,
#   "tenant_id": conv_ref...tenantId}
# packages/ai-parrot-integrations/src/parrot/integrations/slack/oauth_callback.py:230     await identity_service.upsert_identity(
#   auth_provider="slack" (line 232)
# packages/ai-parrot-integrations/src/parrot/integrations/telegram/post_auth_jira.py:254  await self._identity.upsert_identity(
#   auth_provider="telegram" (line 256), auth_data={"telegram_id", "username"}
# packages/ai-parrot-integrations/src/parrot/integrations/telegram/post_auth_jira.py:273  await self._identity.upsert_identity(
#   auth_provider=self.provider_name (line 273) == "jira",
#   auth_data={"account_id", "cloud_id", "site_url", "display_name"}
#   -> token_set.access_token IS in scope here (used at line 220)
# packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py:601         identity_service = IdentityMappingService(db_pool)

# auth.user_identities, live schema (post-0.28.8):
#   PK (user_id, uid)
#   UNIQUE (user_id, auth_provider, provider_user_id) WHERE provider_user_id IS NOT NULL
#   idx_user_identities_user (user_id, auth_provider)   <- NOT unique
```

### Does NOT Exist
- ~~a metadata-only write on `IdentityStore`~~ — every write path requires a
  `TokenResponse` with a mandatory `access_token`. This is the finding that
  reshaped this task.
- ~~an "msteams access token" / "telegram access token"~~ — those providers are
  channel identities. There is no credential to store.
- ~~a unique index on `auth.user_identities (user_id, auth_provider)`~~ — absent
  from the live table **and** from the canonical DDL
  (`../navigator-auth/examples/sql/identity_vault_schema.sql`). **Do not add
  one**: it would forbid a user holding two accounts on one provider, which the
  canonical schema deliberately allows.
- ~~`IdentityStore.upsert_identity` / `.save_identity` / `.put`~~ — the full API
  is listed above; nothing else exists.
- ~~any reader of the identity rows~~ — `get_identity`, `get_all_identities` and
  `delete_identity` have **zero** callers outside the service and its tests, so
  no consumer constrains the payload shape. Confirm before assuming otherwise.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/src/parrot/services/identity_mapping.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-integrations/src/parrot/integrations/msteams/oauth_callback.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-integrations/src/parrot/integrations/slack/oauth_callback.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-integrations/src/parrot/integrations/telegram/post_auth_jira.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/unit/test_identity_mapping.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/services/identity_mapping.py#IdentityMappingService",
    "sym:packages/ai-parrot-server/src/parrot/services/identity_mapping.py#IdentityMappingService.upsert_identity",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/telegram/post_auth_jira.py#JiraPostAuthProvider"
  ]
}
```

---

## Implementation Notes

### Why the partial index forces a non-NULL `provider_user_id`
The only usable arbiter is
`UNIQUE (user_id, auth_provider, provider_user_id) WHERE provider_user_id IS NOT NULL`.
A partial index arbitrates only rows that satisfy its predicate, so an upsert
with `provider_user_id = NULL` is **not** covered and fails again. Every call
site must therefore supply the channel's own user id. That is also the semantic
improvement: one row per account, not one per provider.

### The duplication to resolve (AC-6)
`packages/ai-parrot-server/src/parrot/services/vault_token_sync.py` already stores OAuth tokens for the user.
Once the Jira site writes through `IdentityStore`, the same credential lives in
two places. Decide which is authoritative, write the decision into the
Completion Note, and open a ledger issue if the loser cannot be retired here.

### Testing against real Postgres
The existing tests mock the pool, which is exactly why the 42P10 stayed hidden
for the lifetime of this code. Follow the FEAT-644 conftest pattern: real local
Postgres, a unique schema or key prefix per run, skip when unreachable. A test
that mocks the connection cannot satisfy AC-1.

---

## Implementation Blueprint

### Steps (in order)
1. Fix the SQL and the signature first — *why*: the four call sites cannot be
   updated until the parameter exists.
2. Update the three channel call sites — *why*: they are mechanical once
   `provider_user_id` is a parameter.
3. Do the Jira site last — *why*: it is the only one that changes stores, and it
   needs the `VaultTokenSync` decision made.

### `packages/ai-parrot-server/src/parrot/services/identity_mapping.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'class IdentityMappingService:' packages/ai-parrot-server/src/parrot/services/identity_mapping.py)
# AFTER — replace the module-level `_UPSERT_SQL` (verified: line 26) and extend
#         the method at line 99. Keep get_identity/get_all_identities/
#         delete_identity working against the same columns.

_UPSERT_SQL = """
INSERT INTO auth.user_identities
    (user_id, auth_provider, provider_user_id, auth_data, created_at)
VALUES ($1, $2, $3, $4, NOW())
ON CONFLICT (user_id, auth_provider, provider_user_id)
DO UPDATE SET auth_data = EXCLUDED.auth_data
RETURNING user_id, auth_provider, provider_user_id, auth_data
"""
# FILL IN: confirm against the live table which of display_name/email/uid are
# present post-0.28.8 and whether `uid` is NOT NULL — the old PK was
# (user_id, uid), so a surviving NOT NULL `uid` must be supplied or defaulted.
# Verify with: \d auth.user_identities   — bounded by AC-1.

    async def upsert_identity(self, *, nav_user_id: str, auth_provider: str,
                              provider_user_id: str,
                              auth_data: dict,
                              display_name: Optional[str] = None,
                              email: Optional[str] = None,
                              token: Optional["TokenResponse"] = None) -> None:
        """Write one identity row.

        ``provider_user_id`` is REQUIRED: the only usable unique index is
        partial on it being non-NULL, so a NULL re-introduces the 42P10.
        When ``token`` is given the write goes through ``IdentityStore`` so the
        credential is ciphered; otherwise it is a metadata-only channel mapping
        and goes through the SQL above.
        """
        # FILL IN: branch on `token`; for the IdentityStore path construct it
        # from the caller's TokenResponse and call save_linked_identity(
        # nav_user_id, auth_provider, token, userinfo={...display_name, email}).
        # Raise on failure — do NOT swallow: the callers' own except blocks are
        # what hid this bug, and AC-5 requires at least one caller to surface it.
        # Bounded by AC-1, AC-2, AC-4.
        raise NotImplementedError
```
**Why this shape**: one method keeps the four call sites from each learning two
stores. `provider_user_id` becomes keyword-required so a caller cannot silently
omit it and resurrect the bug. The docstring states the partial-index reason
because that is the single most surprising constraint here.

### `packages/ai-parrot-integrations/src/parrot/integrations/telegram/post_auth_jira.py` (MODIFY)
```python
# occurrences: 2 (verified: grep -c '            await self._identity.upsert_identity(' packages/ai-parrot-integrations/src/parrot/integrations/telegram/post_auth_jira.py)
# FILL IN: disambiguate — the two call sites are textually identical. Quote the
# enclosing comment lines to target each:
#   site 1 is preceded by `        # Telegram identity`          (line ~253)
#   site 2 is preceded by `        # Jira identity`              (line ~271)
# Site 1: add provider_user_id=str(session.telegram_id).
# Site 2: add provider_user_id=token_set.account_id AND pass
#         token=TokenResponse(access_token=token_set.access_token,
#         refresh_token=..., provider_user_id=token_set.account_id,
#         scopes=[...], raw={...}) — token_set.access_token is already in scope
#         (used at line 220). Bounded by AC-3, AC-4.
```
**Why**: these are the two sites the spec's Q4 flagged, and they are the reason
this module is not delegation-eligible — one becomes an `IdentityStore` write and
the other stays SQL, from identical-looking code.

### FILL IN checklist
- [ ] `_UPSERT_SQL` + live-schema confirmation (`uid` nullability); bounded by AC-1
- [ ] `upsert_identity` — the two-path branch, raising on failure; bounded by AC-1, AC-2, AC-4
- [ ] `post_auth_jira` — both sites, disambiguated by their comments; bounded by AC-3, AC-4
- [ ] `msteams`/`slack` callbacks — `provider_user_id` threaded; bounded by AC-3
- [ ] `VaultTokenSync` ownership decision recorded; bounded by AC-6

---

## Acceptance Criteria

- [ ] AC-1 `upsert_identity` writes a row that reads back, against **real
      Postgres** — the assertion the old `except Exception` hid
- [ ] AC-2 calling it twice for the same `(user_id, provider, provider_user_id)`
      updates in place instead of raising 42P10 or duplicating
- [ ] AC-3 all four call sites pass a non-NULL `provider_user_id`
- [ ] AC-4 the Jira site's credential is stored through `IdentityStore` and comes
      back via `decrypt_credential`; `auth_data` holds no cleartext token
- [ ] AC-5 a write failure is **surfaced** by at least one call site rather than
      silently logged
- [ ] AC-6 the `IdentityStore` vs `VaultTokenSync` ownership decision is recorded
      in the Completion Note, with a ledger issue if the duplication survives
- [ ] AC-7 no unique index on `(user_id, auth_provider)` is added anywhere
- [ ] `pytest packages/ai-parrot/tests/unit/test_identity_mapping.py -q` passes
- [ ] `ledger issue:0115386145f2` can be closed with this evidence

---

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/test_identity_mapping.py -q`
- `pytest packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_oauth_callback.py -q`
- `pytest packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_jira_commands.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/test_identity_mapping.py  (extend — do not mock the pool)
import pytest


class TestUpsertAgainstRealPostgres:
    async def test_row_lands_and_reads_back(self, authdb_pool):
        """The write the 42P10 used to kill now produces a readable row."""
        # FILL IN: real pool, unique provider_user_id per run, skip if unreachable

    async def test_second_write_updates_in_place(self, authdb_pool):
        """Same triple upserts rather than erroring or duplicating."""
        # FILL IN

    async def test_null_provider_user_id_is_rejected(self, authdb_pool):
        """A NULL falls outside the partial index, so it must not be allowed."""
        # FILL IN


class TestJiraCredentialPath:
    async def test_token_is_ciphered_not_in_auth_data(self, authdb_pool):
        """The Jira site stores through IdentityStore; auth_data stays clean."""
        # FILL IN: assert decrypt_credential round-trips and no cleartext token
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug msteams-user-auth-lane --feature-id FEAT-729`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in
   `sdd/tasks/index/msteams-user-auth-lane.json`
4. **Verify the Codebase Contract** before writing ANY code. Re-grep every
   anchor: this task was written on `dev @ 0eb59926a` and the spec's §6 was
   verified on `37dc1da44`, so two anchors had already drifted once (see
   Context where noted). If anything moved, fix the contract FIRST.
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`)
   and commit only that index file
6. **Implement** — start from the Implementation Blueprint, complete every
   `# FILL IN:` marker, never change a signature or path it fixes
7. **Verify** the Acceptance Criteria — run the Validation Commands with
   `PYTHONPATH` set per changed package (the shared `.venv` is editable-installed
   against the MAIN checkout, so a bare `pytest` in a worktree imports the wrong
   branch)
8. **Commit the code** — stage only the files this task lists (never `git add .`)
9. **Close the task** with
   `scripts/sdd/close_task.sh TASK-4664 msteams-user-auth-lane verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

> Filled in by the implementing agent when the task is closed.

**Completed**:
**Deviations from scope**:
**Ambiguities found in the spec**:
**Follow-up needed**:
