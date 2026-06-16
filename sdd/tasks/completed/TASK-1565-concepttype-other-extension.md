# TASK-1565: Add ConceptType.OTHER to OKF Ontology

**Feature**: FEAT-216 — OKF Knowledge Lint & Bundle Interchange
**Spec**: `sdd/specs/FEAT-216-okf-knowledge-lint-and-bundle.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

OKF bundle import must handle arbitrary `type` values from external OKF bundles.
Google OKF v0.1 only requires a `type` field but doesn't constrain its values.
AI-Parrot uses `ConceptType` enum with 11 specific values. This task adds `OTHER`
as a catch-all for unknown types during import. This is the foundational change
that Module 2 (lint) and Module 4 (import) depend on.

Implements: Spec §3 Module 1.

---

## Scope

- Add `OTHER = "Other"` to `ConceptType` enum in `ontology.py`
- Verify no existing code assumes exhaustive enum coverage (no `match` without default)
- Add a unit test confirming `ConceptType.OTHER` exists and round-trips through Pydantic

**NOT in scope**: lint engine, bundle import/export, OKFToolkit changes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/okf/ontology.py` | MODIFY | Add `OTHER` value to `ConceptType` enum |
| `packages/ai-parrot/tests/knowledge/pageindex/test_okf_ontology.py` | MODIFY | Add test for `ConceptType.OTHER` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.pageindex.okf.ontology import ConceptType  # verified: ontology.py:21
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/pageindex/okf/ontology.py
class ConceptType(str, Enum):  # line 21
    SECTION = "Section"      # line 27
    POLICY = "Policy"        # line 28
    CONTROL = "Control"      # line 29
    SAFEGUARD = "Safeguard"  # line 30
    EVIDENCE = "Evidence"    # line 31
    PLAYBOOK = "Playbook"    # line 32
    PROCEDURE = "Procedure"  # line 33
    STANDARD = "Standard"    # line 34
    FRAMEWORK = "Framework"  # line 35
    REGULATION = "Regulation"  # line 36
    GUIDELINE = "Guideline"  # line 37
    # Add OTHER here, after GUIDELINE
```

### Does NOT Exist
- ~~`ConceptType.OTHER`~~ — does not exist yet; this task adds it
- ~~`ConceptType.UNKNOWN`~~ — not a valid name; use `OTHER`

---

## Implementation Notes

### Pattern to Follow
Add the new enum value after the last existing value:
```python
class ConceptType(str, Enum):
    ...
    GUIDELINE = "Guideline"
    OTHER = "Other"
```

### Key Constraints
- Must be additive — no existing code should break
- Grep for `ConceptType` across the codebase to confirm no `match`/exhaustive `if-elif` assumes all values
- The string value is `"Other"` (capitalized, matching the pattern of other values)

### References in Codebase
- `packages/ai-parrot/src/parrot/knowledge/pageindex/okf/ontology.py` — the enum to modify
- `packages/ai-parrot/src/parrot/knowledge/pageindex/okf/frontmatter.py:49` — uses `ConceptType` as field type

---

## Acceptance Criteria

- [ ] `ConceptType.OTHER` exists with value `"Other"`
- [ ] `ConceptType("Other")` returns `ConceptType.OTHER`
- [ ] All existing OKF tests still pass: `pytest packages/ai-parrot/tests/knowledge/pageindex/test_okf_*.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/knowledge/pageindex/okf/ontology.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/pageindex/test_okf_ontology.py
from parrot.knowledge.pageindex.okf.ontology import ConceptType


def test_concepttype_other_exists():
    assert ConceptType.OTHER == "Other"
    assert ConceptType("Other") is ConceptType.OTHER


def test_concepttype_other_in_members():
    assert "OTHER" in ConceptType.__members__
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/FEAT-216-okf-knowledge-lint-and-bundle.spec.md`
2. **Check dependencies** — none
3. **Verify the Codebase Contract** — confirm `ConceptType` enum is still at line 21 of `ontology.py`
4. **Grep** for `ConceptType` usages: `grep -rn "ConceptType" packages/ai-parrot/src/`
5. **Implement** the one-line enum addition
6. **Run tests**: `pytest packages/ai-parrot/tests/knowledge/pageindex/test_okf_*.py -v`

---

## Completion Note

*(Agent fills this in when done)*
