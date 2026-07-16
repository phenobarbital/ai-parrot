---
type: Wiki Entity
title: AuthorizationChecker
id: class:parrot.knowledge.ontology.authorization.AuthorizationChecker
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Evaluates declarative authorization rules against resolved entities.
---

# AuthorizationChecker

Defined in [`parrot.knowledge.ontology.authorization`](../summaries/mod:parrot.knowledge.ontology.authorization.md).

```python
class AuthorizationChecker
```

Evaluates declarative authorization rules against resolved entities.

Args:
    graph_store: ArangoDB wrapper used for management-chain and
        same-department AQL traversals.
    reports_to_collection: ArangoDB edge collection name for the
        ``reports_to`` relation. Defaults to ``"reports_to"``.

## Methods

- `async def check(self, spec: AuthorizationSpec, user_context: dict[str, Any], resolved_entities: dict[str, str], tenant_id: str) -> tuple[bool, str | None]` — Evaluate ``spec.rules`` in order, returning on first match.
