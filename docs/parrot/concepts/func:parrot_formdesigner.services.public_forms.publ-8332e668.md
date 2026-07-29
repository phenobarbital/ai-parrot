---
type: Concept
title: public_form_paths()
id: func:parrot_formdesigner.services.public_forms.public_form_paths
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Return the auth-exempt glob patterns for a public form.
---

# public_form_paths

```python
def public_form_paths(form_id: str, base_path: str='/api/v1') -> list[str]
```

Return the auth-exempt glob patterns for a public form.

These five patterns cover all read and submission URLs that should be
reachable without authentication when a form has ``is_public=True``.

Used by both the lifecycle toggle and the exclude-provider registration
so that both callers always register/unregister the same set of paths.

Args:
    form_id: The form's unique identifier.
    base_path: URL prefix used when the form API was mounted (must match
               the ``base_path`` passed to ``setup_form_api``).
               Trailing slashes are stripped automatically.

Returns:
    List of five URL patterns (fnmatch globs):

      - ``{base_path}/forms/{form_id}``            — GET form object
      - ``{base_path}/forms/{form_id}/schema``     — GET JSON schema
      - ``{base_path}/forms/{form_id}/render/*``   — GET rendered formats (glob)
      - ``{base_path}/forms/{form_id}/data``       — POST submit results
      - ``{base_path}/forms/{form_id}/validate``   — POST pre-submit validation
