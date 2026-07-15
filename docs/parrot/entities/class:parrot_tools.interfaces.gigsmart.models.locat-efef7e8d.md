---
type: Wiki Entity
title: PlaceResult
id: class:parrot_tools.interfaces.gigsmart.models.location.PlaceResult
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: A single address suggestion from the placeAutocomplete query.
---

# PlaceResult

Defined in [`parrot_tools.interfaces.gigsmart.models.location`](../summaries/mod:parrot_tools.interfaces.gigsmart.models.location.md).

```python
class PlaceResult(BaseModel)
```

A single address suggestion from the placeAutocomplete query.

Args:
    label: Human-readable address label.
    place_id: Opaque place identifier to use in location mutations.
    place_provider: The geocoding provider (e.g. ``"GOOGLE"``, ``"HERE"``).
