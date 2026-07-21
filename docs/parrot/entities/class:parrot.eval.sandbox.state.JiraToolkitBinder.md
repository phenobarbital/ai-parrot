---
type: Wiki Entity
title: JiraToolkitBinder
id: class:parrot.eval.sandbox.state.JiraToolkitBinder
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Binder for ``JiraToolkit``.
relates_to:
- concept: class:parrot.eval.sandbox.state.ToolkitBinder
  rel: extends
---

# JiraToolkitBinder

Defined in [`parrot.eval.sandbox.state`](../summaries/mod:parrot.eval.sandbox.state.md).

```python
class JiraToolkitBinder(ToolkitBinder)
```

Binder for ``JiraToolkit``.

Pre-seeds ``toolkit.jira = FakeJiraClient(backend)`` so all tool calls
that access ``self.jira`` go to the in-memory backend.  No network calls
and no ``credential_resolver`` resolution occur.

For non-oauth2_3lo auth modes (e.g. ``basic_auth``, ``token_auth``),
``JiraToolkit._pre_execute`` is a no-op and ``self.jira`` is used
directly by every tool method — patching ``toolkit.jira`` is sufficient.

For ``oauth2_3lo`` mode the binder additionally pre-seeds
``toolkit._client_cache`` with the ``FakeJiraClient`` so the cache
hit path in ``_pre_execute`` returns the fake without network I/O.

## Methods

- `def bind(self, toolkit: Any, backend: 'DictStateBackend') -> None` — Inject *backend* into *toolkit*.
