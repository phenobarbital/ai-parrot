---
type: Concept
title: extract_scenes_from_response()
id: func:parrot_loaders.videounderstanding.extract_scenes_from_response
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Extract structured scenes from the AI response.
---

# extract_scenes_from_response

```python
def extract_scenes_from_response(response_text: str) -> List[dict]
```

Extract structured scenes from the AI response.
Attempts to parse JSON-like structures or creates scenes from the text.
