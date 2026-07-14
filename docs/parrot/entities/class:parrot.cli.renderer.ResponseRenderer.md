---
type: Wiki Entity
title: ResponseRenderer
id: class:parrot.cli.renderer.ResponseRenderer
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Renders AIMessage responses to the terminal via Rich.
---

# ResponseRenderer

Defined in [`parrot.cli.renderer`](../summaries/mod:parrot.cli.renderer.md).

```python
class ResponseRenderer
```

Renders AIMessage responses to the terminal via Rich.

Supports both batch mode (full response rendered at once) and streaming
mode (incremental token display via ``rich.live.Live``).

Attributes:
    console: Rich Console instance used for all output.

## Methods

- `def render(self, response: AIMessage) -> None` — Render a complete AIMessage to the terminal.
- `def render_error(self, error: Exception) -> None` — Render an exception in a styled Rich panel.
- `def render_table(self, headers: List[str], rows: List[List[str]], title: Optional[str]=None) -> None` — Render tabular data using Rich Table.
- `def render_info(self, lines: List[tuple[str, str]]) -> None` — Render key-value info lines.
- `def render_stream_start(self) -> None` — Begin a streaming live display session.
- `def render_stream_chunk(self, text: str) -> None` — Append a streamed token chunk to the live display.
- `def render_stream_end(self, response: Optional[AIMessage]=None) -> None` — Finalise the streaming display and show metadata.
- `def print(self, *args: Any, **kwargs: Any) -> None` — Forward arbitrary print calls to the Rich console.
