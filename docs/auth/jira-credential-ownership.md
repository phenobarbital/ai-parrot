# Who owns the Jira credential

> Decided by **FEAT-735** (2026-10-23), from `issue:2e85cce93cab`.
> Before this, one Atlassian 3LO grant lived in three places, written by three
> code paths, with no propagation between them — and two reviews of TASK-4664
> reached opposite conclusions about which one was authoritative.

## The answer

| Store | Role | Written by | Read by |
|---|---|---|---|
| `auth.user_identities` (**Identity Vault**) | **durable owner** | `IdentityVaultCredentialSink`, via `JiraOAuthManager` — at link time (`handle_callback`) and on every refresh (`_refresh_tokens`) | `IntegrationsService._identity_token_status` (the integrations badge) |
| Redis, `jira:oauth:<channel>:<user>` (TTL 90 d) | hot cache, **the live tool path** | `JiraOAuthManager._write_token` | `JiraToolkit` → `OAuthCredentialResolver.resolve` → `get_valid_token` |
| `auth.user_vault_secrets` (Session Vault) | **retired for Jira** | nothing | nothing |

One writer, one owner. The sink is notified *after* the Redis write succeeds,
and a sink failure is logged at `error` and swallowed — a durable-store outage
must never cost a user a working credential, and a refresh that worked must
never be rolled back because the durable copy lagged.

## Adding a reader

Read the owner:

```python
from navigator_auth.identity.store import IdentityStore, IdentityCredentialError

store = IdentityStore(app["authdb"])              # the asyncdb pool, not raw asyncpg
identity = await store.get_by_provider(user_id, "jira")
token = store.decrypt_credential(identity)        # SYNCHRONOUS — do not await it
```

`decrypt_credential` is not a coroutine. Awaiting it raises
`TypeError: object TokenResponse can't be used in 'await' expression`, which
TASK-4664 shipped once already.

**Do not put this on the per-call tool path.** `JiraToolkit` resolves through
Redis, and that is deliberate (FEAT-735 goal G4): moving it to Postgres would
add a database round-trip and a decrypt to every Jira tool call. The owner is
consulted at link, refresh and status time only.

## Why Redis stays

It is the copy with the live reader, and it was the only copy the refresh
already maintained. Nothing about naming a durable owner makes a hot cache
wrong — the defect was never that Redis existed, it was that the *durable*
copies silently went stale behind it.

## Migration: the `jira:*` keys already in users' vaults

**They are left in place.** Once nothing reads them they are inert, and a bulk
delete across every user's vault is a risk with no payoff. `VaultTokenSync`
itself is untouched and still serves fireflies, workiq, entra and o365 — only
the Jira path was retired.

Revisit this only if an audit requires that a revoked credential leave no copy
behind. That would be a deliberate, separately-reviewed cleanup, not a side
effect of this feature.

## Known gap

The sink can only write the owner for a user it can identify. It resolves, in
order: `nav_user_id` from the OAuth state, then
`find_user_by_provider_account("jira", account_id)` for a **re-link** of an
account that already owns a row. When neither resolves it logs a warning and
skips — correctly, because there is no owner to attach the credential to.

Per channel, as of 2026-10-23:

| Channel | Carries `nav_user_id` in the OAuth state? |
|---|---|
| Telegram | **yes** — the combined login sets it (`post_auth_jira.py`) |
| MS Teams | **yes** for an authenticated user, since FEAT-729 / TASK-4667 (`msteams/commands/jira_commands.py`) |
| Slack | **no** — it sends `team_id` / `slack_user_id` (`slack/commands/jira_commands.py`) |

So the remaining gap is a **first-ever Slack link**, plus a Teams link by a user
the resolver cannot authenticate. Closing it means carrying a Navigator user id
into the Slack authorize state, the same way TASK-4667 did for Teams.

Do **not** close it by inventing an id at the callback. A composite
`team:user` string (`issue:a671f989e8e7`) and an AAD GUID
(`issue:187ce3fe3b93`) have each already been written into a `bigint` column
here; the Slack callback now explicitly skips the write instead
(`slack/oauth_callback.py`, TASK-4666).

## History

- **FEAT-729 / TASK-4664** routed the Jira identity write through
  `IdentityStore.save_linked_identity`, creating a *third* copy — the one with
  no reader at all.
- Its two reviews disagreed on the owner: the Completion Note said the Identity
  Vault, the independent re-verification said the Session Vault, because that
  was the copy with a live reader. `issue:2e85cce93cab` was opened to force the
  decision.
- **FEAT-735** settled it: the Identity Vault owns the credential; the live
  reader that argued for the Session Vault was the stale badge, which was
  itself the defect.
