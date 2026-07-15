---
type: Concept
title: inject_rls_mongo()
id: func:parrot.tools.dataset_manager.sources.rls.inject_rls_mongo
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Build a Mongo ``$and`` filter dict from RLS predicates.
---

# inject_rls_mongo

```python
def inject_rls_mongo(source: 'MongoSource', predicates: 'list[RlsPredicate]') -> dict[str, Any]
```

Build a Mongo ``$and`` filter dict from RLS predicates.

Translates each predicate's bound parameters into Mongo ``$in`` filter
expressions and wraps them in a ``{"$and": [...]}`` structure.

Args:
    source: The :class:`~parrot.tools.dataset_manager.sources.mongo.MongoSource`
        (used to read existing ``required_filter`` if set).
    predicates: List of rendered predicates to apply.

Returns:
    A Mongo query filter dict ready for use as the ``filter`` argument.
