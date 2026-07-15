---
type: Wiki Summary
title: parrot.bots.flows.core.storage.synthesis
id: mod:parrot.bots.flows.core.storage.synthesis
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Flow Primitives — SynthesisMixin + synthesize_results util.
relates_to:
- concept: class:parrot.bots.flows.core.storage.synthesis.SynthesisMixin
  rel: defines
- concept: func:parrot.bots.flows.core.storage.synthesis.synthesize_results
  rel: defines
- concept: mod:parrot.bots.flows.core.context
  rel: references
- concept: mod:parrot.bots.flows.core.result
  rel: references
- concept: mod:parrot.models.crew
  rel: references
---

# `parrot.bots.flows.core.storage.synthesis`

Flow Primitives — SynthesisMixin + synthesize_results util.

Copied from ``parrot.bots.flow.storage.synthesis`` into the shared core
storage location.  Relative imports updated for the new package depth.

Accepts both ``CrewResult`` and ``FlowResult`` via duck-typing: only the
``.agents`` (iterable of info objects) and ``.responses`` (dict) attributes
are used. Full migration to ``FlowResult`` will happen in Spec 2.

FEAT-163 additions:
    ``synthesize_results(ctx, result) -> str`` — top-level async util that
    replaces the ``SynthesisMixin._synthesize_results`` method for new-style
    ``AgentsFlow`` callers. Compatible with both ``on_complete`` hooks and
    in-graph ``SynthesisNode`` DAG nodes.

## Classes

- **`SynthesisMixin`** — Mixin that adds LLM-based result synthesis to crew/flow orchestrators.

## Functions

- `async def synthesize_results(ctx: 'FlowContext', result: 'FlowResult', *, max_tokens: int=8192, temperature: float=0.1, user_id: Optional[str]=None, session_id: Optional[str]=None) -> str` — LLM-summarize all agent responses collected in a ``FlowResult``.
