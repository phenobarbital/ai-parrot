# TASK-2370: legal.ontology.yaml — entities and relations

**Feature**: FEAT-449 — Legal Norms Graph (BOE consolidated legislation with temporal validity)
**Spec**: `sdd/specs/legal-norms-graph-boe.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2. The parent proposal's key finding (F003) is that the graph vocabulary is
**declarative configuration**, not framework code: `OntologyMerger` loads ontology YAML layers,
`EntityDef` accepts arbitrary collections, and `initialize_tenant` auto-provisions the ArangoDB
collections. A legal domain layer is therefore a config file, not a fork of GraphIndex.

This task declares the entity and relation vocabulary only. The `article_in_force` traversal
pattern is TASK-2371 (same file, sequential) so that the schema can be validated in isolation
before query logic is layered on.

---

## Scope

- Create `legal.ontology.yaml` declaring three entities:
  - `Norma` — collection `norma`, `key_field: boe_id`
  - `Articulo` — collection `articulo`, `key_field: articulo_key`, including the
    `versions` property (type `list`)
  - `Materia` — collection `materia`, `key_field: materia_id` (static taxonomy)
- Declare three relations: `modifica` (Norma → Articulo), `deroga` (Norma → Norma),
  `pertenece_a` (Norma → Materia).
- Set `source: boe` on `Norma` and `Articulo`; leave `Materia` **without** a source.
- Write a unit test asserting the layer merges cleanly with `base.ontology.yaml`.

**NOT in scope**: the `article_in_force` traversal pattern (TASK-2371); any `Sentencia`
entity or case-law edges; populating `vectorize` (v1 has no chunking).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/ontology/defaults/domains/legal.ontology.yaml` | CREATE | Legal domain ontology layer |
| `packages/ai-parrot/tests/knowledge/ontology/test_legal_ontology.py` | CREATE | Merge + shape tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from pathlib import Path
from parrot.knowledge.ontology.merger import OntologyMerger          # merger.py:26
from parrot.knowledge.ontology.schema import (
    MergedOntology,      # schema.py:330
    EntityDef,           # schema.py:40
    RelationDef,         # schema.py:116
    PropertyDef,         # schema.py:18
)
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/ontology/schema.py:18
class PropertyDef(BaseModel):
    type: Literal["string","int","float","boolean","date","list","dict"]   # CLOSED enum
    required: bool = False
    unique: bool = False
    default: Any = None
    enum: list[str] | None = None
    description: str | None = None
    model_config = ConfigDict(extra="forbid")

# packages/ai-parrot/src/parrot/knowledge/ontology/schema.py:40
class EntityDef(BaseModel):
    collection: str | None = None
    source: str | None = None        # entities WITHOUT this are SKIPPED by the refresh pipeline
    key_field: str | None = None
    properties: list[dict[str, PropertyDef]] = Field(default_factory=list)
    vectorize: list[str] = Field(default_factory=list)
    extend: bool = False
    model_config = ConfigDict(extra="forbid")

# packages/ai-parrot/src/parrot/knowledge/ontology/schema.py:116
class RelationDef(BaseModel):
    from_entity: str = Field(alias="from")    # YAML key is `from`, NOT `from_entity`
    to_entity: str = Field(alias="to")        # YAML key is `to`,   NOT `to_entity`
    edge_collection: str
    properties: list[dict[str, PropertyDef]] = Field(default_factory=list)
    discovery: DiscoveryConfig = Field(default_factory=DiscoveryConfig)
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

# packages/ai-parrot/src/parrot/knowledge/ontology/schema.py:300
class OntologyDefinition(BaseModel):     # the root model for ONE yaml layer
    name: str
    version: str = "1.0"
    extends: str | None = None
    description: str | None = None
    entities: dict[str, EntityDef] = Field(default_factory=dict)
    relations: dict[str, RelationDef] = Field(default_factory=dict)
    traversal_patterns: dict[str, TraversalPattern] = Field(default_factory=dict)
    model_config = ConfigDict(extra="forbid")

# packages/ai-parrot/src/parrot/knowledge/ontology/schema.py:330
class MergedOntology(BaseModel):
    entities: dict[str, EntityDef]
    relations: dict[str, RelationDef]
    traversal_patterns: dict[str, TraversalPattern]
    def get_entity_collections(self) -> list[str]: ...
    def get_edge_collections(self) -> list[str]: ...

# packages/ai-parrot/src/parrot/knowledge/ontology/merger.py:26
class OntologyMerger:
    def merge(self, yaml_paths: list[Path]) -> MergedOntology: ...   # merger.py:51
```

### Verified YAML shape (from the shipped domain example)

Confirmed in `defaults/domains/field_services.ontology.yaml` — relations at line 61,
traversal patterns at line 86:

```yaml
relations:
  assigned_to:
    from: Employee            # <- alias key, not from_entity
    to: Project
    edge_collection: assigned_to
    discovery:
      strategy: field_match
      rules:
        - source_field: project_code
          target_field: project_id
          match_type: exact
```

### Does NOT Exist

- ~~A `date` list type or nested-model property type~~ — `PropertyDef.type` is a **closed
  Literal**: `string|int|float|boolean|date|list|dict`. `versions` MUST be declared `list`;
  its per-entry shape is enforced in Python by the parser (TASK-2372), not by the ontology.
- ~~`from_entity:` / `to_entity:` as YAML keys~~ — the YAML keys are `from:` and `to:`.
  Using the Python attribute names will fail validation.
- ~~Any existing legal ontology~~ — `defaults/domains/` contains exactly one file,
  `field_services.ontology.yaml`. You are adding the second.
- ~~`Sentencia`, `Tribunal`, `Concepto` entities~~ — out of scope for v1 (Sprint 2+).

---

## Implementation Notes

### Pattern to Follow

Mirror the structure of `defaults/base.ontology.yaml` (top-level `name`, `version`,
`description`, `entities`, `relations`) and `defaults/domains/field_services.ontology.yaml`
(domain layer that extends base).

### Key Constraints

- **`extra="forbid"` on every ontology model.** A typo'd key raises rather than being
  ignored — this is a feature. Run the merge test early; it is the cheapest failure signal.
- `Materia` must have **no** `source` key: `OntologyRefreshPipeline.run` skips entities whose
  `entity_def.source` is falsy, which is exactly the desired behaviour for a static taxonomy.
- `Norma` and `Articulo` must declare `source: boe` or the refresh pipeline will silently
  skip them.
- Leave `vectorize` empty/absent — v1 does no chunking or embedding.
- Property names must match what the parser (TASK-2372) will emit. Suggested `Articulo`
  properties: `articulo_key`, `norma_ref`, `number`, `versions`.

### References in Codebase

- `packages/ai-parrot/src/parrot/knowledge/ontology/defaults/domains/field_services.ontology.yaml` — domain layer template
- `packages/ai-parrot/src/parrot/knowledge/ontology/defaults/base.ontology.yaml` — base layer
- `packages/ai-parrot/tests/knowledge/ontology/test_ontology_merger.py` — merge-test style

---

## Acceptance Criteria

- [ ] `legal.ontology.yaml` exists under `defaults/domains/` and parses as an `OntologyDefinition`
- [ ] `OntologyMerger().merge([base_path, legal_path])` returns a `MergedOntology` without raising
- [ ] Merged ontology contains entities `Norma`, `Articulo`, `Materia`
- [ ] Merged ontology contains relations `modifica`, `deroga`, `pertenece_a`
- [ ] `get_entity_collections()` includes `norma`, `articulo`, `materia`
- [ ] `get_edge_collections()` includes `modifica`, `deroga`, `pertenece_a`
- [ ] `Articulo.versions` is declared with `type: list`
- [ ] `Norma.source == "boe"` and `Articulo.source == "boe"`; `Materia.source is None`
- [ ] All tests pass: `pytest packages/ai-parrot/tests/knowledge/ontology/test_legal_ontology.py -v`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/ontology/test_legal_ontology.py
from pathlib import Path
import pytest
from parrot.knowledge.ontology.merger import OntologyMerger
from parrot.knowledge.ontology.parser import OntologyParser


@pytest.fixture
def merged():
    defaults = OntologyParser.get_defaults_dir()
    return OntologyMerger().merge([
        defaults / "base.ontology.yaml",
        defaults / "domains" / "legal.ontology.yaml",
    ])


class TestLegalOntology:
    def test_entities_present(self, merged):
        for name in ("Norma", "Articulo", "Materia"):
            assert name in merged.entities

    def test_relations_present(self, merged):
        for name in ("modifica", "deroga", "pertenece_a"):
            assert name in merged.relations

    def test_collections(self, merged):
        assert {"norma", "articulo", "materia"} <= set(merged.get_entity_collections())
        assert {"modifica", "deroga", "pertenece_a"} <= set(merged.get_edge_collections())

    def test_versions_is_list_type(self, merged):
        props = {k: v for d in merged.entities["Articulo"].properties for k, v in d.items()}
        assert props["versions"].type == "list"

    def test_source_wiring(self, merged):
        assert merged.entities["Norma"].source == "boe"
        assert merged.entities["Articulo"].source == "boe"
        assert not merged.entities["Materia"].source  # static taxonomy — must be skipped
```

---

## Agent Instructions

1. **Read the spec** at `sdd/specs/legal-norms-graph-boe.spec.md` (§2 Data Models, §6).
2. **Check dependencies** — none.
3. **Verify the Codebase Contract** before writing the YAML.
4. **Update status** in `sdd/tasks/index/legal-norms-graph-boe.json` → `"in-progress"`.
5. **Implement** the YAML layer and tests.
6. **Verify** all acceptance criteria.
7. **Move this file** to `sdd/tasks/completed/TASK-2370-legal-ontology-entities.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note**.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
