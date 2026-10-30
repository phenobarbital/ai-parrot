---
id: F031
query_id: Q051
type: read
intent: "R1: read the Jira credential ownership doc — the current stated owner decision."
executed_at: 2026-10-30T12:24:35Z
duration_ms: 0
parent_id: null
depth: 0
merged_from: [FC-032]
---

# F031 — docs/auth/jira-credential-ownership.md (FEAT-735, 2026-10-23): Identity Vault (auth.user_identities) is the durable owner; Redis jira:oauth:* is the live tool path; Session Vault retired for Jira; Slack first-link gap remains

## Summary

Table: `auth.user_identities` = durable owner, written by `IdentityVaultCredentialSink` via `JiraOAuthManager` at link + every refresh, read by `IntegrationsService._identity_token_status`; Redis `jira:oauth:<channel>:<user>` (90d) = hot cache & live tool path (`JiraToolkit` → `OAuthCredentialResolver` → `get_valid_token`); `auth.user_vault_secrets` retired for Jira (keys left in place; `VaultTokenSync` still serves fireflies/workiq/entra/o365). Reader recipe: `IdentityStore(app["authdb"]).get_by_provider(user_id,"jira")` + synchronous `decrypt_credential`. 'Do not put this on the per-call tool path' (G4). Known gap: sink needs `nav_user_id` in OAuth state — Telegram yes (combined login), Teams yes (TASK-4667), Slack no. Never invent a bigint id at the callback (issues a671f989e8e7, 187ce3fe3b93).

## Citations

- path: `docs/auth/jira-credential-ownership.md`
  lines: 1-20
  symbol: `The answer`
  excerpt: |
    | auth.user_identities (Identity Vault) | durable owner | IdentityVaultCredentialSink via JiraOAuthManager | IntegrationsService._identity_token_status |
    | Redis jira:oauth:<channel>:<user> (TTL 90 d) | hot cache, the live tool path | JiraOAuthManager._write_token | JiraToolkit -> OAuthCredentialResolver.resolve -> get_valid_token |
    | auth.user_vault_secrets (Session Vault) | retired for Jira | nothing | nothing |
- path: `docs/auth/jira-credential-ownership.md`
  lines: 24-40
  symbol: `Adding a reader`
  excerpt: |
    store = IdentityStore(app["authdb"])
    identity = await store.get_by_provider(user_id, "jira")
    token = store.decrypt_credential(identity)  # SYNCHRONOUS
- path: `docs/auth/jira-credential-ownership.md`
  lines: 60-80
  symbol: `Known gap`
  excerpt: |
    | Telegram | yes — the combined login sets it (post_auth_jira.py) |
    | MS Teams | yes for an authenticated user, since FEAT-729 / TASK-4667 |
    | Slack | no — it sends team_id / slack_user_id |

## Notes

This is a recent (7 days old) architectural decision the proposal must build on, not overturn: durable owner = navigator-auth Identity Vault keyed by nav user_id + provider; Redis stays as the hot cache keyed by channel. The brainstorm's 'dual-read migration' may reduce to re-keying the hot cache or reading the Identity Vault by principal.
