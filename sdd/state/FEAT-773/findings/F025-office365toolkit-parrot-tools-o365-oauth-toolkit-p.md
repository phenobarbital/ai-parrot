---
id: F025
query_id: Q045
type: read
intent: "R5/O365: read the O365 per-user OAuth toolkit (delegated token source, O365AuthMode)."
executed_at: 2026-10-30T12:24:35Z
duration_ms: 0
parent_id: null
depth: 0
merged_from: [FC-026]
---

# F025 — Office365Toolkit (parrot_tools/o365/oauth_toolkit.py) resolves per-user Graph tokens via CredentialResolver in _pre_execute, declares credential_provider='o365' for the broker seam, raises AuthorizationRequired on miss

## Summary

`parrot_tools/o365/oauth_toolkit.py` (413 lines). `Office365Toolkit(AbstractToolkit)` with `credential_provider = "o365"` (:69) — when a broker is attached the seam raises `CredentialRequired` before `_pre_execute`; without a broker the legacy `_pre_execute` (:102-168) reads `_permission_context`, requires `user_id`, `channel = perm_ctx.channel or "unknown"`, calls `credential_resolver.resolve(channel, user_id)` and raises `AuthorizationRequired(provider="o365", auth_url=get_auth_url(...))` on `None`; caches an aiohttp session per `channel:user_id`, evicts on 401. Tools: `read_inbox`, `search_messages`, `send_email`, `list_onedrive_files`, `list_sharepoint_sites`, `list_upcoming_events`.

## Citations

- path: `packages/ai-parrot-tools/src/parrot_tools/o365/oauth_toolkit.py`
  lines: 37-69
  symbol: `Office365Toolkit`
  excerpt: |
    class Office365Toolkit(AbstractToolkit):
        credential_provider: Optional[str] = "o365"
- path: `packages/ai-parrot-tools/src/parrot_tools/o365/oauth_toolkit.py`
  lines: 102-150
  symbol: `Office365Toolkit._pre_execute`
  excerpt: |
    user_id = getattr(perm_ctx, "user_id", None)
    channel = getattr(perm_ctx, "channel", None) or "unknown"
    token_set = await self.credential_resolver.resolve(channel, user_id)
    if token_set is None:
        auth_url = await self.credential_resolver.get_auth_url(channel, user_id)
        raise AuthorizationRequired(...)
    user_key = f"{channel}:{user_id}"

## Notes

Two O365 tool families exist: this delegated 3LO toolkit and the older `o365/base.py` `O365Tool` with `O365AuthMode` (FC-027). Pattern is identical to JiraToolkit (FC-030).
