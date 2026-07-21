---
type: Wiki Entity
title: StaticResolver
id: class:parrot.eval.sandbox.fakes.StaticResolver
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Credential resolver that always returns a pre-built ``FakeJiraClient``.
---

# StaticResolver

Defined in [`parrot.eval.sandbox.fakes`](../summaries/mod:parrot.eval.sandbox.fakes.md).

```python
class StaticResolver
```

Credential resolver that always returns a pre-built ``FakeJiraClient``.

Satisfies the ``credential_resolver.resolve(channel, user_id)`` contract
used by ``JiraToolkit._pre_execute`` when ``auth_type == "oauth2_3lo"``,
but without any network call.

Args:
    fake_client: The ``FakeJiraClient`` to always return.
    access_token: Fake access token string (used to fill ``token_hash``).

## Methods

- `async def resolve(self, channel: str, user_id: str) -> Any` — Return a fake token set with the pre-built client embedded.
- `async def get_auth_url(self, channel: str, user_id: str) -> str` — Return a placeholder auth URL (never called in eval context).
