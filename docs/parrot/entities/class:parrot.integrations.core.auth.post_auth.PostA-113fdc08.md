---
type: Wiki Entity
title: PostAuthRegistry
id: class:parrot.integrations.core.auth.post_auth.PostAuthRegistry
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Registry mapping provider names to ``PostAuthProvider`` instances.
---

# PostAuthRegistry

Defined in [`parrot.integrations.core.auth.post_auth`](../summaries/mod:parrot.integrations.core.auth.post_auth.md).

```python
class PostAuthRegistry
```

Registry mapping provider names to ``PostAuthProvider`` instances.

The registry is populated at wrapper initialization from the
``post_auth_actions`` YAML config. Each entry's ``provider`` string
is used as the registry key.

Example:
    >>> registry = PostAuthRegistry()
    >>> registry.register(JiraPostAuthProvider(oauth_manager))
    >>> provider = registry.get("jira")
    >>> url = await provider.build_auth_url(session, config, base)

## Methods

- `def register(self, provider: PostAuthProvider) -> None` — Register a provider under its ``provider_name``.
- `def get(self, name: str) -> Optional[PostAuthProvider]` — Look up a provider by name.
- `def providers(self) -> List[str]` — Return the list of registered provider names.
