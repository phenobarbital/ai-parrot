---
type: Wiki Entity
title: InfographicToolkit
id: class:parrot.tools.infographic_toolkit.InfographicToolkit
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Toolkit that produces frozen, multi-dataset HTML infographic artifacts.
relates_to:
- concept: class:parrot.tools.toolkit.AbstractToolkit
  rel: extends
---

# InfographicToolkit

Defined in [`parrot.tools.infographic_toolkit`](../summaries/mod:parrot.tools.infographic_toolkit.md).

```python
class InfographicToolkit(AbstractToolkit)
```

Toolkit that produces frozen, multi-dataset HTML infographic artifacts.

Usage::

    toolkit = InfographicToolkit(artifact_store=store)
    tools = toolkit.get_tools()
    # Attach to a PandasAgent before calling ask().
    toolkit._bot = pandas_agent

Tools exposed (prefixed with ``infographic_``)::

    infographic_render            — typed blocks + pandas (PandasAgent).
    infographic_render_template   — trusted HTML+Jinja template + data (ANY agent).
    infographic_list_templates
    infographic_get_template_contract
    infographic_validate_blocks

## Methods

- `def add_template(self, name: str, source: str) -> None` — Register a trusted in-memory HTML+Jinja template for ``render_template``.
- `def get_tools(self, **kwargs)` — Return the generated tools, ensuring return_direct is propagated.
- `def set_bot(self, bot: Any) -> None` — Bind this toolkit to a bot instance for enhance-mode support.
- `async def render(self, template_name: str, theme: Optional[str], mode: Literal['deterministic', 'enhance'], data_variables: List[str], blocks: Optional[List[Dict[str, Any]]]=None, blocks_variable: Optional[str]=None, enhance_brief: Optional[str]=None) -> InfographicRenderResult` — Validate, render, and persist an infographic artifact.
- `async def render_template(self, template_name: str, data: Optional[Dict[str, Any]]=None, theme: Optional[str]=None, title: Optional[str]=None) -> InfographicRenderResult` — Render a pre-registered HTML+Jinja template into an infographic artifact.
- `async def list_templates(self) -> List[Dict[str, str]]` — Return the list of available infographic templates.
- `async def get_template_contract(self, template_name: str) -> Dict[str, Any]` — Return the positional block contract for a template.
- `async def validate_blocks(self, template_name: str, blocks: Optional[List[Dict[str, Any]]]=None, blocks_variable: Optional[str]=None) -> Dict[str, Any]` — Dry-run block validation without rendering or persisting.
- `async def build_block(self, block_type: str, into: str='infographic_blocks', data_variable: Optional[str]=None, chart_type: Optional[str]=None, label_column: Optional[str]=None, value_columns: Optional[List[str]]=None, table_columns: Optional[List[str]]=None, max_rows: Optional[int]=None, title: Optional[str]=None, layout: Optional[str]=None, block: Optional[Dict[str, Any]]=None) -> Dict[str, Any]` — Build ONE infographic block from REPL data and append it to a list.
