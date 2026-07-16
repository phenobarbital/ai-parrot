---
type: Concept
title: validate_profiles_exist()
id: func:parrot.tools.dataset_manager.spatial.registry.validate_profiles_exist
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Validate that every dataset name has a registered spatial profile.
---

# validate_profiles_exist

```python
def validate_profiles_exist(dataset_names: List[str]) -> None
```

Validate that every dataset name has a registered spatial profile.

Iterates all names and raises a single descriptive ValueError listing
every missing profile — mirrors CompositeDataSource.fetch validation.

Args:
    dataset_names: List of canonical dataset names to check.

Raises:
    ValueError: If any dataset name lacks a registered profile.
