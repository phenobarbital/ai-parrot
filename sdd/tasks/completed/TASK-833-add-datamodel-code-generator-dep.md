# TASK-833: Add `datamodel-code-generator` dependency

**Feature**: FEAT-121 — Parrot FormDesigner POST Submission Pipeline
**Spec**: `sdd/specs/parrot-formdesigner-post-method.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

`PydanticModelResolver` (TASK-837) pre-generates Pydantic classes from form JSON schemas using
`datamodel-code-generator` at `FormRegistry.load_from_storage()` warm-up time. That package is
not declared in `packages/parrot-formdesigner/pyproject.toml` today — it must be added before any
downstream task that imports it. See spec §3 Module 8 and §7 External Dependencies.

---

## Scope

- Add `datamodel-code-generator>=0.25` to the `dependencies` list in
  `packages/parrot-formdesigner/pyproject.toml`.
- Run `uv lock` (or the project's equivalent lockfile update) within an activated venv to pick up
  the new dep.
- Verify the package imports inside the activated venv:
  `python -c "import datamodel_code_generator; print(datamodel_code_generator.__version__)"`.

**NOT in scope**: using the library — that is TASK-837.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/pyproject.toml` | MODIFY | Add dependency entry |
| `uv.lock` (or equivalent) | MODIFY | Regenerate lockfile |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# AFTER this task completes, the following import must resolve:
import datamodel_code_generator  # provided by datamodel-code-generator >= 0.25
```

### Existing Signatures to Use

```toml
# packages/parrot-formdesigner/pyproject.toml (existing structure)
[project]
dependencies = [
    # ...existing deps...
    # ADD: "datamodel-code-generator>=0.25",
]
```

### Does NOT Exist
- ~~`datamodel-code-generator` in the current `pyproject.toml`~~ — not declared; this task adds it.

---

## Implementation Notes

### Pattern to Follow
Match the existing dependency declaration style in `packages/parrot-formdesigner/pyproject.toml`.
Place the new dep alphabetically if the file is alphabetized, otherwise append to the list.

### Key Constraints
- **ALWAYS activate the venv before running `uv`**: `source .venv/bin/activate`.
- Use `uv add --package parrot-formdesigner datamodel-code-generator>=0.25` if the workspace supports
  it; otherwise edit `pyproject.toml` directly and run `uv lock`.
- Do NOT bump unrelated package versions while generating the lockfile — keep the diff minimal.

### References in Codebase
- `packages/parrot-formdesigner/pyproject.toml` — file to edit.

---

## Acceptance Criteria

- [ ] `datamodel-code-generator>=0.25` appears in `packages/parrot-formdesigner/pyproject.toml`.
- [ ] `uv.lock` (or equivalent) reflects the new dep.
- [ ] Inside the activated venv, `import datamodel_code_generator` succeeds.
- [ ] No unrelated package-version churn in the lockfile diff.

---

## Test Specification

```bash
# Manual verification inside the activated venv:
source .venv/bin/activate
python -c "import datamodel_code_generator; print(datamodel_code_generator.__version__)"
# Expected: a version string >= 0.25
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path above (§3 Module 8, §7 External Dependencies).
2. **Check dependencies** — none.
3. **Verify the Codebase Contract** — confirm `pyproject.toml` exists for the subpackage.
4. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`.
5. **Implement** the dependency add + lockfile update.
6. **Verify** by importing the module inside the activated venv.
7. **Move this file** to `sdd/tasks/completed/TASK-833-add-datamodel-code-generator-dep.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
