---
type: Concept
title: create_think_tool()
id: func:parrot_tools.think.create_think_tool
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Factory function to create domain-specific ThinkTool instances.
---

# create_think_tool

```python
def create_think_tool(domain: Optional[str]=None, name: Optional[str]=None, extra_context: str='', output_handler: Optional[Union[str, Callable[[ThinkInput], str]]]=None) -> ThinkTool
```

Factory function to create domain-specific ThinkTool instances.

Args:
    domain: Predefined domain ('data', 'scraping', 'query', 'rag')
            or None for generic ThinkTool
    name: Custom tool name (overrides domain default)
    extra_context: Additional context appended to description
    output_handler: Custom output handler

Returns:
    Configured ThinkTool instance

Example:
    # Using predefined domain
    data_tool = create_think_tool(domain='data')

    # Custom configuration
    custom_tool = create_think_tool(
        domain='scraping',
        name='plan_ecommerce_scrape',
        extra_context='Consider rate limiting for this e-commerce site.'
    )
