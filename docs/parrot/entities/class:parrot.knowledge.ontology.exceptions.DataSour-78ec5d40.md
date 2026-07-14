---
type: Wiki Entity
title: DataSourceValidationError
id: class:parrot.knowledge.ontology.exceptions.DataSourceValidationError
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Raised by ExtractDataSource.validate() when the source schema doesn't match.
relates_to:
- concept: class:parrot.knowledge.ontology.exceptions.OntologyError
  rel: extends
---

# DataSourceValidationError

Defined in [`parrot.knowledge.ontology.exceptions`](../summaries/mod:parrot.knowledge.ontology.exceptions.md).

```python
class DataSourceValidationError(OntologyError)
```

Raised by ExtractDataSource.validate() when the source schema doesn't match.

Examples:
    - Expected fields not found in data source
    - Source is inaccessible or returns unexpected format
