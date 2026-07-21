---
type: Wiki Summary
title: parrot_formdesigner.tools.services.registry
id: mod:parrot_formdesigner.tools.services.registry
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Form-service registry — name → AbstractFormService subclass.
relates_to:
- concept: func:parrot_formdesigner.tools.services.registry.get_form_service
  rel: defines
- concept: func:parrot_formdesigner.tools.services.registry.list_form_services
  rel: defines
- concept: func:parrot_formdesigner.tools.services.registry.register_form_service
  rel: defines
- concept: mod:parrot_formdesigner.tools.services.abstract
  rel: references
---

# `parrot_formdesigner.tools.services.registry`

Form-service registry — name → AbstractFormService subclass.

Mirrors parrot_formdesigner/controls/registry.py:67-113. Module-level dict
preserves registration order for stable iteration.

## Functions

- `def register_form_service(name: str, service_cls: type[AbstractFormService]) -> None` — Register (or overwrite) a form-service class under ``name``.
- `def get_form_service(name: str) -> type[AbstractFormService]` — Resolve a registered form-service class by name.
- `def list_form_services() -> list[str]` — Return registered service names in registration order.
