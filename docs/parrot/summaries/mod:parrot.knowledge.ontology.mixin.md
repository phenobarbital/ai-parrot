---
type: Wiki Summary
title: parrot.knowledge.ontology.mixin
id: mod:parrot.knowledge.ontology.mixin
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: OntologyRAGMixin — agent mixin for ontological graph RAG.
relates_to:
- concept: class:parrot.knowledge.ontology.mixin.OntologyRAGMixin
  rel: defines
- concept: mod:parrot.auth.exceptions
  rel: references
- concept: mod:parrot.conf
  rel: references
- concept: mod:parrot.knowledge.ontology.authorization
  rel: references
- concept: mod:parrot.knowledge.ontology.cache
  rel: references
- concept: mod:parrot.knowledge.ontology.entity_resolver
  rel: references
- concept: mod:parrot.knowledge.ontology.graph_store
  rel: references
- concept: mod:parrot.knowledge.ontology.intent
  rel: references
- concept: mod:parrot.knowledge.ontology.schema
  rel: references
- concept: mod:parrot.knowledge.ontology.tenant
  rel: references
- concept: mod:parrot.knowledge.ontology.tool_dispatcher
  rel: references
---

# `parrot.knowledge.ontology.mixin`

OntologyRAGMixin — agent mixin for ontological graph RAG.

Agents opt-in to ontology-enriched RAG by inheriting this mixin.
The mixin hooks into the agent's ask() flow, intercepting queries
before standard RAG processing to enrich context with structural
graph data.

Usage::

    class MyAgent(OntologyRAGMixin, BasicAgent):
        pass

Return Type
-----------
``ontology_process`` now returns a ``ContextEnvelope`` wrapping an optional
``EnrichedContext``. Callers must read ``result.context`` instead of accessing
``EnrichedContext`` fields directly.  The full state set is:

- ``"ok"``               — happy path; ``result.context`` is populated.
- ``"ambiguous"``        — entity resolver found multiple candidates;
                           ``result.clarification`` carries ``rule``, ``mention``,
                           and ``candidates`` for the chat layer to ask the user.
- ``"entity_not_found"`` — resolver found no match for a required rule.
- ``"denied"``           — ``AuthorizationChecker`` denied the request;
                           ``result.denial_reason`` describes why.
- ``"auth_required"``    — ``ToolCallDispatcher`` raised
                           ``AuthorizationRequired``; ``result.auth_prompt``
                           contains ``auth_url``, ``provider``, and ``scopes``.
- ``"render_error"``     — Jinja2 template rendering failed; ``result.error``
                           has the diagnostic message.
- ``"vector_only"``      — returned as an ``ok``-ish fallback when graph
                           processing is skipped (no pattern match, graph
                           unavailable, etc.).
- ``"disabled"``         — ontology RAG is globally disabled.
- ``"not_configured"``   — ``tenant_manager`` was not provided to the mixin.

AQL Bind-Key Convention
-----------------------
When entity extraction resolves a rule named ``target_employee``, the
resolved ``_id`` is injected into ``intent.params`` under the key
``target_employee_id`` (rule name + ``"_id"`` suffix).  Pattern authors must
declare their AQL ``@target_employee_id`` bind parameter accordingly.

4-Level Degradation Chain (FEAT-159)
-------------------------------------
For the ``authoritative_doc_for_topic`` pattern the traversal section runs a
4-level degradation chain.  For all other patterns only levels 3-4 (vector
fallback) are added on top of the existing single-traversal logic.

``context.source`` values produced by the chain:

- ``"graph:primary"``   — primary-authority graph traversal succeeded.
- ``"graph:secondary"`` — secondary-authority graph traversal succeeded.
- ``"vector:filtered"`` — similarity_search with doc_type filter succeeded.
- ``"vector:plain"``    — unfiltered similarity_search succeeded.
- ``"ontology"``        — normal (non-authority) graph traversal succeeded.
- ``"vector_only"``     — all graph paths were empty/unavailable; falls back
                          to vector store without graph context.

## Classes

- **`OntologyRAGMixin`** — Mixin that adds Ontological Graph RAG capabilities to any agent.
