---
type: Wiki Summary
title: parrot.registry.routing.ontology_signal
id: mod:parrot.registry.routing.ontology_signal
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Ontology Pre-Annotator adapter (FEAT-111 Module 5).
relates_to:
- concept: class:parrot.registry.routing.ontology_signal.OntologyPreAnnotator
  rel: defines
---

# `parrot.registry.routing.ontology_signal`

Ontology Pre-Annotator adapter (FEAT-111 Module 5).

Wraps ``OntologyIntentResolver`` — which is soft-deprecated for strategy
routing — into a thin adapter that:

* Suppresses ``DeprecationWarning`` surgically (only during resolver calls).
* Returns a plain ``dict`` with keys like ``action``, ``pattern`` etc.
* No-ops cleanly when no resolver is configured.
* Swallows all resolver exceptions (logs WARNING + returns ``{}``).
* Works with both sync and async resolver methods (duck-typed).

Usage::

    from parrot.registry.routing import OntologyPreAnnotator

    adapter = OntologyPreAnnotator(resolver)          # or None
    annotations = await adapter.annotate("my query")  # → {"action": "graph_query", ...}

## Classes

- **`OntologyPreAnnotator`** — Adapter that exposes ``OntologyIntentResolver`` as a simple annotator.
