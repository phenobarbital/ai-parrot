---
type: Wiki Summary
title: parrot.forms.tools
id: mod:parrot.forms.tools
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Form tools for the forms abstraction layer.
relates_to:
- concept: mod:parrot.forms
  rel: references
---

# `parrot.forms.tools`

Form tools for the forms abstraction layer.

These tools allow LLMs to interact with the form system:
- RequestFormTool: request a form to collect parameters for another tool
- CreateFormTool: create and register a custom form at runtime (TASK-531)
- DatabaseFormTool: generate a form schema from a database table definition (TASK-544)
