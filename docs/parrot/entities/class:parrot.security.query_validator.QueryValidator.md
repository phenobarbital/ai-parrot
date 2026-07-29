---
type: Wiki Entity
title: QueryValidator
id: class:parrot.security.query_validator.QueryValidator
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Validates queries based on query language.
---

# QueryValidator

Defined in [`parrot.security.query_validator`](../summaries/mod:parrot.security.query_validator.md).

```python
class QueryValidator
```

Validates queries based on query language.

## Methods

- `def validate_sql_query(query: str) -> Dict[str, Any]` — Validate SQL query for safety.
- `def validate_flux_query(query: str) -> Dict[str, Any]` — Validate InfluxDB Flux query for safety.
- `def validate_elasticsearch_query(query: str) -> Dict[str, Any]` — Validate Elasticsearch query (JSON DSL format).
- `def validate_query(cls, query: str, query_language: QueryLanguage) -> Dict[str, Any]` — Validate query based on its language.
- `def validate_sql_ast(cls, query: str, dialect: Optional[str]=None, read_only: bool=True, require_pk_in_where: bool=False, primary_keys: Optional[List[str]]=None) -> Dict[str, Any]` — sqlglot-backed SQL safety validator.
