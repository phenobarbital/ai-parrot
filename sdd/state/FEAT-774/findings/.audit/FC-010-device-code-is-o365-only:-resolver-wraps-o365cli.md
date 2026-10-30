---
id: FC-010
query_id: Q023
type: grep
intent: "Is device-code generic or O365-only"
executed_at: 2026-10-30T15:23:31Z
duration_ms: 0
parent_id: null
depth: 0
---

# FC-010 — Device-code is O365-only: resolver wraps O365Client.interactive_login

## Summary

`O365DeviceCodeCredentialResolver` (o365_devicecode_provider.py:73) is the sole `device_code` strategy; it wraps `O365Client.interactive_login(open_browser=False, device_flow_callback=…)` and persists `o365:*` via `VaultTokenSync`. `o365_oauth.py` has `O365TokenSet(AbstractOAuth2TokenSet)` / `O365OAuthManager(AbstractOAuth2Manager)` (lines 44, 55) with no device-code endpoint handling of its own. There is no provider-neutral device-code engine.

## Citations

- path: `packages/ai-parrot/src/parrot/auth/oauth2/o365_devicecode_provider.py`
  lines: 1-7, 73-79, 206-222
  symbol: `O365DeviceCodeCredentialResolver._run_device_flow`
  excerpt: |
    Wraps the existing :meth:`O365Client.interactive_login` device-code engine ... CLI-only
    class O365DeviceCodeCredentialResolver(CredentialResolver):
    result = await self._o365.interactive_login(scopes=self._scopes, open_browser=False, device_flow_callback=_on_device_flow)

- path: `packages/ai-parrot/src/parrot/auth/o365_oauth.py`
  lines: 44, 55
  symbol: `O365TokenSet / O365OAuthManager`
  excerpt: |
    class O365TokenSet(AbstractOAuth2TokenSet):
    class O365OAuthManager(AbstractOAuth2Manager):


## Notes

A generic RFC 8628 device flow would be new work in S-4 (descriptor field `device_authorization_url` is not in the S-1 descriptor — see FC-033).
