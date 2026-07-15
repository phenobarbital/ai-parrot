---
type: Wiki Summary
title: parrot.auth.oauth2.o365_devicecode_provider
id: mod:parrot.auth.oauth2.o365_devicecode_provider
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: O365 device-code (headless) credential resolver — FEAT-266.
relates_to:
- concept: class:parrot.auth.oauth2.o365_devicecode_provider.O365DeviceCodeCredentialResolver
  rel: defines
- concept: mod:parrot.auth.credentials
  rel: references
- concept: mod:parrot.auth.o365_oauth
  rel: references
---

# `parrot.auth.oauth2.o365_devicecode_provider`

O365 device-code (headless) credential resolver — FEAT-266.

Wraps the existing :meth:`O365Client.interactive_login` device-code engine
to provide a :class:`~parrot.auth.credentials.CredentialResolver` for the
broker's ``device_code`` auth kind. CLI-only: :meth:`resolve` blocks inline
and returns the token on success — it does NOT raise
:class:`~parrot.auth.credentials.CredentialRequired` on the happy path.

Resolution steps:

1. Read the user's ``o365:*`` token set from
   :class:`~parrot.services.vault_token_sync.VaultTokenSync`. If
   ``access_token`` is present and not near expiry, return it (cache hit).
2. If expired and a ``refresh_token`` is present, silently refresh via
   :meth:`O365OAuthManager.refresh_access_token`, re-persist, and return.
   On :class:`PermissionError` (dead refresh token), fall through to the
   device-code flow.
3. On a vault miss (or dead refresh), run
   ``O365Client.interactive_login(open_browser=False, device_flow_callback=…)``
   inline. The callback surfaces ``verification_uri`` + ``user_code`` via an
   injected ``prompt_callback`` (default: print to stdout). On success, the
   canonical token set is persisted to ``VaultTokenSync`` under prefix
   ``"o365"`` and ``access_token`` is returned.

Canonical ``o365:*`` field contract (persisted EXACTLY these fields):
``access_token``, ``refresh_token``, ``expires_at`` (epoch seconds),
``scope``, ``id_token`` (optional), ``tenant_id``.

Device-code is CLI-only — Telegram is explicitly out of scope (spec §1
Non-Goals). Callers MUST construct the injected ``vault_token_sync`` with a
non-Telegram ``session_scheme`` (e.g. ``"cli-persistent"``) so tokens are not
filed under :class:`~parrot.services.vault_token_sync.VaultTokenSync`'s
default Telegram-namespaced session-uuid scheme.

## Classes

- **`O365DeviceCodeCredentialResolver(CredentialResolver)`** — Device-code (headless) credential resolver for O365 (FEAT-266).
