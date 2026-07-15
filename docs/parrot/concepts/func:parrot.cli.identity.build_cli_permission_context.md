---
type: Concept
title: build_cli_permission_context()
id: func:parrot.cli.identity.build_cli_permission_context
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Build the CLI ``PermissionContext`` for the O365 device-code broker seam.
---

# build_cli_permission_context

```python
def build_cli_permission_context(user_id: Optional[str]=None) -> PermissionContext
```

Build the CLI ``PermissionContext`` for the O365 device-code broker seam.

Args:
    user_id: Optional pre-resolved canonical identity. When omitted,
        it is resolved via :func:`resolve_cli_o365_principal` (reads
        ``O365_PRINCIPAL`` from the environment).

Returns:
    A :class:`~parrot.auth.permission.PermissionContext` with
    ``channel="cli"`` and the canonical ``user_id``, ready to pass to
    ``AbstractBot.ask(permission_context=...)`` /
    ``AbstractBot.ask_stream(permission_context=...)``. The session's
    ``tenant_id`` is read from ``O365_TENANT_ID`` when set, otherwise
    falls back to the :data:`UNSET_CLI_TENANT` sentinel (FEAT-267) —
    never ``CLI_CHANNEL``/``"cli"``.

Raises:
    RuntimeError: No principal could be resolved (fail closed —
        propagated from :func:`resolve_cli_o365_principal`).
