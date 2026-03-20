# TASK-361: YAML Parser

**Feature**: Ontological Graph RAG
**Spec**: `sdd/specs/ontological-graph-rag.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (1-2h)
**Depends-on**: TASK-360
**Assigned-to**: —

---

## Context

> Load and validate YAML ontology files against the Pydantic schema models.
> Default ontology files loaded from package resources.
> Implements spec Module 6.

---

## Scope

### Create `parrot/knowledge/ontology/parser.py`

`OntologyParser`:
- `load(path: Path) -> OntologyDefinition` — load YAML file, parse into `OntologyDefinition` Pydantic model. Raises `ValidationError` on invalid YAML.
- `load_default_base() -> OntologyDefinition` — load the base ontology from package resources (`defaults/base.ontology.yaml`). Use `Path(__file__).parent / "defaults"` pattern.
- Handle YAML parse errors with clear error messages including file path and line number.

### Create `parrot/knowledge/ontology/defaults/` directory

- Create `parrot/knowledge/ontology/defaults/__init__.py` (empty).

---

## Acceptance Criteria

- [ ] `OntologyParser.load()` returns a validated `OntologyDefinition`.
- [ ] Invalid YAML raises `ValidationError` with field-level details.
- [ ] `load_default_base()` loads from package resources path.
- [ ] YAML parsing errors include file path in message.
- [ ] Unit tests: valid YAML loads, invalid YAML rejected.

---

## Files to Create / Modify

| File | Action |
|---|---|
| `parrot/knowledge/ontology/parser.py` | **Create** |
| `parrot/knowledge/ontology/defaults/__init__.py` | **Create** |
| `tests/knowledge/test_ontology_parser.py` | **Create** |
