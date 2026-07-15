---
type: Concept
title: merge_tab1_blocks()
id: func:parrot.bots.flows.crew.result_infographic.merge_tab1_blocks
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Insert the LLM-authored Tab 1 as the first tab in the ``tab_view``.
---

# merge_tab1_blocks

```python
def merge_tab1_blocks(tab1_blocks: List[Dict[str, Any]], deterministic_blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]
```

Insert the LLM-authored Tab 1 as the first tab in the ``tab_view``.

Args:
    tab1_blocks: LLM-authored blocks (e.g. ``SummaryBlock`` dicts) for
        the Executive Summary & Insights tab.
    deterministic_blocks: The ``[title, tab_view]`` list produced by
        :func:`build_deterministic_tabs`.

Returns:
    A new block list with Tab 1 inserted as the first tab of the
    ``tab_view`` block. Does not mutate ``deterministic_blocks``.
