---
type: Concept
title: extract_infographic_data()
id: func:parrot.outputs.formats.infographic.extract_infographic_data
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Extract infographic data from the AIMessage response.
---

# extract_infographic_data

```python
def extract_infographic_data(response: Any) -> dict
```

Extract infographic data from the AIMessage response.

Module-level extraction shared by both infographic renderers.

Handles multiple scenarios:
1. response.structured_output is an InfographicResponse
2. response.output is an InfographicResponse
3. response.output is a dict with blocks
4. Raw dict/string fallback

Args:
    response: The AIMessage or raw data.

Returns:
    Dict representation of the InfographicResponse.
