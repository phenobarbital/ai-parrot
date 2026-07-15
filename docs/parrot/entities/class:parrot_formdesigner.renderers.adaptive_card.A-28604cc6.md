---
type: Wiki Entity
title: AdaptiveCardRenderer
id: class:parrot_formdesigner.renderers.adaptive_card.AdaptiveCardRenderer
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Renders FormSchema as Adaptive Card JSON for MS Teams.
---

# AdaptiveCardRenderer

Defined in [`parrot_formdesigner.renderers.adaptive_card`](../summaries/mod:parrot_formdesigner.renderers.adaptive_card.md).

```python
class AdaptiveCardRenderer(AbstractFormRenderer)
```

Renders FormSchema as Adaptive Card JSON for MS Teams.

Produces Adaptive Card v1.5 JSON that is compatible with the
Bot Framework and MS Teams card rendering pipeline.

Supports:
- Complete form rendering (all sections in one card)
- Section-by-section wizard rendering
- Summary/confirmation card
- Error card
- Prefilled values
- Validation error display
- i18n label resolution

Example:
    renderer = AdaptiveCardRenderer()
    result = await renderer.render(form_schema)
    card_json = result.content  # dict ready for Teams

## Methods

- `async def render(self, form: FormSchema, style: StyleSchema | None=None, *, locale: str='en', prefilled: dict[str, Any] | None=None, errors: dict[str, str] | None=None) -> RenderedForm` — Render a complete FormSchema as an Adaptive Card.
- `async def render_section(self, form: FormSchema, section_index: int, style: StyleSchema | None=None, *, locale: str='en', prefilled: dict[str, Any] | None=None, errors: dict[str, str] | None=None, show_back: bool=False, show_skip: bool=False) -> RenderedForm` — Render a single section as a wizard step Adaptive Card.
- `async def render_summary(self, form: FormSchema, form_data: dict[str, Any], *, locale: str='en', summary_text: str | None=None) -> RenderedForm` — Render a summary/confirmation card with submitted data.
- `async def render_error(self, title: str, errors: list[str], *, locale: str='en', retry_action: bool=True) -> RenderedForm` — Render an error card.
