---
type: Concept
title: get_model_from_collection()
id: func:parrot_tools.querytoolkit.get_model_from_collection
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Extract the individual record model from a collection container model.
---

# get_model_from_collection

```python
def get_model_from_collection(collection_model: type) -> type
```

Extract the individual record model from a collection container model.

Args:
    collection_model: Collection model like VisitsByManagerOutput

Returns:
    type: Individual record model like VisitsByManagerRecord
