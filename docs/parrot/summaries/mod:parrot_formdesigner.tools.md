---
type: Wiki Summary
title: parrot_formdesigner.tools
id: mod:parrot_formdesigner.tools
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Form tools for the forms abstraction layer.
relates_to:
- concept: mod:parrot_formdesigner
  rel: references
---

# `parrot_formdesigner.tools`

Form tools for the forms abstraction layer.

These tools allow LLMs to interact with the form system:
- RequestFormTool: request a form to collect parameters for another tool
- CreateFormTool: create and register a custom form at runtime (TASK-531)
- DatabaseFormTool: generate a form schema from a database table definition (TASK-544)
- field_helpers: helper functions for supported field types and snippets
