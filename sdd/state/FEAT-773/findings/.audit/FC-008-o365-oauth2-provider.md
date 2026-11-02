---
id: FC-008
query_id: Q027
type: read
intent: "Registry: read the O365 OAuth2 provider descriptor to learn the OAuth2Provider base contract."
executed_at: 2026-10-30T12:24:35Z
duration_ms: 0
parent_id: null
depth: 0
---

# FC-008 — O365OAuth2Provider is a thin descriptor (provider_id, display_name, icon, default_scopes, pbac_action_namespace) wrapping O365OAuthManager with a toolkit_factory

## Summary

`parrot/auth/oauth2/o365_provider.py` (75 lines). `O365OAuth2Provider(OAuth2Provider)` with class attrs `provider_id="o365"`, `display_name="Office 365"`, `icon="mdi:microsoft-office"`, `default_scopes=[openid, profile, offline_access, User.Read, Mail.Read, Mail.Send, Files.Read, Files.ReadWrite, Sites.Read.All, Calendars.Read]`, `pbac_action_namespace="integration"`. `manager` property returns the injected `O365OAuthManager`; `toolkit_factory(credential_resolver)` returns `Office365Toolkit(credential_resolver=..., tenant_id=manager.tenant_id or "common")`. Registration recipe in docstring: construct manager, `manager.setup()`, `register_oauth2_provider(O365OAuth2Provider(manager=manager))`.

## Citations

- path: `packages/ai-parrot/src/parrot/auth/oauth2/o365_provider.py`
  lines: 32-58
  symbol: `O365OAuth2Provider`
  excerpt: |
    class O365OAuth2Provider(OAuth2Provider):
        provider_id: str = "o365"
        display_name: str = "Office 365"
        icon: str = "mdi:microsoft-office"
        default_scopes: List[str] = ["openid","profile","offline_access","User.Read","Mail.Read","Mail.Send","Files.Read","Files.ReadWrite","Sites.Read.All","Calendars.Read"]
        pbac_action_namespace: str = "integration"
- path: `packages/ai-parrot/src/parrot/auth/oauth2/o365_provider.py`
  lines: 67-75
  symbol: `O365OAuth2Provider.toolkit_factory`
  excerpt: |
    def toolkit_factory(self, credential_resolver) -> Office365Toolkit:
        return Office365Toolkit(credential_resolver=credential_resolver, tenant_id=getattr(self._manager, "tenant_id", "common"))

## Notes

Provider behaviour (endpoints, PKCE, refresh) is NOT in the descriptor — it lives in the manager subclass (`O365OAuthManager`, FC-049). The descriptor is UI/PBAC metadata + toolkit factory.
