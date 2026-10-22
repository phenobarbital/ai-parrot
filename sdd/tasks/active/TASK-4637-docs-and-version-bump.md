# TASK-4637: Docs page + parrot-formdesigner version bump

**Feature**: FEAT-730 — FormDesigner public response controls
**Spec**: `sdd/specs/formdesigner-public-form-controls.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4633, TASK-4634, TASK-4635
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6 and AC11. Hosts (FieldSync FEAT-796, navigator-svelte FEAT-797)
need one page describing the contract, and the package needs a version bump so
the host can pin the release (ai-parrot-server is released in lockstep — memory
rule "ai-parrot y ai-parrot-server van en lockstep"; the release itself is Jesús's).

---

## Scope

- Write `docs/formdesigner-public-form-controls.md`.
- Bump `parrot_formdesigner.version.__version__` (minor: `1.2.4` → `1.3.0`, unless dev already moved it — then the next minor).

**NOT in scope**: publishing the release; FieldSync/svelte changes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/formdesigner-public-form-controls.md` | CREATE | author/host documentation |
| `packages/parrot-formdesigner/src/parrot_formdesigner/version.py` | MODIFY | version bump |

---

## Codebase Contract (Anti-Hallucination)

### Existing Signatures to Use
```python
# packages/parrot-formdesigner/src/parrot_formdesigner/version.py
__version__ = "1.2.4"        # line 5 (count 1) — pyproject reads it: version = {attr = "parrot_formdesigner.version.__version__"}
```
Docs style reference: `docs/formdesigner-llm-validation-enforcement.md`, `docs/formdesigner-autonomous-persistence.md`.

### Does NOT Exist
- ~~A CHANGELOG file for parrot-formdesigner~~ — do not create one.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "docs/formdesigner-public-form-controls.md", "action": "CREATE"},
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/version.py", "action": "MODIFY"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Write the docs page from the spec's §2 and the shipped code — *why*: hosts read it, not the spec.
2. Bump the version — *why*: FieldSync pins the release that carries `on_submitted` / `tenant_scoped_submissions`.

### `docs/formdesigner-public-form-controls.md` (CREATE)
```markdown
# FormDesigner — public response controls (FEAT-730)

## `FormSchema.public_access`
<!-- FILL IN: table of fields (accepting_responses, closes_at UTC, max_responses, unique_key_field, completion) -->

## Enforcement
<!-- FILL IN: closed check before onBeforeSubmit; guarded store (advisory lock, roots-only count,
     lower(btrim()) uniqueness); pipeline channels only (REST /data, audio WS) — hosts that call
     FormSubmissionStorage.store() directly are not subject to it. -->

## HTTP
<!-- FILL IN: 409 {error, reason, field_id?}; GET …/availability body; the seven exempt globs;
     file upload on public forms without login (blob tenant = URL tenant). -->

## Host integration
<!-- FILL IN: setup_form_api(on_submitted=…, tenant_scoped_submissions=True); SubmittedEvent fields
     (no `anonymous` — public is public); deploy note: existing public forms need nothing. -->
```

### `packages/parrot-formdesigner/src/parrot_formdesigner/version.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '__version__ = "1.2.4"' version.py)
# REPLACE `__version__ = "1.2.4"` (verified: :5) with the next minor, e.g.:
__version__ = "1.3.0"
```
FILL IN: if dev moved past 1.2.4 before this task runs, bump the then-current minor instead.

### FILL IN checklist
- [ ] Docs sections
- [ ] Version value

---

## Acceptance Criteria

- [ ] Docs page exists and matches the shipped names (AC11).
- [ ] Version bumped (AC11).
- [ ] The whole feature's test files pass together.

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/unit/services/test_public_forms.py -q`
- `pytest packages/parrot-formdesigner/tests/unit/api/test_setup_form_api.py -q`

---

## Test Specification

No new tests; re-run the feature's suites.

---

## Agent Instructions

1. Feature worktree; all other FEAT-730 tasks `done`.
2. This task edits a package manifest value → it runs exclusively (`parallel: false`).
3. Commit only the listed files; `scripts/sdd/close_task.sh TASK-4637 formdesigner-public-form-controls verified`.

---

## Completion Note

*(Agent fills this in when done)*
