---
type: Wiki Entity
title: SessionManager
id: class:parrot_tools.scraping.session_manager.SessionManager
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Manage Playwright ``BrowserContext``s keyed by session label.
---

# SessionManager

Defined in [`parrot_tools.scraping.session_manager`](../summaries/mod:parrot_tools.scraping.session_manager.md).

```python
class SessionManager
```

Manage Playwright ``BrowserContext``s keyed by session label.

Args:
    browser: A live Playwright ``Browser`` instance.
    default_context_kwargs: Keyword arguments applied to every context
        (viewport, locale, storage_state, proxy, …).
    session_configs: Optional per-session overrides merged on top of
        ``default_context_kwargs`` (e.g. a distinct ``storage_state`` for
        an authenticated session).

## Methods

- `async def get_context(self, session: str) -> Any` — Return the ``BrowserContext`` for *session*, creating it lazily.
- `async def new_page(self, session: str) -> Any` — Create and return a new ``Page`` within *session*'s context.
- `def precompute_last_use(self, topo_order: List[FlowNode]) -> Dict[str, str]` — Record the last node id that uses each session, in topo order.
- `async def close_if_last(self, session: str, node_id: str) -> None` — Close *session*'s context if *node_id* was its last user.
- `async def close_all(self) -> None` — Close every remaining context (cleanup safety net).
