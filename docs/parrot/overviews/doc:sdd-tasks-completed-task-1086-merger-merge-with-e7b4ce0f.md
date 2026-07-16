---
type: Wiki Overview
title: 'TASK-1086: OntologyMerger.merge_with_overlay Extension'
id: doc:sdd-tasks-completed-task-1086-merger-merge-with-overlay-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'The `OntologyMerger` currently supports merging YAML layers via `merge()`
  and in-memory `OntologyDefinition` lists via `merge_definitions()`. This task adds
  `merge_with_overlay()` which combines both: YAML layers first, then in-memory PG-sourced
  overlay definitions on top. It als'
relates_to:
- concept: mod:parrot.knowledge.ontology.exceptions
  rel: mentions
- concept: mod:parrot.knowledge.ontology.merger
  rel: mentions
- concept: mod:parrot.knowledge.ontology.schema
  rel: mentions
---

# TASK-1086: OntologyMerger.merge_with_overlay Extension

**Feature**: FEAT-159 — Topic-Authority Ontology Curation
**Spec**: `sdd/specs/topic-authority-ontology.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1085
**Assigned-to**: unassigned

---

## Context

The `OntologyMerger` currently supports merging YAML layers via `merge()` and in-memory `OntologyDefinition` lists via `merge_definitions()`. This task adds `merge_with_overlay()` which combines both: YAML layers first, then in-memory PG-sourced overlay definitions on top. It also enforces the framework-override guard: overlays cannot mutate entities/relations/patterns present in `base.ontology.yaml`. See spec §3 Module 14.

---

## Scope

- Add `merge_with_overlay(yaml_paths, overlay_defs)` method to `OntologyMerger`.
- Implement framework-override guard: any overlay attempting to redefine an entity, relation, or traversal pattern already defined in the base YAML layer raises `FrameworkOverrideError`.
- Regression safety: when `overlay_defs` is empty, output must be identical to `merge(yaml_paths)`.
- Write unit tests.

**NOT in scope**: PG queries to fetch overlays (that's Module 15), dry-run logic (Module 10), HTTP routes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/ontology/merger.py` | MODIFY | Add `merge_with_overlay()` method |
| `tests/knowledge/ontology/test_merger_overlay.py` | CREATE | Unit tests for overlay merging |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.knowledge.ontology.merger import OntologyMerger          # merger.py:26
from parrot.knowledge.ontology.schema import (
    OntologyDefinition,   # schema.py:155
    MergedOntology,       # schema.py:185
    EntityDef,            # schema.py:39
    RelationDef,          # schema.py:106
    TraversalPattern,     # schema.py:131
)
from parrot.knowledge.ontology.exceptions import FrameworkOverrideError  # to be created by TASK-1085
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/ontology/merger.py
class OntologyMerger:                                                  # line 26
    def merge(self, yaml_paths: list[Path]) -> MergedOntology: ...     # line 51
    def merge_definitions(
        self, definitions: list[OntologyDefinition]
    ) -> MergedOntology: ...                                           # line 99
    def _merge_entities(
        self, base: dict[str, EntityDef], overlay: dict[str, EntityDef]
    ) -> dict[str, EntityDef]: ...                                     # line 144
    def _extend_entity(
        self, base: EntityDef, extension: EntityDef
    ) -> EntityDef: ...                                                # line 162
    def _merge_relations(
        self, base: dict[str, RelationDef], overlay: dict[str, RelationDef]
    ) -> dict[str, RelationDef]: ...                                   # line 204
    def _merge_patterns(
        self, base: dict[str, TraversalPattern], overlay: dict[str, TraversalPattern]
    ) -> dict[str, TraversalPattern]: ...                              # line 253
    def _validate_integrity(self, merged: MergedOntology) -> None: ... # line 278
```

### Does NOT Exist

- ~~`OntologyMerger.merge_with_overlay()`~~ — does not exist; this task creates it.
- ~~`FrameworkOverrideError`~~ — created by TASK-1085; verify import before use.

---

## Implementation Notes

### Pattern to Follow

```python
# Leverage existing merge_definitions() which already handles in-memory OntologyDefinition merging.
# The new method should:
# 1. Parse YAML layers via the existing _parse path used by merge()
# 2. Identify which entities/relations/patterns come from the base (framework) layer
# 3. Merge YAML layers normally
# 4. For each overlay_def, check that it does NOT redefine framework keys
# 5. Merge overlays on top using _merge_entities/_merge_relations/_merge_patterns
# 6. Run _validate_integrity on the final result

def merge_with_overlay(
    self,
    yaml_paths: list[Path],
    overlay_defs: list[OntologyDefinition],
) -> MergedOntology:
    """Merge YAML layers + in-memory PG-sourced overlay definitions.

    Raises:
        FrameworkOverrideError: an overlay attempts to mutate a framework
            entity/relation/pattern.
    """
    ...
```

### Key Constraints

- The "framework" layer is always the FIRST yaml_path (`base.ontology.yaml`). Its entity/relation/pattern keys form the immutable set.
- Domain and client YAML layers CAN extend framework entities (they use `extend: true`). PG overlays CANNOT override framework entities even with `extend: true`.
- Empty `overlay_defs` list must produce identical output to `merge(yaml_paths)` — this is an acceptance criterion.
- Use the existing `_merge_entities`, `_merge_relations`, `_merge_patterns` helpers for the actual merge logic.

### References in Codebase

- `packages/ai-parrot/src/parrot/knowledge/ontology/merger.py` — all internal merge helpers.
- `packages/ai-parrot/src/parrot/knowledge/ontology/schema.py` — `OntologyDefinition` and field structure.

---

## Acceptance Criteria

- [ ] `merge_with_overlay()` method exists on `OntologyMerger`.
- [ ] YAML chain + empty overlay produces identical `MergedOntology` as `merge(yaml_paths)`.
- [ ] Overlay adding a NEW entity succeeds; merged ontology contains it.
- [ ] Overlay redefining a framework entity raises `FrameworkOverrideError`.
- [ ] Overlay redefining a framework relation raises `FrameworkOverrideError`.
- [ ] Overlay redefining a framework traversal pattern raises `FrameworkOverrideError`.
- [ ] `_validate_integrity` runs on the final merged result.
- [ ] All tests pass: `pytest tests/knowledge/ontology/test_merger_overlay.py -v`
- [ ] Existing merger tests still pass: `pytest tests/knowledge/ontology/test_merger*.py -v`

---

## Test Specification

```python
# tests/knowledge/ontology/test_merger_overlay.py
import pytest
from pathlib import Path
from parrot.knowledge.ontology.merger import OntologyMerger
from parrot.knowledge.ontology.schema import OntologyDefinition, EntityDef, RelationDef, TraversalPattern
from parrot.knowledge.ontology.exceptions import FrameworkOverrideError


@pytest.fixture
def merger():
    return OntologyMerger()


@pytest.fixture
def base_yaml_paths(tmp_path) -> list[Path]:
    """Create minimal base + domain YAML files for testing."""
    ...


class TestMergeWithOverlay:
    def test_empty_overlay_matches_merge(self, merger, base_yaml_paths):
        """Empty overlay produces identical result to merge()."""
        from_merge = merger.merge(base_yaml_paths)
        from_overlay = merger.merge_with_overlay(base_yaml_paths, [])
        assert from_merge.entities == from_overlay.entities
        assert from_merge.relations == from_overlay.relations

    def test_overlay_adds_new_entity(self, merger, base_yaml_paths):
        """Overlay with new entity_type merges successfully."""
        overlay = OntologyDefinition(
            name="pg_overlay",
            entities={"Project": EntityDef(collection="projects")},
        )
        result = merger.merge_with_overlay(base_yaml_paths, [overlay])
        assert "Project" in result.entities

    def test_framework_entity_override_blocked(self, merger, base_yaml_paths):
        """Overlay redefining a base entity raises FrameworkOverrideError."""
        # "Employee" is in base.ontology.yaml
        overlay = OntologyDefinition(
            name="pg_overlay",
            entities={"Employee": EntityDef(collection="employees_v2")},
        )
        with pytest.raises(FrameworkOverrideError):
            merger.merge_with_overlay(base_yaml_paths, [overlay])

    def test_framework_relation_override_blocked(self, merger, base_yaml_paths):
        """Overlay redefining a base relation raises FrameworkOverrideError."""
        ...

    def test_framework_pattern_override_blocked(self, merger, base_yaml_paths):
        """Overlay redefining a base traversal pattern raises FrameworkOverrideError."""
        ...

    def test_multiple_overlays_merged_in_order(self, merger, base_yaml_paths):
        """Multiple overlay defs are merged left-to-right."""
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read** `packages/ai-parrot/src/parrot/knowledge/ontology/merger.py` — understand existing merge flow
2. **Read** `packages/ai-parrot/src/parrot/knowledge/ontology/schema.py` — understand `OntologyDefinition` structure
3. **Verify** TASK-1085 exceptions are available (or use a local stub for testing)
4. **Implement** `merge_with_overlay()` reusing internal merge helpers
5. **Run tests**: `pytest tests/knowledge/ontology/test_merger*.py -v`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: 
**Date**: 
**Notes**: 

**Deviations from spec**: none | describe if any
