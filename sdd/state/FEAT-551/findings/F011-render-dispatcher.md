---
id: F011
query_id: Q010
type: read
intent: Render dispatcher registry
executed_at: 2026-09-10T22:27:13Z
duration_ms: 0
parent_id: null
depth: 0
---

# F011 — api/render.py — format registry; 'adaptive' already served

## Summary
`GET .../render/{format}` dispatches through a module-level `_RENDERERS` registry seeded with `html`, `adaptive` (→ `AdaptiveCardRenderer()`), `xml`, `pdf`, `audio`; `register_renderer(format_key, renderer)` adds more. `handle_render` loads the form, enforces tenant membership unless public, and calls `renderer.render(form, locale=...)` — it forwards ONLY `locale`; no style, prefilled, request origin or query params reach the renderer. Response content-type comes from `RenderedForm.content_type`. So a Teams card is already downloadable at `/render/adaptive` — but without a submit target.

## Citations
- path: `packages/parrot-formdesigner/src/parrot_formdesigner/api/render.py`
  lines: 35-60
  symbol: `_RENDERERS`, `_seed_default_renderers`
  excerpt: |
    _RENDERERS.setdefault("html", HTML5Renderer())
    _RENDERERS.setdefault("adaptive", AdaptiveCardRenderer())
    _RENDERERS.setdefault("xml", XFormsRenderer()) ... ("pdf", PdfRenderer()) ... ("audio", AudioFormRenderer())
- path: `packages/parrot-formdesigner/src/parrot_formdesigner/api/render.py`
  lines: 63-83
  symbol: `register_renderer`, `get_renderer`, `supported_formats`
- path: `packages/parrot-formdesigner/src/parrot_formdesigner/api/render.py`
  lines: 101-151
  symbol: `handle_render`
  excerpt: |
    renderer = get_renderer(format_key)  # 415 + {"supported": [...]} on miss
    form = await registry.get(form_uid, tenant=tenant); enforce_membership_unless_public(request, form, tenant)
    locale = request.query.get("locale", "en")
    rendered = await renderer.render(form, locale=locale)
    return web.Response(text=body, content_type=rendered.content_type)
