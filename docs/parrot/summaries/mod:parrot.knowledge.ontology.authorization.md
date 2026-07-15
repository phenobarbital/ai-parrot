---
type: Wiki Summary
title: parrot.knowledge.ontology.authorization
id: mod:parrot.knowledge.ontology.authorization
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Intent-level authorization checker for the ontology pipeline (FEAT-158).
relates_to:
- concept: class:parrot.knowledge.ontology.authorization.AuthorizationChecker
  rel: defines
- concept: mod:parrot.knowledge.ontology.graph_store
  rel: references
- concept: mod:parrot.knowledge.ontology.schema
  rel: references
---

# `parrot.knowledge.ontology.authorization`

Intent-level authorization checker for the ontology pipeline (FEAT-158).

``AuthorizationChecker`` evaluates ``AuthorizationSpec`` rules **after** entity
resolution and **before** graph traversal. Rules are OR-combined: the first
matching rule grants access. When no rule matches and ``spec.default_deny=True``
(the default), access is denied with a human-readable reason.

**Default-deny is explicit and load-bearing.** Every ``AuthorizationSpec``
without a matching rule will deny unless explicitly overridden with
``default_deny=False``. This is documented here because pattern authors must
be aware: an empty ``rules: []`` spec with ``default_deny=True`` (the default)
will ALWAYS deny. That is the intended behavior for the paranoid default.

Supported rules (five declarative types):
- ``always``: unconditionally allow.
- ``target_is_self``: allow if the requesting user equals any resolved entity.
- ``target_in_management_chain``: AQL traversal (depth ≤ 10) along
  ``reports_to`` edges from the requesting user. Allow if any resolved entity
  is found within depth 10.
- ``has_role``: allow if ``rule.role`` is in ``user_context["roles"]``.
- ``same_department``: allow if the requesting user's department equals the
  resolved entity's department (fetched via a graph lookup).

Usage::

    checker = AuthorizationChecker(graph_store=graph_store)
    allowed, reason = await checker.check(
        spec=pattern.authorization,
        user_context={"user_id": "Emp/42", "roles": ["hr_manager"]},
        resolved_entities={"target_employee": "Emp/55"},
        tenant_id="acme",
    )

## Classes

- **`AuthorizationChecker`** — Evaluates declarative authorization rules against resolved entities.
