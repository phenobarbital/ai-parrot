---
type: Wiki Summary
title: parrot.knowledge.ontology.schema_overlay.service
id: mod:parrot.knowledge.ontology.schema_overlay.service
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Schema Overlay Service (FEAT-159 TASK-1095).
relates_to:
- concept: class:parrot.knowledge.ontology.schema_overlay.service.SchemaOverlayService
  rel: defines
- concept: mod:parrot.knowledge.ontology.exceptions
  rel: references
- concept: mod:parrot.knowledge.ontology.merger
  rel: references
- concept: mod:parrot.knowledge.ontology.schema_overlay.models
  rel: references
- concept: mod:parrot.knowledge.ontology.schema_overlay.validator
  rel: references
- concept: mod:parrot.knowledge.ontology.tenant
  rel: references
---

# `parrot.knowledge.ontology.schema_overlay.service`

Schema Overlay Service (FEAT-159 TASK-1095).

Sole SQL writer for ``ontology_schema_overlay``, ``ontology_schema_audit``, and
``ontology_schema_outbox``.  Implements the five-state machine with a mandatory
dry-run gate on every ``approve`` call.

State machine
--------------
::

    proposed ──[submit]──→ pending_review ──[approve]──→ approved ──[deprecate]──→ deprecated
         ↑                      ↓ [reject]                                 ↑
         └──────────────────── rejected ←──────────────────────────────────┘
                                 │ [restore]
                                 └──────────────────→ proposed

Mandatory dry-run gate
-----------------------
``approve`` always calls ``dry_run_overlay()`` before updating state.
If the dry-run fails, state stays at ``pending_review``, the
``dry_run_report`` column is updated, and ``DryRunFailedError`` is raised.

## Classes

- **`SchemaOverlayService`** — Operational truth for per-tenant schema overlays.
