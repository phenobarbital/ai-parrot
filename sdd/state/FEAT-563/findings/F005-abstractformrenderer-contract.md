---
id: F005
query_id: Q005
type: read
intent: Renderer base contract
executed_at: 2026-09-10T00:39:55Z
duration_ms: null
parent_id: null
depth: 0
---

# F005 — AbstractFormRenderer contract

## Summary

`AbstractFormRenderer.render(form, style=None, *, locale, prefilled, errors) -> RenderedForm` is the single abstract method; `FieldRenderer` Protocol is a per-(FieldType, target) async renderer; `FallbackRenderer` is the degraded emitter and renderers own appending `RenderedForm.warnings`.

## Citations

- path: `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/base.py`
  lines: 57-89
  symbol: `AbstractFormRenderer`
  excerpt: |
    async def render(self, form: FormSchema, style: StyleSchema | None = None, *,
        locale: str = "en", prefilled: dict[str, Any] | None = None,
        errors: dict[str, str] | None = None) -> RenderedForm:
- path: `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/base.py`
  lines: 14-31
  symbol: `FieldRenderer`
- path: `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/base.py`
  lines: 34-54
  symbol: `FallbackRenderer`
