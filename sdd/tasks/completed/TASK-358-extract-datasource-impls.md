# TASK-358: Data Source Implementations (CSV, JSON, Records, SQL, API)

**Feature**: Ontological Graph RAG
**Spec**: `sdd/specs/ontological-graph-rag.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (3-5h)
**Depends-on**: TASK-357
**Assigned-to**: —

---

## Context

> Implement concrete ExtractDataSource subclasses for CSV, JSON, in-memory records, SQL, and
> the API base class. Implements spec Module 3.

---

## Scope

### Create `parrot/loaders/extractors/csv_source.py`

`CSVDataSource(ExtractDataSource)`:
- Config: `path`, `delimiter` (default `,`), `encoding` (default `utf-8`), `skip_rows` (default 0).
- `extract()`: Use `csv.DictReader` via `asyncio.to_thread()`. Apply field projection and filters.
- `list_fields()`: Read header row only.

### Create `parrot/loaders/extractors/json_source.py`

`JSONDataSource(ExtractDataSource)`:
- Config: `path`, `records_path` (JSONPath-like dotted string, e.g. `"data.employees"`).
- `extract()`: Load JSON, navigate to `records_path`, validate target is a list. Apply filters/projection.
- `list_fields()`: Load first record, return keys.

### Create `parrot/loaders/extractors/records_source.py`

`RecordsDataSource(ExtractDataSource)`:
- `__init__(self, name: str, records: list[dict], **kwargs)` — wrap in-memory data.
- `extract()`: Return records optionally filtered/projected.
- `list_fields()`: Keys from first record.

### Create `parrot/loaders/extractors/sql_source.py`

`SQLDataSource(ExtractDataSource)`:
- Config: `dsn`, `query`, `params`.
- `extract()`: Execute parameterized SELECT via asyncpg. Validate query is read-only (SELECT only).
- `list_fields()`: Execute `query` with `LIMIT 0` to get column names.

### Create `parrot/loaders/extractors/api_source.py`

`APIDataSource(ExtractDataSource)` (ABC):
- Config: `base_url`, `auth_type`, `credentials`, `headers`, `page_size`, `max_pages`.
- Abstract: `_build_request()`, `_parse_response()`, `_get_next_page()`.
- `extract()`: Paginated loop using aiohttp — fetch page → parse → check next page → respect max_pages.
- `list_fields()`: Call `_parse_response()` on first page, return keys.

### Update `parrot/loaders/extractors/__init__.py`

Export all implementations.

---

## Acceptance Criteria

- [ ] `CSVDataSource` reads CSV files asynchronously, supports field projection and filters.
- [ ] `JSONDataSource` navigates nested structures via `records_path`.
- [ ] `RecordsDataSource` wraps `list[dict]` correctly — useful for testing.
- [ ] `SQLDataSource` validates read-only queries (no INSERT/UPDATE/DELETE).
- [ ] `APIDataSource` handles pagination with `max_pages` safety limit.
- [ ] All implementations pass `validate()` with expected fields.
- [ ] Unit tests for CSV, JSON, and Records sources.

---

## Files to Create / Modify

| File | Action |
|---|---|
| `parrot/loaders/extractors/csv_source.py` | **Create** |
| `parrot/loaders/extractors/json_source.py` | **Create** |
| `parrot/loaders/extractors/records_source.py` | **Create** |
| `parrot/loaders/extractors/sql_source.py` | **Create** |
| `parrot/loaders/extractors/api_source.py` | **Create** |
| `parrot/loaders/extractors/__init__.py` | **Modify** — add exports |
| `tests/loaders/test_extractors.py` | **Create** |
