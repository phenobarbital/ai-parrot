---
id: F006
query_id: Q005
type: read
intent: Find the Form model and any is_public/visibility property
executed_at: 2026-06-16T00:00:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F006 — `FormSchema` has no `is_public` field (must be added)

## Summary

`FormSchema` (pydantic) is the canonical form model. It already carries
publishing-adjacent fields from FEAT-300 (`form_type`, `published_version`,
`product_bindings`) but has **no `is_public` / visibility / anonymous-access
field** (grep for `is_public` across the whole package → zero matches). So the
property the source asks for does not exist yet and must be introduced here.

## Citations

- path: `packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py`
  lines: 300-315
  symbol: `FormSchema`
  excerpt: |
    form_id: str
    version: str = "1.0"
    ...
    # FEAT-300 — Form Builder Parity
    form_type: FormType = FormType.SIMPLE
    product_bindings: list[str] | None = None
    published_version: str | None = None

## Notes

`grep -rniE 'is_public' packages/parrot-formdesigner` → no matches. Adding
`is_public: bool = False` here is the natural home; it is platform-agnostic and
flows through the existing register/persist path (F007).
