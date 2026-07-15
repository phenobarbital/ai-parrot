---
type: Wiki Summary
title: parrot.loaders
id: mod:parrot.loaders
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Document Loaders — load data from different sources for RAG.
relates_to:
- concept: mod:parrot
  rel: references
- concept: mod:parrot.plugins
  rel: references
- concept: mod:parrot_loaders
  rel: references
---

# `parrot.loaders`

Document Loaders — load data from different sources for RAG.

Resolution chain for loader imports:
1. Core classes (always available — defined directly in this module)
2. parrot_loaders (ai-parrot-loaders installed package)
3. plugins.loaders (user/deploy-time plugin directory)
4. LOADER_REGISTRY (declarative registry from ai-parrot-loaders)
5. Legacy dynamic_import_helper (backward-compat submodule resolution)

Submodule redirector:
  ``from parrot.loaders.audio import X`` is transparently redirected
  to ``from parrot_loaders.audio import X`` when no local submodule
  exists.  This is done via a sys.meta_path finder installed at import time.
