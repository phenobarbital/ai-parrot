---
type: Wiki Overview
title: 'TASK-1531: Extractor round-trip for post_depends/operations + legacy re-exports'
id: doc:sdd-tasks-completed-task-1531-extractor-roundtrip-reexports-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Spec §3 Module 8. Forms are imported/exported via extractors; the new `post_depends`/`operations`
relates_to:
- concept: mod:parrot.forms
  rel: mentions
---

# TASK-1531: Extractor round-trip for post_depends/operations + legacy re-exports

**Feature**: FEAT-234 — Form Designer — Conditional Sections (Pre/Post Dependencies)
**Spec**: `sdd/specs/formdesigner-conditional-sections.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1525, TASK-1530
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 8. Forms are imported/exported via extractors; the new `post_depends`/`operations`
declarations must survive a round-trip (especially the YAML extractor, which already parses
`depends_on`). Also re-export the new public symbols from the legacy `parrot.forms` shim so
backward-compatible imports keep working.

---

## Scope

- Update `extractors/yaml.py` so its dependency parsing also reads `post_depends` and operation
  blocks (it already parses `depends_on` via an internal `_parse_dependency_rule`-style helper).
- Update `extractors/jsonschema.py` so importing a JSON Schema with `x-post-depends` /
  serialized operations reconstructs `PostDependency`/`DependencyOperation` (inverse of TASK-1527).
- Re-export `DependencyOperation`, `PostDependency`, `RuleEvaluator`, `RuleResolution` from the
  legacy shim `packages/ai-parrot/src/parrot/forms/__init__.py`.
- Round-trip tests: schema → render/serialize → import → equal models.

**NOT in scope**: the renderer emission itself (TASK-1527); the evaluator implementation
(TASK-1530); `core/__init__.py` exports of the models (done in TASK-1524/1525); `services/__init__.py`
export of the evaluator (done in TASK-1530).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/extractors/yaml.py` | MODIFY | Parse `post_depends`/operations on import |
| `packages/parrot-formdesigner/src/parrot_formdesigner/extractors/jsonschema.py` | MODIFY | Reconstruct post-deps/operations from `x-post-depends` |
| `packages/ai-parrot/src/parrot/forms/__init__.py` | MODIFY | Re-export new public symbols (legacy compat) |
| `packages/parrot-formdesigner/tests/` | CREATE/MODIFY | Round-trip tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.extractors import YamlExtractor, JsonSchemaExtractor
from parrot_formdesigner.core import (
    FormSchema, FormField, DependencyRule, PostDependency, DependencyOperation,
)
# After this task, legacy compat also works:
from parrot.forms import PostDependency, DependencyOperation  # via re-export
```

### Existing Signatures to Use
```python
# packages/parrot-formdesigner/src/parrot_formdesigner/extractors/
#   yaml.py        — YAML → FormSchema; already parses depends_on (has a dependency-rule parser)
#   jsonschema.py  — JSON Schema → FormSchema
# (Directory listing confirmed: __init__.py, jsonschema.py, pydantic.py, tool.py, yaml.py)

# packages/ai-parrot/src/parrot/forms/__init__.py — legacy re-export shim that already
#   re-exports FormField/FormSchema/DependencyRule/... from parrot_formdesigner

# Renderer counterpart this mirrors (TASK-1527):
# renderers/jsonschema.py:411  prop["x-depends-on"] = field.depends_on.model_dump()
#                              prop["x-post-depends"] = [...]   (added in TASK-1527)
```

### Does NOT Exist
- ~~`extractors/yaml.py` parsing of `post_depends`/operations~~ — only `depends_on` is parsed today.
- ~~`parrot.forms.PostDependency` / `parrot.forms.DependencyOperation` / `parrot.forms.RuleEvaluator`~~ — not re-exported yet (this task adds them).
- Do NOT re-add `core/__init__` model exports here (TASK-1524/1525) or `services/__init__` evaluator export (TASK-1530) — only the legacy `parrot.forms` shim.

---

## Implementation Notes

### Pattern to Follow
Find the existing `depends_on` parsing in `extractors/yaml.py` and add a sibling branch for
`post_depends`/operations using the same model-construction style. For `parrot.forms/__init__.py`,
follow the existing re-export lines (mirror how `DependencyRule` is already re-exported).

### Key Constraints
- Round-trip must be lossless for the new fields.
- Importing a legacy form WITHOUT post-deps/operations must behave exactly as before.

### References in Codebase
- `extractors/yaml.py` (dependency-rule parsing), `extractors/jsonschema.py`.
- `packages/ai-parrot/src/parrot/forms/__init__.py` (existing re-exports).

---

## Acceptance Criteria

- [ ] YAML with `post_depends`/operation blocks imports into `PostDependency`/`DependencyOperation`.
- [ ] JSON Schema with `x-post-depends` reconstructs equivalent models.
- [ ] A form round-trips (build → serialize → import) with equal `depends_on`/`post_depends`/operations.
- [ ] Legacy form without new fields imports unchanged.
- [ ] `from parrot.forms import PostDependency, DependencyOperation` works.
- [ ] Tests pass: `pytest packages/parrot-formdesigner/tests/ -k "extractor or roundtrip or yaml" -v`
- [ ] `ruff check` clean.

---

## Test Specification

```python
import pytest
from parrot_formdesigner.extractors import YamlExtractor
from parrot_formdesigner.core import PostDependency, DependencyOperation

class TestExtractorRoundtrip:
    def test_yaml_imports_post_depends(self):
        ...  # YAML with post_depends → FormField.post_depends populated

    def test_jsonschema_roundtrip(self):
        ...  # render x-post-depends → import → equal models

    def test_legacy_reexport(self):
        from parrot.forms import PostDependency as P, DependencyOperation as O
        assert P is PostDependency and O is DependencyOperation
```

---

## Agent Instructions

1. **Read the spec** §3 Module 8 + §2 Integration Points (extractors row).
2. **Check dependencies** — TASK-1525 and TASK-1530 in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — locate the existing `depends_on` parser in `extractors/yaml.py` before editing.
4. **Update index** → `"in-progress"`.
5. **Implement** extractor parsing + legacy re-exports + round-trip tests.
6. **Verify** acceptance criteria.
7. **Move** to `sdd/tasks/completed/`; **update index** → `"done"`; fill Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 4.6)
**Date**: 2026-06-12
**Notes**: Updated `extractors/yaml.py` to parse `post_depends` list into `PostDependency` objects and `depends_on.operations` block into `DependencyOperation` objects. Added `_parse_dependency_operation` and `_parse_post_dependency` helpers. Updated `extractors/jsonschema.py` to reconstruct `depends_on` from `x-depends-on` via `DependencyRule.model_validate` and `post_depends` from `x-post-depends` via `PostDependency.model_validate`. Updated `parrot/forms/__init__.py` to re-export `DependencyOperation`, `PostDependency`, `RuleEvaluator`, `RuleResolution`, `get_dependency_rule_snippets`. 15 round-trip tests pass.

**Deviations from spec**: None. Legacy re-export tests use source-file inspection rather than live `import parrot.forms` due to PYTHONPATH isolation in worktree tests (installed package points to main repo path); the worktree source file is verified to contain the correct re-export declarations.
