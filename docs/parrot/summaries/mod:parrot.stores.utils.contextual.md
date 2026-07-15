---
type: Wiki Summary
title: parrot.stores.utils.contextual
id: mod:parrot.stores.utils.contextual
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Contextual embedding header helper.
relates_to:
- concept: func:parrot.stores.utils.contextual.build_contextual_text
  rel: defines
- concept: mod:parrot.stores.models
  rel: references
---

# `parrot.stores.utils.contextual`

Contextual embedding header helper.

Builds a deterministic, LLM-free contextual header from a Document's
``metadata['document_meta']`` sub-dict and prepends it to the chunk text
*for embedding only*.  No I/O, no ML dependencies — stdlib + Pydantic.

Spec: FEAT-127 — Metadata-Driven Contextual Embedding Headers.

## Functions

- `def build_contextual_text(document: Document, template: ContextualTemplate=DEFAULT_TEMPLATE, max_header_tokens: int=DEFAULT_MAX_HEADER_TOKENS) -> tuple[str, str]` — Build the text that will be embedded plus the header used.
