---
type: Wiki Entity
title: YAMLRenderer
id: class:parrot.outputs.formats.yaml.YAMLRenderer
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Renderer for YAML output using yaml-rs (Rust) or PyYAML fallback
relates_to:
- concept: class:parrot.outputs.formats.base.BaseRenderer
  rel: extends
---

# YAMLRenderer

Defined in [`parrot.outputs.formats.yaml`](../summaries/mod:parrot.outputs.formats.yaml.md).

```python
class YAMLRenderer(BaseRenderer)
```

Renderer for YAML output using yaml-rs (Rust) or PyYAML fallback

## Methods

- `async def render(self, response: Any, environment: str='default', **kwargs) -> Tuple[str, Any]` — Render response as YAML.
