---
type: Wiki Entity
title: PostAuthProvider
id: class:parrot.integrations.core.auth.post_auth.PostAuthProvider
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Protocol for secondary authentication providers.
---

# PostAuthProvider

Defined in [`parrot.integrations.core.auth.post_auth`](../summaries/mod:parrot.integrations.core.auth.post_auth.md).

```python
class PostAuthProvider(Protocol)
```

Protocol for secondary authentication providers.

Implementations must declare a class-level ``provider_name`` attribute
(the key used in YAML ``post_auth_actions``) and implement the two
async methods below.

Attributes:
    provider_name: Unique name of the provider (e.g., ``"jira"``).
        Matches the ``provider`` field of ``PostAuthAction`` in YAML.

## Methods

- `async def build_auth_url(self, session: Any, config: Any, callback_base_url: str) -> str` — Return the authorization URL the login page should redirect to.
- `async def handle_result(self, data: Dict[str, Any], session: Any, primary_auth_data: Dict[str, Any]) -> bool` — Process the secondary auth result payload from the callback.
