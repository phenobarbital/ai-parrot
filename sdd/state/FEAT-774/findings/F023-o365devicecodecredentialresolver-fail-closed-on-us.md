---
id: F023
query_id: Q036
type: read
intent: "O365 device-code resolver internals"
executed_at: 2026-10-30T15:23:31Z
duration_ms: 0
parent_id: null
depth: 0
merged_from: [FC-023]
---

# F023 — O365DeviceCodeCredentialResolver: fail-closed on user_id, vault read/refresh/device flow, prompt_callback prints to stdout

## Summary

Resolution: read `o365:*` from `VaultTokenSync` (cache hit if `expires_at` valid; missing expires_at = expired), silent refresh via `O365OAuthManager.refresh_access_token` (PermissionError → device flow), else blocking `interactive_login` with `prompt_callback` (default prints URL + code to stdout). Persists canonical `access_token, refresh_token, expires_at, scope, id_token, tenant_id`. Callers must use a non-Telegram `session_scheme` (e.g. `"cli-persistent"`).

## Citations

- path: `packages/ai-parrot/src/parrot/auth/oauth2/o365_devicecode_provider.py`
  lines: 100-116, 117-178, 180-186
  symbol: `__init__ / resolve / get_auth_url`
  excerpt: |
    def __init__(self, o365_client, o365_oauth_manager, vault_token_sync, scopes=None, prompt_callback=None)
    async def resolve(self, channel: str, user_id: str) -> Optional[str]:
        if not user_id: raise ValueError("... refusing to resolve under an anonymous vault key.")
        tokens = await self._vault.read_tokens(user_id, _O365_VAULT_PREFIX)
        ...
        return await self._run_device_flow(user_id)
    async def get_auth_url(self, channel: str, user_id: str) -> str: return _DEVICE_LOGIN_URL
- path: `packages/ai-parrot/src/parrot/auth/oauth2/o365_devicecode_provider.py`
  lines: 57-70
  symbol: `_default_prompt_callback`
  excerpt: |
    print(message)  # user-facing CLI prompt, bypasses logger

## Notes

Pattern reusable for S-4 CLI UX (prompt_callback injection) but engine is MSAL/O365-bound. stdout printing would corrupt a stdio MCP server's JSON-RPC channel — prompts must go to stderr or the host there.
