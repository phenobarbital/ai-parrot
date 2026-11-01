# TASK-5101: Docs for the noun-grouped CLI + Validation Contract refresh

**Feature**: FEAT-633 — parrot-installer
**Spec**: `sdd/specs/parrot-installer.spec.md` (rev 0.8, amendment C26 item 7 — proposal rev 0.9)
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4095, TASK-5098, TASK-5099, TASK-5100
**Assigned-to**: unassigned

---

## Context

TASK-4095 documented `parrot sdd run <name>` in the canonical install guide and the global-runtime reference;
`docs/sdd/WORKFLOW.md` and `CLAUDE.md` (repo-only, exempt from the shipped-asset gates) still show the old
spellings and `scripts/sdd/launch_worker.sh`. C26 item 7: docs describe the noun tree, not the module list.
The spec's §4 Validation Contract must also name the new test files so the merge tier runs them.

---

## Scope

- Rewrite the `parrot sdd run` lines in `docs/getting-started.md` (:446), `docs/install/global-runtime.md`
  (:223, :231), `docs/sdd/WORKFLOW.md` (:63, :81, :88, :100) and the `launch_worker.sh` mentions in
  `CLAUDE.md` / `docs/sdd/*.md` to the noun/verb and `launch worker` spellings; add a short "`parrot sdd` command
  tree" section to `docs/install/global-runtime.md` (nouns, one line each, `ledger` as a second spelling of
  `wikitoolkit ledger`, `launch worker|brief|fix`).
- Add `packages/ai-parrot/tests/sdd/test_sdd_ledger_mount.py`, `packages/ai-parrot/tests/sdd/test_sdd_launch.py`
  and `tests/sdd_scripts/test_check_spec_consequences.py` to the spec's §4 Validation Contract and re-cache it into
  the per-spec index (clears the `test-contract-task-tests-uncovered` warnings of TASK-5096/5099/5100).

**NOT in scope**: any shipped asset (TASK-5098/5100); `sdd/WORKFLOW.md` (shipped — TASK-5098); the spec's
prose beyond the Validation Contract rows (C26 is already folded in at rev 0.8).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/getting-started.md` | MODIFY | :446 |
| `docs/install/global-runtime.md` | MODIFY | :223, :231 + command-tree section |
| `docs/sdd/WORKFLOW.md` | MODIFY | :63, :81, :88, :100 |
| `CLAUDE.md` | MODIFY | `launch_worker.sh` → `parrot sdd launch worker` (keep the tmux recipe) |
| `sdd/specs/parrot-installer.spec.md` | MODIFY | §4 Validation Contract rows |
| `sdd/tasks/index/parrot-installer.json` | MODIFY | re-cached `test_contract` |

---

## Codebase Contract (Anti-Hallucination)

> Verified on `feat-FEAT-633-parrot-installer` @ `54868dcb2d` (2026-11-01).

### Verified Imports
```python
# none — documentation task
```

### Existing Signatures to Use
```text
docs/getting-started.md:446        `parrot sdd run <name>` (for example `parrot sdd run reserve_ids --help`).
docs/install/global-runtime.md:223 parrot sdd run reserve_ids --kind task --count 1 --base-branch dev --label demo
docs/install/global-runtime.md:231 - Helpers run as `parrot sdd run <name>`, never `python -m ...`: …
docs/sdd/WORKFLOW.md:63            parrot sdd run ensure_worktree --slug <slug> --feature-id FEAT-<NNN> \
docs/sdd/WORKFLOW.md:81            `parrot sdd run select_tests --tier merge --base origin/<base_branch> --task-file <task.md> --run`.
docs/sdd/WORKFLOW.md:88            parrot sdd run close_task TASK-<NNN> <slug> verified   # or partial | forced
docs/sdd/WORKFLOW.md:100           `parrot sdd run reserve_ids --kind task|feature --count N --base-branch dev --label <slug>`.
CLAUDE.md — "Autonomous Agent (`sdd-worker`)" section: `scripts/sdd/launch_worker.sh --verbose` (two code blocks)
sdd/specs/parrot-installer.spec.md — §4 "### Validation Contract" (the `runners:` form, FEAT-709); index header test_contract schema 2 (runners[].targets)
python -m scripts.sdd.cache_test_contract --spec sdd/specs/parrot-installer.spec.md --index sdd/tasks/index/parrot-installer.json   # re-cache (exit 2 = malformed subsection)
VERBS table — packages/ai-parrot/src/parrot/sdd/cli.py (TASK-5095): the spelling source for every docs line
```

### Does NOT Exist
- ~~`parrot sdd run`~~, ~~`parrot devloop launch-worker`~~, ~~`parrot sdd launch-worker`~~ — never document them.
- ~~`docs/sdd/GUIDE.md` / `docs/sdd/PLATFORM.md` on this branch before TASK-5093~~ — they arrive with FEAT-768; include them if present after the merge (re-grep `launch_worker.sh`).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "docs/getting-started.md", "action": "MODIFY"},
    {"path": "docs/install/global-runtime.md", "action": "MODIFY"},
    {"path": "docs/sdd/WORKFLOW.md", "action": "MODIFY"},
    {"path": "CLAUDE.md", "action": "MODIFY"},
    {"path": "sdd/specs/parrot-installer.spec.md", "action": "MODIFY"},
    {"path": "sdd/tasks/index/parrot-installer.json", "action": "MODIFY"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

- Spellings come from `VERBS`: `ensure_worktree` → `worktree ensure`, `select_tests` → `tests select`,
  `close_task` → `task close`, `reserve_ids` → `ids reserve`. Do not invent a verb the table lacks.
- The command tree section is generated, not typed: run `parrot sdd --help` and each `parrot sdd <noun> --help`
  from the branch (`PYTHONPATH=packages/ai-parrot/src python -m parrot.cli sdd --help`) and paste the names.
- `CLAUDE.md` keeps its tmux recipe; only the command inside it changes (`parrot sdd launch worker FEAT-… --tmux`).
- `docs/sdd/WORKFLOW.md` is the always-loaded agent quick reference (`@docs/sdd/WORKFLOW.md` in `CLAUDE.md`), so
  keep its length and structure; replace the four lines in place.

---

## Implementation Blueprint

### Steps (in order)
1. Replace the eight documented lines — *why*: they are the ones `grep -rn "parrot sdd run" docs CLAUDE.md` finds.
2. Add the command-tree section to `docs/install/global-runtime.md` — *why*: C26 item 7, "the noun tree, not the module list".
3. Add the two test files to the spec's Validation Contract; re-cache — *why*: the merge tier must run them.

### `docs/install/global-runtime.md` (MODIFY)
```markdown
<!-- occurrences: 1 (verified: grep -c '^parrot sdd run reserve_ids --kind task --count 1' docs/install/global-runtime.md) -->
<!-- REPLACE :223 -->
parrot sdd ids reserve --kind task --count 1 --base-branch dev --label demo
<!-- REPLACE :231 -->
- Helpers run as `parrot sdd <noun> <verb>` (for example `parrot sdd ids reserve`), never `python -m ...`: …
<!-- FILL IN: new subsection "## The `parrot sdd` command tree" after the helpers bullet list — one line per noun,
     generated from `parrot sdd --help`; note `ledger` = second spelling of `wikitoolkit ledger`, `launch worker|brief|fix`. -->
```

### `sdd/specs/parrot-installer.spec.md` (MODIFY — §4 Validation Contract)
```markdown
<!-- FILL IN: locate the `### Validation Contract` subsection (runners: form) and append the two test files
     `packages/ai-parrot/tests/sdd/test_sdd_ledger_mount.py`, `packages/ai-parrot/tests/sdd/test_sdd_launch.py`
     to the pytest runner's targets; then run cache_test_contract (exit 0) — bounded by AC-3. -->
```

### FILL IN checklist
- [ ] command-tree section text from the real `--help` output; bounded by AC-2.
- [ ] Validation Contract rows + re-cache; bounded by AC-3.

---

## Acceptance Criteria
- [ ] AC-1 `grep -rn "parrot sdd run\|launch_worker.sh\|devloop launch-worker" docs CLAUDE.md README.md` returns nothing except the alias note in `scripts/sdd/launch_worker.sh` itself.
- [ ] AC-2 `docs/install/global-runtime.md` has the command-tree section and every noun/verb it names exists in `parrot sdd --help`.
- [ ] AC-3 `python -m scripts.sdd.cache_test_contract --spec sdd/specs/parrot-installer.spec.md --index sdd/tasks/index/parrot-installer.json` exits 0 and the index `test_contract` lists the two new test files.

---

## Validation Commands
- `pytest packages/ai-parrot/tests/sdd/test_no_repo_script_refs.py -q`
- `pytest packages/ai-parrot/tests/sdd/test_sdd_cli.py -q`

---

## Test Specification
```python
# No new test file: docs are checked by AC-1/AC-2 greps; the contract re-cache is checked by AC-3.
```

---

## Agent Instructions
- Work inside `.claude/worktrees/feat-FEAT-633-parrot-installer`; `PYTHONPATH=packages/ai-parrot/src`.
- Commit: `docs(parrot-installer): TASK-5101 — parrot sdd command tree + validation contract`.

---

## Completion Note
_(filled by the implementer)_
