---
type: Wiki Summary
title: parrot_formdesigner.tools.field_helpers
id: mod:parrot_formdesigner.tools.field_helpers
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Helper utilities for supported form field definitions.
relates_to:
- concept: func:parrot_formdesigner.tools.field_helpers.get_dependency_rule_snippets
  rel: defines
- concept: func:parrot_formdesigner.tools.field_helpers.get_form_field_schema_snippets
  rel: defines
- concept: func:parrot_formdesigner.tools.field_helpers.list_supported_form_field_types
  rel: defines
- concept: mod:parrot_formdesigner.core.types
  rel: references
---

# `parrot_formdesigner.tools.field_helpers`

Helper utilities for supported form field definitions.

This module centralizes the accepted ``FieldType`` values and provides
minimal JSON snippets for each field type. These snippets are intended for
form creation/editing flows where agents or UIs need quick reference payloads.

## Functions

- `def list_supported_form_field_types() -> list[str]` — Return supported field type values for FormField.field_type.
- `def get_form_field_schema_snippets() -> dict[str, dict[str, Any]]` — Return example JSON snippets for each supported field type.
- `def get_dependency_rule_snippets() -> dict[str, Any]` — Return skeleton dicts for building ``depends_on`` and ``post_depends`` rules.
