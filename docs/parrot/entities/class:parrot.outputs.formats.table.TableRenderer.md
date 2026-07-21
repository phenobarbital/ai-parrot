---
type: Wiki Entity
title: TableRenderer
id: class:parrot.outputs.formats.table.TableRenderer
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Renderer for Tables supporting Rich (Terminal), HTML (Simple), and Grid.js.
relates_to:
- concept: class:parrot.outputs.formats.base.BaseRenderer
  rel: extends
---

# TableRenderer

Defined in [`parrot.outputs.formats.table`](../summaries/mod:parrot.outputs.formats.table.md).

```python
class TableRenderer(BaseRenderer)
```

Renderer for Tables supporting Rich (Terminal), HTML (Simple), and Grid.js.

## Methods

- `async def render(self, response: Any, table_mode: str='grid', title: str='', environment: str='terminal', html_mode: str='partial', **kwargs) -> Tuple[Any, Optional[Any]]` — Render table in the appropriate format.
