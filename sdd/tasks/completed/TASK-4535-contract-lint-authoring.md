# TASK-4535: Registry-backed contract lint, schema-2 caching and the `runners:` authoring form

**Feature**: FEAT-709 — Language-agnostic validation runners and an engine-owned task-tier gate
**Spec**: `sdd/specs/language-agnostic-validation-runners.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4522
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 9 and codex S6 (one source of truth: the lint consumes the registry and contract loader
instead of duplicating pytest operand parsing) and S12 (extension adapters re-checked under isolated system Python).

---

## Scope

- `check_task_graph._check_test_contract`: load the registry from the repo root; findings `test-contract-unknown-runner`, `test-contract-tier-forbidden`, `test-contract-settings-invalid`, `test-contract-extension-invalid` (subprocess `python -I` import check), keep `-real-llm`, `-operand-missing`, `-task-tests-uncovered`; add warning `validation-command-unrecognised` for a task command no adapter matches; remove the local `_pytest_operands` duplicate.
- `cache_test_contract.py`: write schema 2 via `contract_to_header` (already) and accept both authoring forms.
- `sdd/templates/spec.md` `### Validation Contract`: document the `runners:` form beside the flat form.
- `/sdd-spec` and `/sdd-task` command docs + their `.agent/workflows/` and `.agents/skills/*/SKILL.md` twins: one paragraph each on runners, tiers and lift-on-read.

**NOT in scope**: Kernel contract code (TASK-4522).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `scripts/sdd/check_task_graph.py` | MODIFY | registry-backed lint |
| `scripts/sdd/cache_test_contract.py` | MODIFY | schema 2 + both forms |
| `sdd/templates/spec.md` | MODIFY | runners: form |
| `.claude/commands/sdd-spec.md` | MODIFY | contract hint |
| `.claude/commands/sdd-task.md` | MODIFY | cache step |
| `.agent/workflows/sdd-spec.md` | MODIFY | twin |
| `.agent/workflows/sdd-task.md` | MODIFY | twin |
| `.agents/skills/sdd-spec/SKILL.md` | MODIFY | twin |
| `.agents/skills/sdd-task/SKILL.md` | MODIFY | twin |
| `tests/sdd_scripts/test_check_task_graph.py` | MODIFY | new finding codes |
| `tests/sdd_scripts/test_cache_test_contract.py` | MODIFY | schema 2 |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `cb3b32639` (2026-10-20). Re-run `grep -c` on every anchor before editing.

### Verified Imports
```python
# scripts/sdd/check_task_graph.py loads the kernel by path via _load_contract() (line ~18-25 pattern in cache_test_contract.py)
```

### Existing Signatures to Use
```python
# scripts/sdd/check_task_graph.py
def _check_validation_contract(tasks, root, required) -> list[Finding]   # line 234 (FEAT-563 flag — leave untouched)
def _check_test_contract(data, root, tasks) -> list[Finding]             # line 309
# scripts/sdd/cache_test_contract.py
def _load_contract() -> ModuleType                                       # line 18
def main(argv=None) -> int                                               # line 45 — contract_to_header call :70
# sdd/templates/spec.md:147  ### Validation Contract  (flat tests:/markers: form at :156-159)
# .claude/commands/sdd-spec.md:541  **Validation Contract hint (FEAT-699 …)**
# .claude/commands/sdd-task.md:406  #### Cache the Validation Contract (FEAT-699, mandatory)
```

### Does NOT Exist
- ~~`_check_runner_contract`~~ — do not add a second function; extend `_check_test_contract`

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "scripts/sdd/check_task_graph.py",
      "action": "MODIFY"
    },
    {
      "path": "scripts/sdd/cache_test_contract.py",
      "action": "MODIFY"
    },
    {
      "path": "sdd/templates/spec.md",
      "action": "MODIFY"
    },
    {
      "path": ".claude/commands/sdd-spec.md",
      "action": "MODIFY"
    },
    {
      "path": ".claude/commands/sdd-task.md",
      "action": "MODIFY"
    },
    {
      "path": ".agent/workflows/sdd-spec.md",
      "action": "MODIFY"
    },
    {
      "path": ".agent/workflows/sdd-task.md",
      "action": "MODIFY"
    },
    {
      "path": ".agents/skills/sdd-spec/SKILL.md",
      "action": "MODIFY"
    },
    {
      "path": ".agents/skills/sdd-task/SKILL.md",
      "action": "MODIFY"
    },
    {
      "path": "tests/sdd_scripts/test_check_task_graph.py",
      "action": "MODIFY"
    },
    {
      "path": "tests/sdd_scripts/test_cache_test_contract.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:scripts/sdd/check_task_graph.py#_check_test_contract",
    "sym:scripts/sdd/cache_test_contract.py#main"
  ]
}
```

---

## Implementation Notes

- `.claude/` edits need `git add -f`; `.agents/` does not (memory FEAT-703 note).
- Keep the template's flat example valid — existing specs use it.

---

## Implementation Blueprint

> Write each block nearly verbatim, then complete every `# FILL IN:` marker. Signatures, names and paths here come from the spec's Interface Skeletons (§3) and are not renegotiable.

### Steps (in order)
1. Lint — *why*: S6/S12.
2. Cache script — *why*: schema 2.
3. Template + command docs + twins — *why*: authoring.
4. Tests.

### `sdd/templates/spec.md` (MODIFY)
```markdown
# occurrences: 1 (verified: grep -c '^### Validation Contract' sdd/templates/spec.md)
# AFTER the flat example (`markers: none`, spec.md:159), add:

Multi-runner form (FEAT-709) — use it when the feature has non-pytest tests:

runners:
- kind: pytest
  tests:
  - packages/<dist>/tests/path/test_file.py
  markers: none
- kind: vitest
  cwd: packages/ai-parrot-server/ui
  tests:
  - src/lib/path/file.test.ts
- kind: cargo
  crate: <crate dir or package>
- kind: parrot-e2e
  plan: sdd/state/FEAT-<NNN>/e2e-plan.md   # merge/feature tiers only — never task
```
**Why**: Both forms stay valid; the flat form lifts to one pytest runner.

### FILL IN checklist
- [ ] lint rules + isolated extension check
- [ ] remove duplicate `_pytest_operands`
- [ ] cache script both forms
- [ ] doc paragraphs ×6
- [ ] tests

---

## Acceptance Criteria

- [ ] Each new finding code fires on a crafted index.
- [ ] Existing FEAT-699 index lints clean.
- [ ] `cache_test_contract.py` writes schema 2 for both forms; `--check` stable.
- [ ] `ruff check` clean on every touched `.py` file

## Validation Commands

- `pytest tests/sdd_scripts/test_check_task_graph.py -q`
- `pytest tests/sdd_scripts/test_cache_test_contract.py -q`
- `pytest tests/sdd_scripts/test_feat699_doc_contract.py -q`

---

## Test Specification

Tests live in the files declared above; write the cases named in Acceptance Criteria. sdd_coder tests reuse the hermetic-root fixture in `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/conftest.py`.

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug language-agnostic-validation-runners --feature-id FEAT-709`), never on `dev`.
2. Every `Depends-on` task must be `done` in `sdd/tasks/index/language-agnostic-validation-runners.json`.
3. Verify the Codebase Contract first; fix stale entries in this file before coding.
4. Implement from the blueprint; complete every `FILL IN`; never change a fixed signature or path.
5. Run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
6. Stage only the files listed above (`git add -f` for `.claude/`, `.parrot/`, `artifacts/`).
7. Close with `scripts/sdd/close_task.sh TASK-4535 language-agnostic-validation-runners verified`, then fill the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (orchestrator); implemented by opus (native) after two empty deliveries from codex seats; engine merge read a stale attempt record so the branch was merged by hand after confirming the diff was exactly the 11 declared files
**Date**: 2026-10-20
**Notes**: Merge-tier validation: only 5 pre-existing bwrap failures + test_background_contract.py (owned by TASK-4530). Closed via close_task.sh.

**Deviations from spec**: none
