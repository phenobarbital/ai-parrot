---
type: Concept
title: resolve_cli_o365_principal()
id: func:parrot.cli.identity.resolve_cli_o365_principal
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Read and normalize the CLI's canonical O365 principal from the environment.
---

# resolve_cli_o365_principal

```python
def resolve_cli_o365_principal() -> str
```

Read and normalize the CLI's canonical O365 principal from the environment.

Returns:
    The canonical identity string (lower-cased email or Entra OID).

Raises:
    RuntimeError: ``O365_PRINCIPAL`` is unset/blank, or does not
        normalize to a canonical identity. Fails closed — the
        device-code resolver must never operate under an anonymous
        vault key.
