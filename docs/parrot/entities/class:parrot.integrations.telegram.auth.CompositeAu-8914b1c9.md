---
type: Wiki Entity
title: CompositeAuthStrategy
id: class:parrot.integrations.telegram.auth.CompositeAuthStrategy
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Multi-method auth router.
relates_to:
- concept: class:parrot.integrations.telegram.auth.AbstractAuthStrategy
  rel: extends
---

# CompositeAuthStrategy

Defined in [`parrot.integrations.telegram.auth`](../summaries/mod:parrot.integrations.telegram.auth.md).

```python
class CompositeAuthStrategy(AbstractAuthStrategy)
```

Multi-method auth router.

Owns a dict of per-method strategies keyed by their canonical ``.name``
(``"basic"``, ``"azure"``). At callback time, it reads
``data["auth_method"]`` and dispatches to the matching member. A single
WebApp button points to ``login_multi.html`` which shows all available
sign-in methods to the user.

Note: ``oauth2`` cannot be combined with other methods — ``login_multi.html``
does not implement an OAuth2 flow.  The config validator (TASK-784 /
TASK-I2) enforces this constraint at startup.

Class Attributes:
    name: ``"composite"`` — used in logs and config validation.
    supports_post_auth_chain: Instance-level property (not a plain class
        attribute). Returns ``True`` only when **every** member strategy
        supports the post-auth chain (AND semantics).  Always access this
        on an *instance*; ``CompositeAuthStrategy.supports_post_auth_chain``
        at class level returns the property descriptor object itself.

Args:
    strategies: Mapping of strategy name → strategy instance. Must
        contain at least one entry.
    login_page_url: URL of ``login_multi.html`` served as the WebApp
        page. Must be non-empty.

Raises:
    ValueError: If ``strategies`` is empty or ``login_page_url`` is unset.

## Methods

- `def supports_post_auth_chain(self) -> bool` — Return True only when all member strategies support the chain.
- `async def build_login_keyboard(self, config: Any, state: str, *, next_auth_url: Optional[str]=None, next_auth_required: bool=False) -> ReplyKeyboardMarkup` — Build a WebApp keyboard pointing at ``login_multi.html``.
- `async def handle_callback(self, data: Dict[str, Any], session: TelegramUserSession) -> bool` — Dispatch the WebApp callback to the matching member strategy.
- `async def validate_token(self, token: str, session: Optional['TelegramUserSession']=None) -> bool` — Validate a session token against the correct member strategy.
