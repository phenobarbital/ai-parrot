---
type: Wiki Entity
title: NLSpatialSynthesizer
id: class:parrot.handlers.spatial_filter_handler.NLSpatialSynthesizer
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Thin synthesizer: natural language → SpatialFilterSpec.'
---

# NLSpatialSynthesizer

Defined in [`parrot.handlers.spatial_filter_handler`](../summaries/mod:parrot.handlers.spatial_filter_handler.md).

```python
class NLSpatialSynthesizer
```

Thin synthesizer: natural language → SpatialFilterSpec.

Uses the configured LLM client to extract structured spatial parameters
from a user's natural language query.  The agent does NOT run a reasoning
loop — this is a single structured-output LLM call.

The synthesizer is stateless; construct one per request.

Args:
    client: An ``AbstractClient`` instance to use for the structured
        extraction call.  If None, a fallback heuristic parser is used
        (for testing; not suitable for production NL queries).

## Methods

- `async def synthesize(self, query: str, available_datasets: List[str], default_datasets: Optional[List[str]]=None) -> 'SpatialFilterSpec'` — Synthesize a SpatialFilterSpec from a natural language query.
