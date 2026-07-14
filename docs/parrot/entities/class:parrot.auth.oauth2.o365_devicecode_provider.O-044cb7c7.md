---
type: Wiki Entity
title: O365DeviceCodeCredentialResolver
id: class:parrot.auth.oauth2.o365_devicecode_provider.O365DeviceCodeCredentialResolver
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Device-code (headless) credential resolver for O365 (FEAT-266).
relates_to:
- concept: class:parrot.auth.credentials.CredentialResolver
  rel: extends
---

# O365DeviceCodeCredentialResolver

Defined in [`parrot.auth.oauth2.o365_devicecode_provider`](../summaries/mod:parrot.auth.oauth2.o365_devicecode_provider.md).

```python
class O365DeviceCodeCredentialResolver(CredentialResolver)
```

Device-code (headless) credential resolver for O365 (FEAT-266).

Implements the :class:`~parrot.auth.credentials.CredentialResolver`
contract so the broker can gate any tool declaring
``credential_provider="o365"`` with ``auth="device_code"`` through this
flow. CLI-only — see module docstring for the resolution steps.

Args:
    o365_client: Configured :class:`~parrot.interfaces.o365.O365Client`
        used for the device-code engine (``interactive_login``).
    o365_oauth_manager: :class:`~parrot.auth.o365_oauth.O365OAuthManager`
        used for the silent refresh primitive
        (``refresh_access_token``).
    vault_token_sync: :class:`~parrot.services.vault_token_sync.VaultTokenSync`
        instance used to persist/read the canonical ``o365:*`` token
        set. CLI callers should construct this instance with a
        non-Telegram ``session_scheme`` (e.g. ``"cli-persistent"``).
    scopes: Requested device-code scopes (defaults to
        ``DEFAULT_O365_SCOPES``, which includes ``offline_access`` so a
        refresh token is granted).
    prompt_callback: Callback invoked with the device-flow payload
        (``verification_uri``, ``user_code``, ``expires_in``,
        ``message``). Defaults to :func:`_default_prompt_callback`
        (prints to stdout).

## Methods

- `async def resolve(self, channel: str, user_id: str) -> Optional[str]` — Return a valid Entra access token for ``user_id``.
- `async def get_auth_url(self, channel: str, user_id: str) -> str` — Return the Microsoft device-login verification URI.
- `async def is_connected(self, channel: str, user_id: str) -> bool` — Return True when a non-expired ``o365:*`` token exists for ``user_id``.
