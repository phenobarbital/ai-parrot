---
type: Concept
title: parse_bot_permissions()
id: func:parrot.auth.agent_guard.parse_bot_permissions
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Validate and parse the JSONB shape stored in ``ai_bots.permissions``.
---

# parse_bot_permissions

```python
def parse_bot_permissions(value: dict | list | None) -> list[PolicyRuleConfig]
```

Validate and parse the JSONB shape stored in ``ai_bots.permissions``.

Accepted shapes (all treated as **public** — any authenticated user allowed):
  - ``None``
  - ``{}``
  - ``{"permissions": []}``

Accepted shape (deny-by-default with explicit rules):
  - ``{"permissions": [<PolicyRuleConfig dict>, ...]}``

Forgiving fallback (bare list coerced to canonical shape):
  - ``[<rule dict>, ...]``

Any other shape raises ``ValueError`` so that malformed rows fail loudly
at load time rather than being silently treated as public.

Args:
    value: Raw value read from ``navigator.ai_bots.permissions``.

Returns:
    List of ``PolicyRuleConfig`` instances. Empty list means public.

Raises:
    ValueError: When ``value`` has an unrecognised shape or contains
        invalid rule dicts (e.g., missing required ``action`` field).

Examples::

    >>> parse_bot_permissions(None)
    []
    >>> parse_bot_permissions({})
    []
    >>> parse_bot_permissions({"permissions": []})
    []
    >>> rules = parse_bot_permissions(
    ...     {"permissions": [{"action": "agent:resolve", "effect": "allow",
    ...                       "groups": ["engineering"]}]}
    ... )
    >>> len(rules)
    1
