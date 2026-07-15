---
type: Wiki Summary
title: parrot_formdesigner.tools.services
id: mod:parrot_formdesigner.tools.services
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Form-source services for DatabaseFormTool.
relates_to:
- concept: mod:parrot_formdesigner.tools
  rel: references
---

# `parrot_formdesigner.tools.services`

Form-source services for DatabaseFormTool.

This is **parrot_formdesigner.tools.services** (nested under tools/), NOT the
package-level parrot_formdesigner.services/ (which holds FormRegistry,
storage, cache, etc.). The two paths are distinct Python packages; they only
share the name. New form-source strategies live HERE.

Built-in services register at import time. Custom services can register via:

    from parrot_formdesigner.tools.services import register_form_service
    register_form_service("my_service", MyFormService)

before any DatabaseFormTool invocation that targets that service name.
