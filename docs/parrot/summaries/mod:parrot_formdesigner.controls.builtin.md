---
type: Wiki Summary
title: parrot_formdesigner.controls.builtin
id: mod:parrot_formdesigner.controls.builtin
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Built-in form-control seed.
relates_to:
- concept: mod:parrot_formdesigner.controls.registry
  rel: references
- concept: mod:parrot_formdesigner.core.types
  rel: references
- concept: mod:parrot_formdesigner.tools.field_helpers
  rel: references
---

# `parrot_formdesigner.controls.builtin`

Built-in form-control seed.

Importing this module registers one ``FieldControlMetadata`` entry per
``FieldType`` enum value with the form-control registry. Snippet seeds are
sourced from ``tools.field_helpers.get_form_field_schema_snippets()``;
per-type categorization (``category``, ``icon``, ``render_hint``,
``is_container``, ``supports_constraints``) is encoded as a constant in
this module.

This module is meant to be imported once for its side effect — typically by
``parrot_formdesigner.api.__init__`` so the registry is seeded before any
request hits ``GET /api/v1/form-controls``.
