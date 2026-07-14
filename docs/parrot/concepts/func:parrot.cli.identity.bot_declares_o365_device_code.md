---
type: Concept
title: bot_declares_o365_device_code()
id: func:parrot.cli.identity.bot_declares_o365_device_code
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Return True when ``bot`` declares an ``o365``/``device_code`` credential.
---

# bot_declares_o365_device_code

```python
def bot_declares_o365_device_code(bot: object) -> bool
```

Return True when ``bot`` declares an ``o365``/``device_code`` credential.

Used by the CLI entry point (``parrot.cli.agent_repl``) to decide
whether to bootstrap a device-code ``PermissionContext`` (and therefore
enforce ``O365_PRINCIPAL``) for this particular agent — agents that
don't declare the o365 device-code provider are completely unaffected.

Args:
    bot: The loaded agent instance (an ``AbstractBot``).

Returns:
    True if any entry in ``bot._credentials`` declares
    ``provider="o365"`` with ``auth="device_code"``.
