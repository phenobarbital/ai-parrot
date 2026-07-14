---
type: Wiki Entity
title: QSourceTool
id: class:parrot_tools.qsource.QSourceTool
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Tool for executing QuerySource queries and returning structured data.
relates_to:
- concept: class:parrot.tools.abstract.AbstractTool
  rel: extends
---

# QSourceTool

Defined in [`parrot_tools.qsource`](../summaries/mod:parrot_tools.qsource.md).

```python
class QSourceTool(AbstractTool)
```

Tool for executing QuerySource queries and returning structured data.

This tool can:
- Execute queries using query slugs or raw SQL
- Apply conditions, filters, and grouping
- Return results as pandas DataFrames, dictionaries, or structured outputs
- Handle multiple data sources through different drivers

## Methods

- `def get_input_schema(self) -> Dict[str, Any]` — Return the input schema for this tool.
- `def get_date_range(self, days_back: int=30) -> Dict[str, str]` — Get date range for the last N days.
- `def build_date_filter(self, date_field: str='date', days_back: int=30) -> Dict[str, List[str]]` — Build a date filter for queries.
- `def add_structured_output(self, name: str, model_class: Type[BaseModel])` — Add a structured output class that can be used for result conversion.
- `def list_available_outputs(self) -> List[str]` — List available structured output classes.
- `async def execute_with_date_range(self, query_slug: str, date_field: str='date', days_back: int=30, additional_filters: Optional[Dict]=None, **kwargs) -> ToolResult` — Execute query with automatic date range filtering.
