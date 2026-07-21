---
type: Wiki Summary
title: parrot.knowledge.ontology.schema_overlay.validator
id: mod:parrot.knowledge.ontology.schema_overlay.validator
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Schema Overlay dry-run validator (FEAT-159 TASK-1094).
relates_to:
- concept: func:parrot.knowledge.ontology.schema_overlay.validator.dry_run_overlay
  rel: defines
- concept: mod:parrot.conf
  rel: references
- concept: mod:parrot.knowledge.ontology.exceptions
  rel: references
- concept: mod:parrot.knowledge.ontology.merger
  rel: references
- concept: mod:parrot.knowledge.ontology.parser
  rel: references
- concept: mod:parrot.knowledge.ontology.schema
  rel: references
- concept: mod:parrot.knowledge.ontology.schema_overlay.models
  rel: references
- concept: mod:parrot.knowledge.ontology.tenant
  rel: references
- concept: mod:parrot.knowledge.ontology.validators
  rel: references
---

# `parrot.knowledge.ontology.schema_overlay.validator`

Schema Overlay dry-run validator (FEAT-159 TASK-1094).

Performs sandboxed validation of a schema overlay candidate before it can
transition from ``pending_review`` to ``approved``.  The dry-run is the
mandatory approval gate.

Validation pipeline (v1)
-------------------------
1. Parse ``overlay.definition`` into the appropriate schema model.
2. Build an ``OntologyDefinition`` from the candidate.
3. Call ``merger.merge_with_overlay()`` on a private call — does NOT mutate
   the tenant's ``TenantOntologyManager`` cache.
4. For ``traversal_pattern`` overlays: run ``validate_aql()`` on the
   ``query_template``.
5. Catch ``FrameworkOverrideError`` if the overlay attempts to mutate a
   framework item.
6. Return a ``DryRunReport`` with per-check results and wall-clock timing.

A ``ONTOLOGY_DRY_RUN_TIMEOUT_S`` timeout (default 10 s) is enforced via
``asyncio.wait_for``.

## Functions

- `async def dry_run_overlay(tenant_id: str, overlay: SchemaOverlayRow, tenant_manager: TenantOntologyManager, merger: OntologyMerger) -> DryRunReport` — Sandboxed validation of a schema overlay candidate.
