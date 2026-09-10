---
id: F007
query_id: Q007
type: read
intent: HTTP render dispatcher
executed_at: 2026-09-10T00:39:55Z
duration_ms: null
parent_id: null
depth: 0
---

# F007 — api/render.py — format-keyed renderer registry

## Summary

`GET /api/v1/{tenant}/forms/{form_uid}/render/{format}` dispatches by `format` path param over a module-level `_RENDERERS` dict seeded with html/adaptive/xml/pdf/audio; `register_renderer(format_key, renderer)` adds more; unknown format → 415 `{supported:[...]}`. Handler passes only `locale` to `renderer.render(form)` and serialises `rendered.content` (str/bytes/JSON-able) with `rendered.content_type`. Public/private membership enforced via `enforce_membership_unless_public`.

## Citations

- path: `packages/parrot-formdesigner/src/parrot_formdesigner/api/render.py`
  lines: 38-60
  symbol: `_seed_default_renderers`
  excerpt: |
    _RENDERERS.setdefault("html", HTML5Renderer())
    _RENDERERS.setdefault("adaptive", AdaptiveCardRenderer())
    _RENDERERS.setdefault("xml", XFormsRenderer())
    _RENDERERS.setdefault("pdf", PdfRenderer())
    _RENDERERS.setdefault("audio", AudioFormRenderer())
- path: `packages/parrot-formdesigner/src/parrot_formdesigner/api/render.py`
  lines: 63-83
  symbol: `register_renderer`
- path: `packages/parrot-formdesigner/src/parrot_formdesigner/api/render.py`
  lines: 101-151
  symbol: `handle_render`
  excerpt: |
    locale = request.query.get("locale", "en")
    rendered = await renderer.render(form, locale=locale)
    body = _coerce_body(rendered.content)
