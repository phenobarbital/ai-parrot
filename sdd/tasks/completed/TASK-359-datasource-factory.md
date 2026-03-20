# TASK-359: DataSourceFactory

**Feature**: Ontological Graph RAG
**Spec**: `sdd/specs/ontological-graph-rag.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (1h)
**Depends-on**: TASK-358
**Assigned-to**: —

---

## Context

> Create the DataSourceFactory that resolves source names to ExtractDataSource implementations.
> Implements spec Module 4.

---

## Scope

### Create `parrot/loaders/extractors/factory.py`

`DataSourceFactory`:
- `_builtin_types` class-level dict: `{"csv": CSVDataSource, "json": JSONDataSource, "sql": SQLDataSource, "records": RecordsDataSource}`.
- `_api_registry` class-level dict: empty initially, extendable for Workday/Jira etc.
- `register_api_source(cls, name: str, source_cls: type)` — class method to register custom API sources.
- `get(self, source_name: str, source_config: dict) -> ExtractDataSource`:
  1. Check `source_config["type"]` (or fall back to `source_name`).
  2. Look up in `_builtin_types`.
  3. Look up in `_api_registry`.
  4. Raise `UnknownDataSourceError`.

### Update `parrot/loaders/extractors/__init__.py`

Export `DataSourceFactory`.

---

## Acceptance Criteria

- [ ] Factory resolves built-in types by `type` key in config.
- [ ] Factory supports custom API source registration.
- [ ] Unknown source raises `UnknownDataSourceError` with descriptive message.
- [ ] Unit test covers resolution and error path.

---

## Files to Create / Modify

| File | Action |
|---|---|
| `parrot/loaders/extractors/factory.py` | **Create** |
| `parrot/loaders/extractors/__init__.py` | **Modify** — add export |
