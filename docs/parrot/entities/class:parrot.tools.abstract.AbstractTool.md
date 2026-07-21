---
type: Wiki Entity
title: AbstractTool
id: class:parrot.tools.abstract.AbstractTool
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Abstract base class for all tools in the ai-parrot framework.
relates_to:
- concept: class:parrot.core.events.lifecycle.mixin.EventEmitterMixin
  rel: extends
---

# AbstractTool

Defined in [`parrot.tools.abstract`](../summaries/mod:parrot.tools.abstract.md).

```python
class AbstractTool(EventEmitterMixin, ABC)
```

Abstract base class for all tools in the ai-parrot framework.

This class provides a unified interface for tools that can be used by both
conversational bots and agents. It includes common functionality like:
- Name and description management
- JSON schema generation
- File path management
- Logging and error handling
- Async/sync execution support
- Lifecycle event emission (FEAT-176)

## Methods

- `def clone(self)` — Create a new instance of this tool with the same configuration.
- `def get_schema(self) -> Dict[str, Any]` — Get the JSON schema for this tool.
- `def get_tool_schema(self) -> Dict[str, Any]` — Get the JSON schema for the tool's arguments.
- `def validate_args(self, **kwargs) -> BaseModel` — Validate arguments using the tool's schema.
- `async def execute(self, *args, **kwargs) -> ToolResult` — Execute the tool with error handling and result standardization.
- `async def run(self, *args, **kwargs) -> Any` — Public alias for executing the tool directly without the ToolResult wrapper.
- `def to_static_url(self, file_path: Union[str, Path]) -> str` — Convert an absolute file path to a static URL.
- `def relative_url(self, url: str) -> str` — Convert an absolute URL to a relative URL based on the base URL.
- `def generate_filename(self, prefix: str='output', extension: str='', include_timestamp: bool=True) -> str` — Generate a unique filename with optional timestamp.
- `def validate_output_path(self, file_path: Union[str, Path]) -> Path` — Validate and ensure the output path is within allowed directories.
