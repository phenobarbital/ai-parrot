---
id: F012
query_id: Q031
type: read
intent: "R1: read IdentityMappingService — telegram/teams/web → navigator user link storage and lookup."
executed_at: 2026-10-30T12:24:35Z
duration_ms: 0
parent_id: null
depth: 0
merged_from: [FC-012]
---

# F012 — IdentityMappingService writes auth.user_identities (navigator-auth): channel ids (telegram/msteams/slack) via raw SQL, token-bearing providers (jira) via IdentityStore.save_linked_identity (ciphered)

## Summary

`parrot/services/identity_mapping.py` (347 lines, server). Table `auth.user_identities` (navigator-auth ≥0.28.8): PK `identity_id`, `user_id` bigint FK to `auth.users`, partial unique `(user_id, auth_provider, provider_user_id)`. `upsert_identity(nav_user_id, auth_provider, provider_user_id, auth_data, display_name, email, token?)`: requires numeric nav_user_id and non-null provider_user_id; token-bearing providers go through `IdentityStore.save_linked_identity`. `get_identity(nav_user_id, auth_provider)`, `get_all_identities`, `delete_identity`. Known ledger issue 0115386145f2 (ON CONFLICT 42P10) is fixed by the partial-index arbiter.

## Citations

- path: `packages/ai-parrot-server/src/parrot/services/identity_mapping.py`
  lines: 1-24
  symbol: `module docstring`
  excerpt: |
    Links navigator-auth internal user IDs with external provider identities (Telegram numeric IDs, Teams AAD object ids, Jira account IDs)
    * channel mappings (msteams/slack/telegram) carry no credential and are written with raw SQL
    * token-bearing providers (jira) go through navigator-auth's IdentityStore, which ciphers the credential.
- path: `packages/ai-parrot-server/src/parrot/services/identity_mapping.py`
  lines: 44-53
  symbol: `_UPSERT_SQL`
  excerpt: |
    INSERT INTO auth.user_identities (user_id, auth_provider, provider_user_id, auth_data, display_name, email, created_at)
    ON CONFLICT (user_id, auth_provider, provider_user_id) DO UPDATE ...
- path: `packages/ai-parrot-server/src/parrot/services/identity_mapping.py`
  lines: 136-160
  symbol: `IdentityMappingService`
  excerpt: |
    class IdentityMappingService:
        def __init__(self, db_pool: Any, identity_store: Optional[IdentityStore] = None)
- path: `packages/ai-parrot-server/src/parrot/services/identity_mapping.py`
  lines: 173-268
  symbol: `IdentityMappingService.upsert_identity`
  excerpt: |
    async def upsert_identity(self, nav_user_id, auth_provider: str, provider_user_id, auth_data=None, display_name=None, email=None, token=None, userinfo=None)
        # bigint check; token -> self._get_identity_store().save_linked_identity(user_id, auth_provider, token, userinfo=userinfo)

## Notes

R1 answer: the telegram_id → navigator user link IS stored (`auth.user_identities`, provider `telegram`, written by `JiraPostAuthProvider._write_identity_records`, FC-045). Lookup by `(user_id, provider)` exists; reverse lookup provider_user_id→user_id exists on `IdentityStore.find_user_by_provider_account` (FC-013).
