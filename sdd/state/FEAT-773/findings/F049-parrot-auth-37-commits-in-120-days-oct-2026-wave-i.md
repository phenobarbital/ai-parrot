---
id: F049
query_id: Q060
type: git_log
intent: "History: recent commits on parrot/auth (broker, oauth2, routes) — what landed in the last 120 days."
executed_at: 2026-10-30T12:05:12Z
duration_ms: 900
parent_id: null
depth: 0
merged_from: [FG-001]
---

# F049 — parrot/auth: 37 commits in 120 days; Oct 2026 wave is Jira-credential ownership + Teams user-auth lane

## Summary

37 commits (2026-07-03 → 2026-10-23) touched `packages/ai-parrot/src/parrot/auth/`; authors Jesus Lara / Jesus (plus `revbot` for agentstudio). Dominant themes, newest first: (1) **services-vault-token-sync-tech-debt** (2026-10-23, TASK-4668/4669/4670) — `JiraOAuthManager` gained an optional structural `CredentialSink` Protocol so a refresh and a link both propagate the Jira grant to navigator-auth's Identity Vault (`auth.user_identities`); the integrations badge now reads that owner for Jira. (2) **msteams-user-auth-lane** (2026-10-23, TASK-4660/4661/4663) — new `parrot/auth/token_exchange.py` (165 lines) for Teams token exchange with a fail-closed gate. (3) **jiratoolkit-upgrades** (2026-10-16/17, TASK-4418) — 3LO helpers (`exchange_code`, `refresh_access_token`, `fetch_accessible_resources`, `fetch_myself`) extracted in `jira_oauth.py` (+144/-41) and later hardened (error-body truncation, CSRF state check for CLI). (4) **vault-crypto-hardening** (2026-09-16, TASK-079/082) — envelope v2 context-bound seal/open in `security/credentials_utils.py`, process-wide KeyRing in `vault_utils.py`, and `oauth2/service.py` + `oauth2/models.py` gained an `IntegrationDescriptor.status` (connected | disconnected | needs_reconnect) probed from `VaultTokenSync`. (5) **BYOK** (2026-08-27, TASK-2516) — `parrot/auth/broker.py` grew a CredentialBroker resolver for per-user LLM keys (+148 lines). No commit in this window creates a `connections` module, a generic `ConnectionManager`, or touches `oauth2_routes.py` directly. Note: the broker lived at `parrot/auth/broker.py` in Aug–Sep 2026; the wiki now lists `parrot/auth/broker/core.py` — a package split happened (cross-lane check).

## Citations

(none)

## Notes

- Everything in the Oct-23 wave is about *who owns the Jira credential* — the exact question the brainstorm's spike S1 asks. The answer in git: the Identity Vault row in `auth.user_identities` (navigator-auth), fed by a `CredentialSink`; the Session Vault (`VaultTokenSync`) copy of Jira tokens was being retired (see FG-002/FG-003).
- Nothing in 120 days created `parrot.connections`, `ConnectionManager`, `OAuthProviderRegistry` or `connection.*` events.
- [cross-lane: type=read, intent=confirm the broker package split — `parrot/auth/broker.py` (Aug–Sep 2026) vs `parrot/auth/broker/core.py` (wiki); cite the current path]
- [cross-lane: type=read, intent=read `parrot/auth/token_exchange.py` (TASK-4660) — a second token-exchange helper besides `jira_oauth.py`; candidate for the generic manager]
- [cross-lane: type=read, intent=read `parrot/auth/oauth2/service.py` + `oauth2/models.py` — `IntegrationsService`, `IntegrationDescriptor.status`, `_token_status`/`_identity_token_status`: this is already a per-user "connections list" API]
