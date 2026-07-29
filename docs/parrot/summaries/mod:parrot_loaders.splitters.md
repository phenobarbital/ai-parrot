---
type: Wiki Summary
title: parrot_loaders.splitters
id: mod:parrot_loaders.splitters
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Backward-compatibility shim.
relates_to:
- concept: mod:parrot.loaders.splitters
  rel: references
- concept: mod:parrot.loaders.splitters.base
  rel: references
- concept: mod:parrot.loaders.splitters.md
  rel: references
- concept: mod:parrot.loaders.splitters.semantic
  rel: references
- concept: mod:parrot.loaders.splitters.token
  rel: references
---

# `parrot_loaders.splitters`

Backward-compatibility shim.

The text splitters now live in ai-parrot **core**
(:mod:`parrot.loaders.splitters`) to break the circular dependency:
``ai-parrot-loaders`` depends on ``ai-parrot``, so core must not import
from ``parrot_loaders``. This module re-exports the core implementations
so existing imports keep working:

    from parrot_loaders.splitters import TokenTextSplitter        # ok
    from parrot_loaders.splitters.base import BaseTextSplitter    # ok
