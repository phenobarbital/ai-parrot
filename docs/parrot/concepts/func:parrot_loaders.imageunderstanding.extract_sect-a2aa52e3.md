---
type: Concept
title: extract_sections_from_response()
id: func:parrot_loaders.imageunderstanding.extract_sections_from_response
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Extract structured sections from the AI image analysis response.
---

# extract_sections_from_response

```python
def extract_sections_from_response(response_text: str) -> List[dict]
```

Extract structured sections from the AI image analysis response.
Attempts to parse JSON-like structures or creates sections from the text.
