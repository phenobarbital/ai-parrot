# TASK-4442: `### Validation Contract` in the spec template and `/sdd-spec`

**Feature**: FEAT-699 — Tests Optimization in the SDD Flow (spec-declared Validation Contract)
**Spec**: `sdd/specs/tests-optimization-sdd-flow.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4440
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1 (authoring half), §5 AC1. Spec authors need a place to declare the integration tests that
gate their feature. The subsection format must be exactly what `parse_spec_contract()` (TASK-4440)
accepts, so this task's test parses the template's own example with the real parser.

---

## Scope

- Insert a `### Validation Contract` subsection into `sdd/templates/spec.md` §4, directly above
  `### Test Data / Fixtures`.
- Add a "Validation Contract hint" paragraph to `/sdd-spec` (`.claude/commands/sdd-spec.md`) directly above
  the `**E2E plan hint ...**` paragraph, and the IDENTICAL text to its twin `.agent/workflows/sdd-spec.md`
  (body parity is enforced by `tests/sdd_scripts/test_command_twin_parity.py`). Add a one-bullet mention in
  the codex skill `.agents/skills/sdd-spec/SKILL.md` next to its `Worktree Strategy` bullet.
- New contract test `tests/sdd_scripts/test_spec_validation_contract_template.py`.

**NOT in scope**: `/sdd-task` caching (TASK-4443), any kernel change.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `sdd/templates/spec.md` | MODIFY | New §4 subsection |
| `.claude/commands/sdd-spec.md` | MODIFY | Authoring hint |
| `.agent/workflows/sdd-spec.md` | MODIFY | Twin — identical hint |
| `.agents/skills/sdd-spec/SKILL.md` | MODIFY | One bullet |
| `tests/sdd_scripts/test_spec_validation_contract_template.py` | CREATE | Template parses with the kernel parser; both twins carry the hint |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# load the stdlib kernel by path (same idiom as scripts/sdd/select_tests.py:18-27)
import sys; from pathlib import Path
_KERNEL_PARENT = Path(__file__).resolve().parents[2] / "packages/ai-parrot/src/parrot/flows/dev_loop"
sys.path.insert(0, str(_KERNEL_PARENT)); import test_scope.contract as contract  # parse_spec_contract from TASK-4440
```

### Existing Signatures to Use
- `sdd/templates/spec.md:147` — `### Test Data / Fixtures` (occurrences: 1)
- `.claude/commands/sdd-spec.md` / `.agent/workflows/sdd-spec.md` — `**E2E plan hint (new section in spec, FEAT-581 — optional):**` (occurrences: 1 each)
- `.agents/skills/sdd-spec/SKILL.md:132` — `   - Worktree Strategy`
- `tests/sdd_scripts/test_e2e_spec_contract.py:40-41` — pattern for template/command contract tests

### Does NOT Exist
- ~~a `### Validation Contract` subsection anywhere in templates~~ — created here
- ~~`sdd/templates/` is freely addable~~ — `.gitignore` has a global `templates/` rule; `spec.md` is
  already tracked so a MODIFY is fine, but never create a new file there without `git add -f`

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "sdd/templates/spec.md", "action": "MODIFY"},
    {"path": ".claude/commands/sdd-spec.md", "action": "MODIFY"},
    {"path": ".agent/workflows/sdd-spec.md", "action": "MODIFY"},
    {"path": ".agents/skills/sdd-spec/SKILL.md", "action": "MODIFY"},
    {"path": "tests/sdd_scripts/test_spec_validation_contract_template.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Insert the template subsection — *why*: authors copy the template, so the format is taught there.
2. Insert the same hint paragraph in both sdd-spec twins — *why*: twin parity is a CI-run test.
3. Write the contract test — *why*: proves the template example is parseable by the real parser (AC1).

### `sdd/templates/spec.md` (MODIFY)
```markdown
<!-- occurrences: 1 (verified: grep -c '### Test Data / Fixtures' sdd/templates/spec.md) -->
<!-- BEFORE — insert above `### Test Data / Fixtures` (verified: spec.md:147) -->
### Validation Contract

> FEAT-699. Explicit pytest operands (repo-relative file or `file::node`) that gate this feature in ALL
> tiers — task, merge, feature (`/sdd-done`) and QA. When present it REPLACES the heuristic breadth
> (import impact, suite escalation); the nightly workflow covers everything else. Write
> `none — fallback` to opt out explicitly (bounded fallback: tasks' own tests + direct importers).
> Never list `real_llm` tests. `integration`/`e2e`-marked operands listed here DO run.
> `/sdd-task` caches this list into the per-spec index header (`test_contract`).

tests:
- packages/<dist>/tests/path/test_file.py
- packages/<dist>/tests/path/test_file.py::test_node
markers: none

```
**Why**: the `markers: none` form and the bullet grammar are what `parse_spec_contract` accepts; the
placeholder `<dist>` keeps the example generic — FILL IN: the test must substitute a real path before parsing.

### `.claude/commands/sdd-spec.md` and `.agent/workflows/sdd-spec.md` (MODIFY — identical text)
```markdown
<!-- occurrences: 1 per file (verified: grep -c '^\*\*E2E plan hint (new section in spec, FEAT-581 — optional):\*\*') -->
<!-- BEFORE — insert above that line, followed by a blank line -->
**Validation Contract hint (FEAT-699 — mandatory subsection, may be `none — fallback`):**
Fill §4 `### Validation Contract` with the integration tests that prove THIS feature works: start from the
§3 modules' existing test files and the §4 Integration Tests table, prefer files over node ids, never a
directory, never a `real_llm` test. It replaces heuristic test breadth in every tier, so under-declaring
narrows local coverage (the nightly workflow is the backstop). Write `none — fallback` only when no
existing test exercises the feature yet; the selector then uses its bounded fallback.

```

### `.agents/skills/sdd-spec/SKILL.md` (MODIFY)
```markdown
<!-- AFTER — insert below `   - Worktree Strategy` (verified: SKILL.md:132; occurrences: FILL IN grep -c) -->
   - `### Validation Contract` in §4 (FEAT-699): explicit pytest operands or `none — fallback`
```

### FILL IN checklist
- [ ] test: extract the template subsection, replace `<dist>` with `ai-parrot`, parse → 2 tests, no markers
- [ ] test: both sdd-spec twins contain `Validation Contract hint (FEAT-699`
- [ ] confirm `test_command_twin_parity.py::test_command_twin_parity[sdd-spec]` passes

---

## Acceptance Criteria

- [ ] Template subsection parses with `parse_spec_contract` (after `<dist>` substitution).
- [ ] Twin parity test passes for `sdd-spec`.
- [ ] `test_e2e_spec_contract.py` still passes (template structure intact).

---

## Validation Commands

- `pytest tests/sdd_scripts/test_spec_validation_contract_template.py -q`
- `pytest tests/sdd_scripts/test_command_twin_parity.py -q`
- `pytest tests/sdd_scripts/test_e2e_spec_contract.py -q`

---

## Test Specification

```python
# tests/sdd_scripts/test_spec_validation_contract_template.py
"""FEAT-699: the spec template's Validation Contract example is parseable and documented in both twins."""
# FILL IN: load kernel by path (see Verified Imports), cut the subsection from sdd/templates/spec.md,
#          substitute <dist>, assert parse_spec_contract(...) returns 2 tests and markers == ()
```

---

## Agent Instructions

Standard. Close with `scripts/sdd/close_task.sh TASK-4442 tests-optimization-sdd-flow verified`.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
