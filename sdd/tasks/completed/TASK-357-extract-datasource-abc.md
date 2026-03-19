# TASK-357: ExtractDataSource ABC & Base Models

**Feature**: Ontological Graph RAG
**Spec**: `sdd/specs/ontological-graph-rag.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-3h)
**Depends-on**: TASK-356
**Assigned-to**: —

---

## Context

> Create the ExtractDataSource abstract base class and its data models. This is a generic,
> reusable abstraction for structured record extraction, separate from existing Loaders.
> Implements spec Module 2.

---

## Scope

### Create `parrot/loaders/extractors/base.py`

1. **`ExtractedRecord(BaseModel)`**:
   - `data: dict[str, Any]` — actual field values from source.
   - `metadata: dict[str, Any] = {}` — provenance info.

2. **`ExtractionResult(BaseModel)`**:
   - `records: list[ExtractedRecord]`
   - `total: int`
   - `errors: list[str] = []`
   - `warnings: list[str] = []`
   - `source_name: str`
   - `extracted_at: datetime`

3. **`ExtractDataSource(ABC)`**:
   - `__init__(self, name: str, config: dict[str, Any] = None)` — store name, config, create logger.
   - `async extract(self, fields: list[str] | None = None, filters: dict[str, Any] | None = None) -> ExtractionResult` — abstract.
   - `async list_fields(self) -> list[str]` — abstract.
   - `async validate(self, expected_fields: list[str] | None = None) -> bool` — concrete, calls `list_fields()`, checks missing fields, raises `DataSourceValidationError`.

### Update `parrot/loaders/extractors/__init__.py`

Export `ExtractDataSource`, `ExtractedRecord`, `ExtractionResult`.

---

## Acceptance Criteria

- [ ] `ExtractDataSource` is an ABC that cannot be instantiated directly.
- [ ] `extract()` and `list_fields()` are abstract methods.
- [ ] `validate()` is concrete and catches missing fields.
- [ ] `ExtractionResult` includes `extracted_at` timestamp.
- [ ] Logger follows pattern: `logging.getLogger(f'Parrot.Extractors.{cls.__name__}')`.
- [ ] All classes exported from `parrot.loaders.extractors`.

---

## Files to Create / Modify

| File | Action |
|---|---|
| `parrot/loaders/extractors/base.py` | **Create** |
| `parrot/loaders/extractors/__init__.py` | **Modify** — add exports |
