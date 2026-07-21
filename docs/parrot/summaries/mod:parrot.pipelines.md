---
type: Wiki Summary
title: parrot.pipelines
id: mod:parrot.pipelines
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: AI-Parrot pipelines proxy.
relates_to:
- concept: mod:parrot.plugins
  rel: references
- concept: mod:parrot_pipelines
  rel: references
---

# `parrot.pipelines`

AI-Parrot pipelines proxy.

Resolution chain for pipeline imports:
1. ai-parrot-pipelines installed package (parrot_pipelines)
2. plugins.pipelines user/deploy-time plugin directory
3. PIPELINE_REGISTRY declarative lookup from ai-parrot-pipelines
4. Legacy dynamic_import_helper fallback

Submodule redirector:
  ``from parrot.pipelines.handlers import X`` is transparently redirected
  to ``from parrot_pipelines.handlers import X`` when no local submodule
  exists.  This is done via a sys.meta_path finder installed at import time.
