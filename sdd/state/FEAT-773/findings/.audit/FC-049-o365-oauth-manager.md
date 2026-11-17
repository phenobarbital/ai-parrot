---
id: FC-049
query_id: Q027-F1
type: read
intent: "Follow-up: read parrot/auth/o365_oauth.py — the O365 manager built on the generic base."
executed_at: 2026-10-30T12:24:35Z
duration_ms: 0
parent_id: FC-008
depth: 1
---

# FC-049 — O365OAuthManager(AbstractOAuth2Manager) implements the four provider hooks for Microsoft identity platform: PKCE on, tenant-templated endpoints, prompt=select_account, refresh via grant_type=refresh_token, identity via Graph /me

## Summary

227 lines. `DEFAULT_O365_SCOPES` (10 scopes incl. offline_access). `O365TokenSet(AbstractOAuth2TokenSet)` adds `tenant_id`. `O365OAuthManager(AbstractOAuth2Manager)`: `use_pkce: ClassVar[bool] = True`; `__init__(..., tenant_id="common")` builds `https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/{authorize,token}`; `authorization_url_extra_params` → `prompt=select_account` (Microsoft's documented way to ensure a refresh_token comes back); `_exchange_code(code, code_verifier)`; `_refresh_request(refresh_token)` raises PermissionError on 400/401 invalid_grant; public `refresh_access_token`; `_discover_identity` (Graph); `_build_token_set`.

## Citations

- path: `packages/ai-parrot/src/parrot/auth/o365_oauth.py`
  lines: 55-90
  symbol: `O365OAuthManager`
  excerpt: |
    class O365OAuthManager(AbstractOAuth2Manager):
        use_pkce: ClassVar[bool] = True
        def __init__(self, ..., tenant_id: str = "common", ...):
            self.authorize_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/authorize"
            self.token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
- path: `packages/ai-parrot/src/parrot/auth/o365_oauth.py`
  lines: 99-110
  symbol: `authorization_url_extra_params`
  excerpt: |
    # prompt=select_account ... Microsoft documented way to ensure a refresh_token comes back
- path: `packages/ai-parrot/src/parrot/auth/o365_oauth.py`
  lines: 113-165
  symbol: `_exchange_code / _refresh_request`
  excerpt: |
    if code_verifier: data["code_verifier"] = code_verifier
    # 400 invalid_grant is Microsoft "your refresh token died" -> PermissionError

## Notes

Spike S2 answer: the reusable PKCE/exchange/refresh machinery is `AbstractOAuth2Manager` (FC-052), already used by O365; the Jira manager is the odd one out.
