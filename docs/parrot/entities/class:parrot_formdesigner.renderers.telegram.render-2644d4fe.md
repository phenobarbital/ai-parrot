---
type: Wiki Entity
title: TelegramRenderer
id: class:parrot_formdesigner.renderers.telegram.renderer.TelegramRenderer
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Renders FormSchema as Telegram interactions.
---

# TelegramRenderer

Defined in [`parrot_formdesigner.renderers.telegram.renderer`](../summaries/mod:parrot_formdesigner.renderers.telegram.renderer.md).

```python
class TelegramRenderer(AbstractFormRenderer)
```

Renders FormSchema as Telegram interactions.

Supports two modes:
- **inline**: Sequential inline keyboard prompts for simple forms.
- **webapp**: A URL to a Telegram WebApp serving the full HTML form.

Auto-selects the mode based on form complexity, with explicit override.

Args:
    base_url: Base URL for WebApp pages (e.g., "https://example.com").
        Falls back to config if None.
    html_renderer: Optional HTML5Renderer for WebApp mode.

## Methods

- `def analyze_form(self, form: FormSchema) -> TelegramRenderMode` — Determine optimal rendering mode for a form.
- `async def render(self, form: FormSchema, style: StyleSchema | None=None, *, locale: str='en', prefilled: dict[str, Any] | None=None, errors: dict[str, str] | None=None, mode: TelegramRenderMode=TelegramRenderMode.AUTO) -> RenderedForm` — Render a FormSchema for Telegram.
