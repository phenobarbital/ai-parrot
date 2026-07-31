---
type: Wiki Entity
title: WhatIfTool
id: class:parrot_tools.whatif.WhatIfTool
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: What-If Analysis Tool with support for derived metrics and optimization.
relates_to:
- concept: class:parrot.tools.abstract.AbstractTool
  rel: extends
---

# WhatIfTool

Defined in [`parrot_tools.whatif`](../summaries/mod:parrot_tools.whatif.md).

```python
class WhatIfTool(AbstractTool)
```

What-If Analysis Tool with support for derived metrics and optimization.

Allows LLM to execute hypothetical scenarios on DataFrames,
optimize metrics under constraints, and compare results.

## Methods

- `def set_parent_agent(self, agent)` — Set reference to parent PandasAgent
- `def get_input_schema(self) -> type[BaseModel]`
