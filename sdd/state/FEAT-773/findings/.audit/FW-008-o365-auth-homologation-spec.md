---
id: FW-008
query_id: Q008
type: wiki_page
intent: "Read spec: O365 auth homologation — decides delegated O365 token source."
executed_at: 2026-10-30T12:10:52Z
duration_ms: 0
parent_id: null
depth: 0
---

# FW-008 — FEAT-266 (approved, 6 tasks done 2026-07-01): O365 has `O365OAuthManager` (PKCE, `AbstractOAuth2Manager` subclass) + `O365OAuth2Provider` + broker `device_code` kind; canonical per-user Entra store = `VaultTokenSync` flat `o365:*`; Gen-1 `/api/v1/o365/auth/sessions` deleted

## Summary

The brainstorm's O365 rows ("`O365AuthMode.DELEGATED`, older Svelte page hitting `/api/o365/oauth/initiate|status`") are superseded. FEAT-266 found three O365 auth generations; Gen 1 (`services/o365_remote_auth.py`, `handlers/o365_auth.py`, REST polling sessions) was DELETED (TASK-1686, no consumers). Active: `O365OAuthManager(AbstractOAuth2Manager)` in `parrot/auth/o365_oauth.py` (provider_id `o365`, PKCE S256 + client_secret, tenant `common`, Graph `/me` identity, `refresh_access_token` public), `Office365Toolkit` (`parrot_tools/o365/oauth_toolkit.py`), `O365OAuth2Provider` in the registry, and `O365DeviceCodeCredentialResolver` (`auth/oauth2/o365_devicecode_provider.py`) as a broker `device_code` strategy for CLI (`O365_PRINCIPAL` env → `CanonicalIdentityMapper`). Spec names `VaultTokenSync` prefix `o365` with a fixed field contract (`access_token`, `refresh_token`, `expires_at`, `scope`, `id_token`, `tenant_id`) as the canonical per-user Entra store, and records that the 3LO browser flow writes `vault_utils` (`oauth2_o365_{channel}_{user_id}`) instead — a `post_auth_o365` bridge was deferred as a follow-up. `NeedsAuth`/`CredentialRequired` gained optional `user_code`/`verification_uri`/`expires_in`.

## Citations

- path: `sdd/specs/o365-auth-homologation.spec.md`
  lines: n/a
  symbol: FEAT-266 §1 three generations, §2, §6 contract (`credentials.py:43 AuthKind`, `:82 NeedsAuth`, `:97 CredentialRequired`, `:128 CredentialResolver`; `broker.py:66 CredentialResolverFactory`, `:280 CredentialBroker`, `:405 resolve`; `interfaces/o365.py:115 O365Client`, `:763 interactive_login`, `:621 acquire_token_on_behalf_of`; `o365_oauth.py:55`, `:140 _refresh_request`; `identity.py:57`; `tools/abstract.py:36 current_credential`)
  wiki_page_id: ledger::spec:o365-auth-homologation.spec (score=0.47)
- path: `packages/ai-parrot/src/parrot/auth/o365_oauth.py`
  lines: n/a
  symbol: `O365TokenSet`, `O365OAuthManager` (`provider_id="o365"`, `use_pkce=True`, `require_client_secret=True`, `refresh_access_token`, `_discover_identity` Graph `/me`), `DEFAULT_O365_SCOPES`
  wiki_page_id: file:packages/ai-parrot/src/parrot/auth/o365_oauth.py
- path: `packages/ai-parrot/src/parrot/auth/oauth2/o365_devicecode_provider.py`
  lines: n/a
  symbol: `O365DeviceCodeCredentialResolver`
- path: `packages/ai-parrot-tools/src/parrot_tools/o365/oauth_toolkit.py`
  lines: n/a
  symbol: Office 365 toolkit with per-user OAuth 2.0 (delegated / 3LO) auth
  wiki_page_id: file:packages/ai-parrot-tools/src/parrot_tools/o365/oauth_toolkit.py (score=0.24)
- path: `sdd/tasks/index/o365-auth-homologation.json`
  lines: n/a
  symbol: TASK-1681..1686 all `done`, completed 2026-07-01

## Notes

`[cross-lane: type=grep, intent=confirm /api/o365/oauth routes do NOT exist anymore and whether O365AuthMode enum exists in parrot_tools/o365/base.py]`. Open gap the proposal can claim: the O365 3LO browser flow (vault_utils key) and the device-code CLI flow (`VaultTokenSync o365:*`) still write different stores — the "post_auth_o365 bridge" follow-up was never filed as a FEAT per this lane's search.
