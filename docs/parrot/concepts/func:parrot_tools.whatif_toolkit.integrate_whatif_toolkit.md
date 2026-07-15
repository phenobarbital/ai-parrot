---
type: Concept
title: integrate_whatif_toolkit()
id: func:parrot_tools.whatif_toolkit.integrate_whatif_toolkit
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Integrate WhatIfToolkit into an agent.
---

# integrate_whatif_toolkit

```python
def integrate_whatif_toolkit(agent, dataset_manager: Optional[Any]=None, pandas_tool: Optional[Any]=None) -> WhatIfToolkit
```

Integrate WhatIfToolkit into an agent.

Resolves DatasetManager and PythonPandasTool from agent if not provided.
Registers all 6 tools and adds system prompt.

Args:
    agent: The agent to integrate with.
    dataset_manager: Optional DatasetManager instance.
    pandas_tool: Optional PythonPandasTool instance.

Returns:
    The configured WhatIfToolkit instance.
