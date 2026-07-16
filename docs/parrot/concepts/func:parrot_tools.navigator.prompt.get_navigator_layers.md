---
type: Concept
title: get_navigator_layers()
id: func:parrot_tools.navigator.prompt.get_navigator_layers
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Return all custom Navigator prompt layers.
---

# get_navigator_layers

```python
def get_navigator_layers(page_index: NavigatorPageIndex=None) -> list[PromptLayer]
```

Return all custom Navigator prompt layers.

Args:
    page_index: If provided, includes a tree context layer with
                pre-resolved node summaries from the PageIndex.

Usage:
    page_index = NavigatorPageIndex()
    await page_index.build(adapter)

    builder = PromptBuilder.default()
    for layer in get_navigator_layers(page_index):
        builder.add(layer)
