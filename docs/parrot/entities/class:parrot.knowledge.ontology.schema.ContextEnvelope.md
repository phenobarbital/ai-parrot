---
type: Wiki Entity
title: ContextEnvelope
id: class:parrot.knowledge.ontology.schema.ContextEnvelope
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Wraps EnrichedContext with state-specific fields for non-happy paths.
---

# ContextEnvelope

Defined in [`parrot.knowledge.ontology.schema`](../summaries/mod:parrot.knowledge.ontology.schema.md).

```python
class ContextEnvelope(BaseModel)
```

Wraps EnrichedContext with state-specific fields for non-happy paths.

Introduced by FEAT-158 to widen the return type of
``OntologyRAGMixin.ontology_process`` so all code paths — happy, ambiguous,
denied, auth-required, render-error, tool-failed — share a single return
type.

Callers previously reading ``result.graph_context`` directly must migrate
to ``result.context.graph_context`` (``context`` is ``None`` for non-``ok``
states).

States:
- ``ok``: Pipeline completed successfully; ``context`` is populated.
- ``ambiguous``: EntityResolver found multiple candidates for a required
  rule; ``clarification`` carries ``rule``, ``mention``, and
  ``candidates``.
- ``entity_not_found``: EntityResolver found no candidates for a required
  rule; ``error`` carries the rule name.
- ``denied``: AuthorizationChecker denied access; ``denial_reason`` is set.
- ``auth_required``: Tool raised ``AuthorizationRequired``; ``auth_prompt``
  carries ``auth_url``, ``provider``, and ``scopes``.
- ``render_error``: Jinja2 template rendering failed (``StrictUndefined``);
  ``error`` carries the template field name and message.
- ``tool_failed``: Tool invocation raised an unexpected exception;
  ``error`` carries the message.

Args:
    state: Current pipeline state.
    context: Populated ``EnrichedContext`` on ``state="ok"``; ``None``
        otherwise.
    clarification: On ``state="ambiguous"``: mapping with keys
        ``rule``, ``mention``, ``candidates``.
    denial_reason: On ``state="denied"``: human-readable denial reason.
    auth_prompt: On ``state="auth_required"``: mapping with keys
        ``auth_url``, ``provider``, ``scopes``.
    tool_result: On ``state="ok"`` with a tool_call post-action: the
        result dict keyed by ``ToolCallSpec.result_binding``.
    error: On error states: description of what went wrong.
