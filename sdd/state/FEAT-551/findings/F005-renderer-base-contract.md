---
id: F005
query_id: Q005
type: read
intent: Renderer base contract
executed_at: 2026-09-10T22:27:13Z
duration_ms: 0
parent_id: null
depth: 0
---

# F005 — AbstractFormRenderer contract is fixed-signature

## Summary
`AbstractFormRenderer.render(form, style=None, *, locale, prefilled, errors) -> RenderedForm` is the abstract contract; there is no parameter for a submit target / base URL / channel context. Any per-render target info must come via constructor config, a subclass, or `RenderedForm.metadata`. `FieldRenderer` Protocol and `FallbackRenderer` exist for per-type dispatch.

## Citations
- path: `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/base.py`
  lines: 57-89
  symbol: `AbstractFormRenderer.render`
  excerpt: |
    async def render(self, form: FormSchema, style: StyleSchema | None = None, *,
        locale: str = "en", prefilled: dict[str, Any] | None = None,
        errors: dict[str, str] | None = None) -> RenderedForm
- path: `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/base.py`
  lines: 15-31
  symbol: `FieldRenderer` (Protocol)
- path: `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/base.py`
  lines: 34-54
  symbol: `FallbackRenderer`
- path: `packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py`
  lines: 671-688
  symbol: `RenderedForm`
  excerpt: |
    content: Any; content_type: str; style_output: Any | None = None
    metadata: dict[str, Any] | None = None; warnings: list[RenderWarning] = []
