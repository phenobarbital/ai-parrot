---
type: Wiki Summary
title: parrot.stores.kb.local
id: mod:parrot.stores.kb.local
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: 'LocalKB: Knowledge Base from local text and markdown files with FAISS vector
  store.'
relates_to:
- concept: class:parrot.stores.kb.local.LocalKB
  rel: defines
- concept: mod:parrot.stores.faiss_store
  rel: references
- concept: mod:parrot.stores.kb.abstract
  rel: references
- concept: mod:parrot.stores.models
  rel: references
- concept: mod:parrot.utils.helpers
  rel: references
---

# `parrot.stores.kb.local`

LocalKB: Knowledge Base from local text and markdown files with FAISS vector store.

## Classes

- **`LocalKB(AbstractKnowledgeBase)`** — Local Knowledge Base that loads markdown and text documents from a local directory.
