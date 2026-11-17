---
id: FC-011
query_id: Q030
type: read
intent: "R1: read vault_utils — shared encrypted-credential CRUD helpers (storage, envelope)."
executed_at: 2026-10-30T12:24:35Z
duration_ms: 0
parent_id: null
depth: 0
---

# FC-011 — vault_utils stores AES-GCM-encrypted credentials in DocumentDB `user_credentials` keyed (user_id, vault_name), with a pluggable Postgres store (VAULT_STORE=postgres); oauth2_vault_name = oauth2_{provider}_{channel}_{user_id}

## Summary

`parrot/security/vault_utils.py` (211 lines, core). `store/retrieve/delete_vault_credential(user_id, vault_name, …)` encrypt via `parrot.security.credentials_utils` (envelope v2, AES-GCM, `KeyRing` from navigator-session) into DocumentDB collection `user_credentials` under `{user_id, name}`; `set_vault_credential_store(store)` lets the server register a Postgres store (TASK-3953, `navigator.ai_user_credentials`) so core never imports server code. `oauth2_vault_name(provider_id, channel, user_id)` → `oauth2_{provider_id}_{channel}_{user_id}` — channel is part of the vault name.

## Citations

- path: `packages/ai-parrot/src/parrot/security/vault_utils.py`
  lines: 43-49
  symbol: `set_vault_credential_store`
  excerpt: |
    _PG_VAULT_STORE: Any = None
    def set_vault_credential_store(store): # Server registers its Postgres store at startup (VAULT_STORE=postgres). Core never imports server code.
- path: `packages/ai-parrot/src/parrot/security/vault_utils.py`
  lines: 92-143
  symbol: `store_vault_credential`
  excerpt: |
    async def store_vault_credential(user_id: str, vault_name: str, secret_params: Dict[str, Any]):
        if _PG_VAULT_STORE is not None: return await _PG_VAULT_STORE.store(user_id, vault_name, secret_params)
        encrypted = encrypt_credential(secret_params, credential_context(user_id, vault_name), keyring)
- path: `packages/ai-parrot/src/parrot/security/vault_utils.py`
  lines: 205-211
  symbol: `oauth2_vault_name`
  excerpt: |
    def oauth2_vault_name(provider_id: str, channel: str, user_id: str) -> str:
        return f"oauth2_{provider_id}_{channel}_{user_id}"

## Notes

Spike S1 answer (part 2): a THIRD credential store exists (DocumentDB/Postgres `user_credentials`), used by `AbstractOAuth2Manager` (FC-052) and MCP `VaultTokenStore` (FC-042). Its OAuth2 key embeds `channel` — the exact channel-binding the brainstorm wants removed. Encryption at rest: yes (AES-GCM envelope v2).
