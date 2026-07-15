---
type: Concept
title: is_collection_model()
id: func:parrot_tools.querytoolkit.is_collection_model
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Determine if a BaseModel is a collection container (single instance with
  records field)
---

# is_collection_model

```python
def is_collection_model(structured_obj: type) -> bool
```

Determine if a BaseModel is a collection container (single instance with records field)
or a direct list model (List[SomeModel]).

Args:
    structured_obj: The class/type to inspect

Returns:
    bool: True if it's a collection container, False if it's a direct list
