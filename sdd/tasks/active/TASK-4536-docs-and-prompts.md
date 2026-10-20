# TASK-4536: Agent prompts and docs: `run_validation`, the gate and the same-seat repair

**Feature**: FEAT-709 — Language-agnostic validation runners and an engine-owned task-tier gate
**Spec**: `sdd/specs/language-agnostic-validation-runners.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4532, TASK-4534
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 10. Seats must be told to use `run_validation` and that a Bash runner command returns a
verdict; `sdd-worker` must know about `validation_failed` and repair; `/sdd-done` documents per-runner rows.
Both `sdd-coder.md` twins change together (memory "sdd-worker prompt: two suites").

---

## Scope

- Replace the Validation Commands bullet in both `sdd-coder.md` twins with: use `run_validation` (MCP) / your Bash runner command returns a JSON verdict; the engine re-runs validation after you commit; a red gate returns the task to you once with the verdict.
- `sdd-worker.md`: `validation_failed` outcome, repair semantics, `coder_run_validation(tier="task")` availability.
- `qa-runner.md`: non-pytest runners in the plan; `unknown` failures gate.
- `/sdd-done` §4.7: rows `<runner>:<distribution>`, `n/a` cache/baseline.
- New `docs/dev_loop/validation-runners.md` (runner config, TOML, verdict schema, tiers).
- New `tests/sdd_scripts/test_feat709_doc_contract.py` asserting the key phrases exist in each doc (pattern: test_feat699_doc_contract.py).

**NOT in scope**: Code.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.claude/agents/sdd-coder.md` | MODIFY | seat instructions |
| `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-coder.md` | MODIFY | twin |
| `.claude/agents/sdd-worker.md` | MODIFY | orchestrator |
| `.claude/agents/qa-runner.md` | MODIFY | QA |
| `.claude/commands/sdd-done.md` | MODIFY | closeout table |
| `.agent/workflows/sdd-done.md` | MODIFY | twin |
| `.agents/skills/sdd-done/SKILL.md` | MODIFY | twin |
| `docs/dev_loop/validation-runners.md` | CREATE | operator doc |
| `tests/sdd_scripts/test_feat709_doc_contract.py` | CREATE | doc contract test |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `cb3b32639` (2026-10-20). Re-run `grep -c` on every anchor before editing.

### Verified Imports
```python
# none (docs) — test reads files with pathlib
```

### Existing Signatures to Use
```python
# .claude/agents/sdd-coder.md:175 and packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-coder.md (same text):
#   "- Run exactly the commands listed under your task file's `## Validation Commands`. Do not run"
# .claude/agents/sdd-worker.md:383  coder_run_validation(feature, worktree, execution_id, task_ids=…, tier="merge",
# .claude/agents/qa-runner.md:46 "## Process"
# .claude/commands/sdd-done.md:245 "### 4.7. Test Report (FEAT-695)"
# tests/sdd_scripts/test_feat699_doc_contract.py — pattern to copy
```

### Does NOT Exist
- ~~MCP tools in the native sdd-coder tool list~~ — native stays `Read, Write, Edit, MultiEdit, Bash, Glob, Grep`

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": ".claude/agents/sdd-coder.md",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-coder.md",
      "action": "MODIFY"
    },
    {
      "path": ".claude/agents/sdd-worker.md",
      "action": "MODIFY"
    },
    {
      "path": ".claude/agents/qa-runner.md",
      "action": "MODIFY"
    },
    {
      "path": ".claude/commands/sdd-done.md",
      "action": "MODIFY"
    },
    {
      "path": ".agent/workflows/sdd-done.md",
      "action": "MODIFY"
    },
    {
      "path": ".agents/skills/sdd-done/SKILL.md",
      "action": "MODIFY"
    },
    {
      "path": "docs/dev_loop/validation-runners.md",
      "action": "CREATE"
    },
    {
      "path": "tests/sdd_scripts/test_feat709_doc_contract.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

- `.claude/` files need `git add -f`.

---

## Implementation Blueprint

> Write each block nearly verbatim, then complete every `# FILL IN:` marker. Signatures, names and paths here come from the spec's Interface Skeletons (§3) and are not renegotiable.

### Steps (in order)
1. Twins first, identical wording — *why*: two suites.
2. Orchestrator/QA/sdd-done — *why*: closeout.
3. Operator doc.
4. Doc contract test.

### `.claude/agents/sdd-coder.md` (MODIFY)
```markdown
# occurrences: 1 (verified: grep -c "^- Run exactly the commands listed under your task file's" .claude/agents/sdd-coder.md)
# REPLACE that bullet (lines 175-179) with:
- Validate with the `run_validation` tool when you have it (MCP seats). On a native seat, run your task's
  `## Validation Commands` with Bash: inside an attempt the harness turns a test command into a JSON
  **verdict** (counts, failing node ids, ≤30-line excerpts) — you never see raw test output, and a command
  with nothing scoped is blocked. Do not run a directory, `tests/` or a bare `pytest`/`vitest run`.
- After you commit, the engine re-runs your task's validation itself. If it is red, the task comes back to
  you ONCE in a fresh session with that verdict under `## Validation verdict`; fix exactly those failures.
```
**Why**: Same text in the `_subagent_data` twin.

### FILL IN checklist
- [ ] twin text
- [ ] sdd-worker paragraph
- [ ] qa-runner paragraph
- [ ] sdd-done rows
- [ ] operator doc
- [ ] doc contract test

---

## Acceptance Criteria

- [ ] Both twins carry identical new bullets.
- [ ] Doc contract test passes.
- [ ] `ruff check` clean on every touched `.py` file

## Validation Commands

- `pytest tests/sdd_scripts/test_feat709_doc_contract.py -q`

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
7. Close with `scripts/sdd/close_task.sh TASK-4536 language-agnostic-validation-runners verified`, then fill the Completion Note.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
