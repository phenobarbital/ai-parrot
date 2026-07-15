---
type: Wiki Summary
title: parrot.forms
id: mod:parrot.forms
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Universal Form Abstraction Layer for AI-Parrot.
relates_to:
- concept: mod:parrot
  rel: references
- concept: mod:parrot.registry
  rel: references
- concept: mod:parrot.storage
  rel: references
- concept: mod:parrot.tools
  rel: references
- concept: mod:parrot_formdesigner.core
  rel: references
- concept: mod:parrot_formdesigner.extractors
  rel: references
- concept: mod:parrot_formdesigner.renderers
  rel: references
- concept: mod:parrot_formdesigner.services
  rel: references
- concept: mod:parrot_formdesigner.tools
  rel: references
---

# `parrot.forms`

Universal Form Abstraction Layer for AI-Parrot.

This module is a backward-compatible re-export shim. All form functionality
has been moved to the `parrot-formdesigner` package (parrot_formdesigner.*).

Existing imports from parrot.forms continue to work unchanged.

Updated for FEAT-152: ``parrot_formdesigner`` no longer re-exports symbols
at the top level. We now import from the explicit submodules.
