---
type: Wiki Entity
title: AbstractPipeline
id: class:parrot_pipelines.abstract.AbstractPipeline
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Abstract base class for all pipelines.
---

# AbstractPipeline

Defined in [`parrot_pipelines.abstract`](../summaries/mod:parrot_pipelines.abstract.md).

```python
class AbstractPipeline(ABC)
```

Abstract base class for all pipelines.

## Methods

- `def open_image(self, image_path: Union[Path, Image.Image]) -> Image.Image` — Open an image from a file path.
- `async def run(self, *args: Any, **kwargs: Any) -> Dict[str, Any]` — Run the pipeline with the provided arguments
