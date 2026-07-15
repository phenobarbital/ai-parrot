---
type: Wiki Summary
title: parrot_formdesigner.services.public_forms
id: mod:parrot_formdesigner.services.public_forms
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Helper for computing auth-exempt URL patterns for public forms (FEAT-241).
relates_to:
- concept: func:parrot_formdesigner.services.public_forms.public_form_paths
  rel: defines
---

# `parrot_formdesigner.services.public_forms`

Helper for computing auth-exempt URL patterns for public forms (FEAT-241).

## Functions

- `def public_form_paths(form_id: str, base_path: str='/api/v1') -> list[str]` — Return the auth-exempt glob patterns for a public form.
