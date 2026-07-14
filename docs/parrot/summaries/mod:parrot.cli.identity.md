---
type: Wiki Summary
title: parrot.cli.identity
id: mod:parrot.cli.identity
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: CLI identity bootstrap for the O365 device-code broker seam (FEAT-266).
relates_to:
- concept: func:parrot.cli.identity.bot_declares_o365_device_code
  rel: defines
- concept: func:parrot.cli.identity.build_cli_permission_context
  rel: defines
- concept: func:parrot.cli.identity.resolve_cli_o365_principal
  rel: defines
- concept: mod:parrot.auth.identity
  rel: references
- concept: mod:parrot.auth.permission
  rel: references
---

# `parrot.cli.identity`

CLI identity bootstrap for the O365 device-code broker seam (FEAT-266).

The O365 device-code resolver (``O365DeviceCodeCredentialResolver``) fails
closed without a canonical per-user identity (spec §1/§7). The CLI is the
only surface for device-code (Telegram explicitly excluded), so this module
reads the explicit Entra principal from the ``O365_PRINCIPAL`` environment
variable, normalizes it via :class:`~parrot.auth.identity.CanonicalIdentityMapper`,
and builds the :class:`~parrot.auth.permission.PermissionContext` that
``AbstractBot.ask(permission_context=...)`` threads through to the
``ToolManager`` → ``AbstractTool`` credential seam (see
``tools/manager.py`` around the ``_cred_channel``/``_cred_user_id``
injection and ``tools/abstract.py``'s broker gate).

## Functions

- `def resolve_cli_o365_principal() -> str` — Read and normalize the CLI's canonical O365 principal from the environment.
- `def build_cli_permission_context(user_id: Optional[str]=None) -> PermissionContext` — Build the CLI ``PermissionContext`` for the O365 device-code broker seam.
- `def bot_declares_o365_device_code(bot: object) -> bool` — Return True when ``bot`` declares an ``o365``/``device_code`` credential.
