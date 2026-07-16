---
type: Concept
title: parse_response()
id: func:parrot.integrations.parser.parse_response
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Parse an AIMessage or similar response into structured content.
---

# parse_response

```python
def parse_response(response: Any) -> ParsedResponse
```

Parse an AIMessage or similar response into structured content.

Extracts text, images, documents, code, and tabular data from the response
for platform-specific rendering.

Args:
    response: AIMessage, AgentResponse, or similar response object
    
Returns:
    ParsedResponse with extracted content
