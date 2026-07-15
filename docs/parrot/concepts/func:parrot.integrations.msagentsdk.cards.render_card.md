---
type: Concept
title: render_card()
id: func:parrot.integrations.msagentsdk.cards.render_card
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Render a `SemanticUIResult` as Adaptive Card 1.4 JSON.
---

# render_card

```python
def render_card(result: SemanticUIResult, *, max_table_rows: int=15, max_card_bytes: int=25000) -> dict
```

Render a `SemanticUIResult` as Adaptive Card 1.4 JSON.

Args:
    result: The semantic UI result to render.
    max_table_rows: Maximum table rows to render before truncating with
        a "showing N of M" note.
    max_card_bytes: Maximum serialized card size in bytes; exceeding it
        raises `CardRenderError` so the caller can fall back to
        `render_text`.

Returns:
    The Adaptive Card as a plain dict (`type`, `version`, `body`,
    `actions`).

Raises:
    CardRenderError: If the result cannot be rendered within limits
        (unknown `result_type` at runtime, or the serialized card
        exceeds `max_card_bytes`).
