---
type: Wiki Summary
title: parrot.outputs.a2ui.producer
id: mod:parrot.outputs.a2ui.producer
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: LLM envelope producer with a catalog-validate-retry loop (Module 9, D1b).
relates_to:
- concept: class:parrot.outputs.a2ui.producer.ProducerResult
  rel: defines
- concept: func:parrot.outputs.a2ui.producer.generate_envelope
  rel: defines
- concept: mod:parrot.clients.base
  rel: references
- concept: mod:parrot.models.outputs
  rel: references
- concept: mod:parrot.outputs.a2ui.catalog
  rel: references
- concept: mod:parrot.outputs.a2ui.models
  rel: references
- concept: mod:parrot.outputs.a2ui.serialization
  rel: references
---

# `parrot.outputs.a2ui.producer`

LLM envelope producer with a catalog-validate-retry loop (Module 9, D1b).

The LLM produces A2UI envelopes only for freeform DISPLAY UI. This module wraps the
existing ``client.ask(..., structured_output=StructuredOutputConfig(output_type=CreateSurface))``
machinery — which silently degrades to raw text on a Pydantic ``ValidationError`` — with
a bounded catalog-validate-retry loop: validate against the catalog allowlist (LLM
origin, so ``requires_actions`` components are rejected — D10b), re-prompt with the
validation-error context on failure, and after the budget is exhausted **degrade to plain
text — never raw passthrough** (G1 survives the failure path).

Retry budget: SPK-3 (TASK-1727) recommended **3 attempts** (1 initial + 2 retries),
grounded in the ``OutputFormatter`` ``max_retries=2`` precedent; live validity numbers
were not obtainable in the spike environment, so this is the documented default.

One-way import rule (G8): no module-level import of LLM clients/agents/DatasetManager —
the ``client`` arrives as a call argument (typed loosely / via ``TYPE_CHECKING``).

## Classes

- **`ProducerResult(BaseModel)`** — Outcome of :func:`generate_envelope`.

## Functions

- `async def generate_envelope(client: 'AbstractClient', prompt: str, *, catalog: Any=None, max_attempts: int=DEFAULT_MAX_ATTEMPTS, model: str='', system_prompt: Optional[str]=None) -> ProducerResult` — Produce a catalog-valid display ``CreateSurface`` via a bounded retry loop.
