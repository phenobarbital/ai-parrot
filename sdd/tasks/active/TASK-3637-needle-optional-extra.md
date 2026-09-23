# TASK-3637: `ai-parrot[needle]` optional extra

**Feature**: FEAT-590 — Tool-Call Delegate
**Spec**: `sdd/specs/tool-call-delegate.spec.md`
**Status**: pending
**Priority**: low
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3624, TASK-3633
**Assigned-to**: unassigned

---

## Context

Spec Module 9 (dependency half). This adds an optional `needle` extra that
pins `cactus-needle` to the version TASK-3624's decision record tested. It is
**not** added to `all`: a 121M on-device model runtime isn't a default
dependency. `LlamaCppDelegate` needs no extra (aiohttp is core).

This task is exclusive (`parallel: false`) because it edits the dependency
manifest and, through it, the lockfile.

If the decision record says **DROP**, cancel this task.

---

## Scope

- Add a `needle = ["cactus-needle==<version from decision.md>"]` extra with a short comment, placed after the `security` extra.
- Refresh the lockfile only if this repo tracks `uv.lock` for the package, and only as `uv lock` from the main checkout by the operator. Never run `uv sync` in a worktree.

**NOT in scope**: code changes; adding anything to `all`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/pyproject.toml` | MODIFY | `needle` extra |

---

## Codebase Contract (Anti-Hallucination)

### Existing Signatures to Use
```toml
# packages/ai-parrot/pyproject.toml
[project.optional-dependencies]      # line 209
security = [                         # line ~702 — its comment explains why llama-cpp-python is avoided
all = [                              # line 869 — line-anchored ^all = \[ ; do NOT add needle here
```

### Does NOT Exist
- ~~A `llamacpp` / `llama-cpp` extra~~: not needed. The backend is HTTP-only (design-research S10).
- ~~`cactus-needle` version~~: unknown until `decision.md`. Never guess it.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/pyproject.toml", "action": "MODIFY"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Read the tested `cactus-needle` version from `sdd/state/FEAT-590/spike/decision.md` — *why*: the pin must match what was measured.
2. Insert the extra — *why*: `NeedleDelegate`'s `ImportError` message names `ai-parrot[needle]` (TASK-3633).

### `packages/ai-parrot/pyproject.toml` (MODIFY)
```toml
# FILL IN: disambiguate — insert after the closing `]` of the `security = [` extra (quote its last 2 lines
#   when locating it; `security = [` occurs once: verify with grep -c '^security = \[' pyproject.toml)
# FEAT-590: Needle 3 on-device tool-call delegate backend (NeedleDelegate).
# Optional and NOT part of `all`; pinned to the version the FEAT-590 spike measured.
needle = [
    "cactus-needle==FILL-IN-FROM-decision.md",
]
```

### FILL IN checklist
- [ ] Version pin from `decision.md`
- [ ] The insertion point, verified unique

---

## Acceptance Criteria

- [ ] The `needle` extra exists, is pinned, and is absent from `all`
- [ ] `python -c "import tomllib;tomllib.load(open('packages/ai-parrot/pyproject.toml','rb'))"` succeeds

---

## Validation Commands

- `pytest packages/ai-parrot/tests/bots/flows/plan/test_plan.py -q`

> Manifest-only task: the real check is the `tomllib` parse in Acceptance Criteria; this is a smoke check
> that the plan package still imports after the dependency edit.

---

## Test Specification

None beyond the TOML parse check and the Needle unit tests still passing.

---

## Agent Instructions

Standard.

---

## Completion Note

*(Agent fills this in when done)*
