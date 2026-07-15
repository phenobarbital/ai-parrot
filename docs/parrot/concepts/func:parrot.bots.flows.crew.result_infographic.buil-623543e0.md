---
type: Concept
title: build_deterministic_tabs()
id: func:parrot.bots.flows.crew.result_infographic.build_deterministic_tabs
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Build the deterministic ``crew_report`` block list.
---

# build_deterministic_tabs

```python
def build_deterministic_tabs(execution_memory: ExecutionMemory, final_output: Any, exclude_node_id: Optional[str]=None, artifact_store: Optional[Any]=None) -> List[Dict[str, Any]]
```

Build the deterministic ``crew_report`` block list.

Produces a ``[title, tab_view]`` block list where the ``tab_view``
contains the Final-Result tab followed by one tab per research agent
found in ``execution_memory.results`` — excluding ``exclude_node_id``
(the ResultAgent's own node, to avoid self-reference). The LLM-authored
Tab 1 (Executive Summary) is NOT included here; call
:func:`merge_tab1_blocks` afterwards to insert it as the first tab.

Args:
    execution_memory: The crew's ``ExecutionMemory`` for the current run.
    final_output: The crew's final result (``FlowResult.output``).
    exclude_node_id: Node id to exclude from the per-agent tabs (the
        ResultAgent's own id).
    artifact_store: Optional duck-typed artifact publisher; see
        :func:`_summarize_content`.

Returns:
    A list with a ``title`` block followed by a ``tab_view`` block.
