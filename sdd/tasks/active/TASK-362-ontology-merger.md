# TASK-362: YAML Merger — Multi-Layer Composition

**Feature**: Ontological Graph RAG
**Spec**: `sdd/specs/ontological-graph-rag.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (3-5h)
**Depends-on**: TASK-360, TASK-361
**Assigned-to**: —

---

## Context

> Merge multiple ontology YAML layers (base + domain + client) into a single MergedOntology
> with deterministic merge rules and integrity validation.
> Implements spec Module 7.

---

## Scope

### Create `parrot/knowledge/ontology/merger.py`

`OntologyMerger`:
- `merge(yaml_paths: list[Path]) -> MergedOntology` — sequential merge of YAML layers.

**Merge rules** (from spec):

**Entities:**
- `extend=True`: properties concatenated (no name collisions), vectorize unioned, source overridden, key_field/collection immutable.
- `extend=False` on existing entity: raise `OntologyMergeError`.
- New entity: added.

**Relations:**
- Existing relation (same name): from/to immutable, discovery.rules concatenated.
- New relation: validate endpoints exist, add.

**Traversal patterns:**
- Existing: trigger_intents concatenated (deduped), query_template overridden, post_action overridden.
- New: added.

**Integrity validation** (`_validate_integrity`):
- All relation endpoints reference existing entities.
- All vectorize fields reference existing entity properties.

Helper methods:
- `_load_and_validate(path) -> OntologyDefinition` — delegates to `OntologyParser.load()`.
- `_merge_entity(existing, extension)` — apply entity merge rules.
- `_validate_relation_endpoints(relation, entities, path)` — check from/to exist.

---

## Acceptance Criteria

- [ ] Entities with `extend=True` merge properties, vectorize, and source correctly.
- [ ] Entities with `extend=False` on existing entity raise `OntologyMergeError`.
- [ ] Immutable fields (key_field, collection, relation endpoints) cannot be changed.
- [ ] Relations concatenate discovery rules.
- [ ] Patterns concatenate trigger_intents and override template/post_action.
- [ ] Integrity validation catches missing entity references and invalid vectorize fields.
- [ ] `MergedOntology.layers` lists all merged file paths.
- [ ] Unit tests: extend, no-extend error, immutability, relation merge, pattern merge, integrity.

---

## Files to Create / Modify

| File | Action |
|---|---|
| `parrot/knowledge/ontology/merger.py` | **Create** |
| `tests/knowledge/test_ontology_merger.py` | **Create** |
