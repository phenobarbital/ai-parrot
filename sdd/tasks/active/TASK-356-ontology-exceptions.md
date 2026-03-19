# TASK-356: Ontology Exceptions & Package Init

**Feature**: Ontological Graph RAG
**Spec**: `sdd/specs/ontological-graph-rag.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (0.5h)
**Depends-on**: —
**Assigned-to**: —

---

## Context

> Create the `parrot/knowledge/ontology/` package structure and define all custom exceptions.
> Implements spec Module 18 and package init files.

---

## Scope

### Create `parrot/knowledge/__init__.py`

Empty init or minimal exports.

### Create `parrot/knowledge/ontology/__init__.py`

Prepare for public API exports (initially empty, populated as modules are added).

### Create `parrot/knowledge/ontology/exceptions.py`

Define all custom exceptions:

1. `OntologyError(Exception)` — base exception for all ontology errors.
2. `OntologyMergeError(OntologyError)` — raised during YAML merge when rules are violated (duplicate entity without extend, immutable field change, endpoint mismatch).
3. `OntologyIntegrityError(OntologyError)` — raised during post-merge integrity validation (missing entity references, invalid vectorize fields).
4. `AQLValidationError(OntologyError)` — raised when LLM-generated AQL fails safety validation (mutations, depth, system collections).
5. `UnknownDataSourceError(OntologyError)` — raised by DataSourceFactory when source name cannot be resolved.
6. `DataSourceValidationError(OntologyError)` — raised by ExtractDataSource.validate() when schema doesn't match.

### Create `parrot/loaders/extractors/__init__.py`

Prepare for extractor exports (initially empty).

### Create `parrot/loaders/extractors/exceptions.py`

Define extractor-specific exceptions (or re-export from ontology exceptions):
1. `DataSourceValidationError`
2. `UnknownDataSourceError`

---

## Acceptance Criteria

- [ ] `parrot/knowledge/` and `parrot/knowledge/ontology/` packages are importable.
- [ ] `parrot/loaders/extractors/` package is importable.
- [ ] All 6 exception classes defined with proper inheritance.
- [ ] Each exception has a descriptive docstring.
- [ ] No circular imports.

---

## Files to Create / Modify

| File | Action |
|---|---|
| `parrot/knowledge/__init__.py` | **Create** |
| `parrot/knowledge/ontology/__init__.py` | **Create** |
| `parrot/knowledge/ontology/exceptions.py` | **Create** |
| `parrot/loaders/extractors/__init__.py` | **Create** |
| `parrot/loaders/extractors/exceptions.py` | **Create** |
