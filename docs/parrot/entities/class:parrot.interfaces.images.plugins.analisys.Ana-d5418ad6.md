---
type: Wiki Entity
title: AnalysisPlugin
id: class:parrot.interfaces.images.plugins.analisys.AnalysisPlugin
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Plugin for analyzing images.
relates_to:
- concept: class:parrot.interfaces.images.plugins.abstract.ImagePlugin
  rel: extends
---

# AnalysisPlugin

Defined in [`parrot.interfaces.images.plugins.analisys`](../summaries/mod:parrot.interfaces.images.plugins.analisys.md).

```python
class AnalysisPlugin(ImagePlugin)
```

Plugin for analyzing images.

## Methods

- `async def start(self, **kwargs)` — Initialize the plugin and load the prompt.
- `async def analyze(self, image: Union[Path, Image.Image], **kwargs) -> dict` — Analyze the ink wall image and perform structured analysis.
