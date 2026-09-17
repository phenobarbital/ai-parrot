# TASK-3302: Gate — confirm FEAT-562 is merged and re-verify the Codebase Contract

**Feature**: FEAT-563 — Scoped Test Selection for the SDD Cycle
**Spec**: `sdd/specs/scoped-test-selection.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

FEAT-563 was decomposed **before** FEAT-562 (`ci-test-failures-root-cause-remediation`) merged
(user decision 2026-09-17: run `/sdd-task` now, with guards). FEAT-562 registers markers, adds
`pytest.importorskip` guards and changes CI selections, so spec §6 "Configuration References"
and the marker/conftest facts TASK-3316 builds on may be stale. This task is the **gate**:
it proves FEAT-562 is in `origin/dev` and records every drift in §6 so the orchestrator can
fold it into the spec before TASK-3316 (directory markers) starts. Spec risk **R11**,
Worktree Strategy "Cross-feature dependencies".

---

## Scope

- Verify FEAT-562 is merged into `origin/dev`. If it is **not**, write the log with
  `verdict: BLOCKED`, do **not** commit anything else, and report the attempt as failed — the
  task must stay pending.
- Re-verify, against the current feature branch (which is based on `origin/dev`), every item of
  spec §6 "Configuration References" and the marker/conftest anchors listed in the blueprint.
- Record each item as `unchanged` / `moved (old → new line)` / `changed (describe)` / `gone`.
- List every marker now registered in `pytest.ini` and in each `packages/<dist>/pyproject.toml`
  `[tool.pytest.ini_options]`, and every `pytest_collection_modifyitems` / `pytest_configure`
  hook in conftests (FEAT-562 may have added some).
- Write the result to `artifacts/logs/feat-563-contract-reverify.md`.

**NOT in scope**: editing the spec or anything under `sdd/` (forbidden for sdd-coder — the
orchestrator folds the log into spec §6); implementing markers (TASK-3316); CI changes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `artifacts/logs/feat-563-contract-reverify.md` | CREATE | Gate verdict + §6 drift report |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
# none — this task runs shell commands and writes a markdown log only
```

### Existing Signatures to Use
```text
# Anchors to re-verify (as recorded 2026-09-17, pre-FEAT-562)
pytest.ini                                         # 10 lines: asyncio_mode=auto; markers integration, live, real_llm, slow; filterwarnings ignore::DeprecationWarning
pyproject.toml:230                                 # [tool.pytest.ini_options] (shadowed by pytest.ini): --strict-config, --strict-markers, log_cli DEBUG, filterwarnings error
packages/ai-parrot/pyproject.toml:997              # [tool.pytest.ini_options]: asyncio_mode auto; markers real_llm, network, live
packages/ai-parrot-server/pyproject.toml:118       # [tool.pytest.ini_options]
packages/ai-parrot-integrations/pyproject.toml:143 # [tool.pytest.ini_options]
packages/parrot-formdesigner/pyproject.toml:93     # [tool.pytest.ini_options]
packages/ai-parrot/tests/conftest.py:15            # def pytest_collection_modifyitems(config, items):  # noqa: D401
packages/ai-parrot/tests/benchmarks/conftest.py:13 # def pytest_collection_modifyitems(config, items):
packages/ai-parrot-tools/tests/research/conftest.py:20      # def pytest_collection_modifyitems(config, items):
packages/ai-parrot-tools/tests/company_info/conftest.py:21  # def pytest_collection_modifyitems(config, items):
.github/workflows/ci.yml:147                       # run: uv run pytest tests/ -q --tb=short --ignore=tests/tools --continue-on-collection-errors
.gitignore:363-366                                 # .codex/* ; !.codex/ ; !.codex/agents/ ; !.codex/agents/*.toml
sdd/tasks/index/ci-test-failures-root-cause-remediation.json   # FEAT-562 index; "completed_at": null and TASK-3296..3301 at decomposition time
origin/feat-FEAT-562-ci-test-failures-root-cause-remediation   # FEAT-562 feature branch (remote)
```

### Does NOT Exist
- ~~an `e2e` marker~~ — not registered anywhere as of 2026-09-17 (record whether FEAT-562 added one)
- ~~directory-based auto-marking in any conftest~~ — none as of 2026-09-17
- ~~a script that checks "feature merged"~~ — use the git commands below; do not invent one
- ~~permission to edit `sdd/specs/*.spec.md`~~ — the fidelity gate rejects any `sdd/` change from a coder

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "artifacts/logs/feat-563-contract-reverify.md",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Pattern to Follow
Evidence logs under `artifacts/logs/` (e.g. `artifacts/logs/feat-566-ledger-core.log`): plain
text/markdown, commands and their verbatim output excerpts, then a verdict line.

### Key Constraints
- Git is the authority: never infer "merged" from task statuses in a non-`dev` branch.
- The verdict line must be machine-greppable: `verdict: PASS` or `verdict: BLOCKED`.
- Quote exact line numbers found **now**; do not copy the pre-FEAT-562 numbers without re-reading.

### References in Codebase
- `sdd/specs/scoped-test-selection.spec.md` §6 "Configuration References", §7 R11
- `sdd/specs/ci-test-failures-root-cause-remediation.spec.md` — what FEAT-562 intended to change

---

## Implementation Blueprint

### Steps (in order)
1. Run `git fetch origin dev` and the merge checks below — *why*: the gate is only meaningful against the remote integration branch.
2. If not merged, write the log with `verdict: BLOCKED`, commit only the log, and report failure — *why*: TASK-3316 depends on this task and must not start on stale marker facts.
3. Re-read every anchor in "Existing Signatures to Use" and fill the drift table — *why*: the orchestrator folds it into spec §6 (coders cannot edit `sdd/`).
4. Inventory markers and marker hooks with the grep commands — *why*: TASK-3316 must extend, not duplicate, FEAT-562 registrations.
5. Write `verdict: PASS` only when FEAT-562 is merged — *why*: drift alone does not block; it is data.

### `artifacts/logs/feat-563-contract-reverify.md` (CREATE)
```markdown
# FEAT-563 gate — FEAT-562 merge + Codebase Contract re-verification

Date: <FILL IN: YYYY-MM-DD>
Feature branch HEAD: <FILL IN: git rev-parse HEAD>
origin/dev: <FILL IN: git rev-parse origin/dev>

## 1. FEAT-562 merge status

    $ git fetch origin dev
    $ git merge-base --is-ancestor origin/feat-FEAT-562-ci-test-failures-root-cause-remediation origin/dev; echo $?
    <FILL IN: exit code; 0 = merged>
    $ git show origin/dev:sdd/tasks/index/ci-test-failures-root-cause-remediation.json | python3 -c "import json,sys;d=json.load(sys.stdin);print(d.get('completed_at'),[(t['id'],t['status']) for t in d['tasks']])"
    <FILL IN: output>

Merged: <FILL IN: yes | no>

## 2. Spec §6 anchor drift

| Anchor (as recorded) | Now | Status |
|---|---|---|
| pytest.ini (markers integration, live, real_llm, slow) | <FILL IN> | <unchanged/moved/changed/gone> |
| pyproject.toml:230 [tool.pytest.ini_options] | <FILL IN> | |
| packages/ai-parrot/pyproject.toml:997 | <FILL IN> | |
| packages/ai-parrot-server/pyproject.toml:118 | <FILL IN> | |
| packages/ai-parrot-integrations/pyproject.toml:143 | <FILL IN> | |
| packages/parrot-formdesigner/pyproject.toml:93 | <FILL IN> | |
| packages/ai-parrot/tests/conftest.py:15 | <FILL IN> | |
| packages/ai-parrot/tests/benchmarks/conftest.py:13 | <FILL IN> | |
| packages/ai-parrot-tools/tests/research/conftest.py:20 | <FILL IN> | |
| packages/ai-parrot-tools/tests/company_info/conftest.py:21 | <FILL IN> | |
| .github/workflows/ci.yml:147 | <FILL IN> | |
| .gitignore:363-366 | <FILL IN> | |

## 3. Marker inventory (post-FEAT-562)

    $ grep -n -A12 "^markers" pytest.ini
    $ grep -n -A15 "tool.pytest.ini_options" packages/*/pyproject.toml
    $ grep -rn "def pytest_collection_modifyitems\|def pytest_configure\|addinivalue_line" --include=conftest.py tests packages/*/tests conftest.py
    <FILL IN: condensed output>

## 4. Notes for the orchestrator (fold into spec §6 / TASK-3316)

- <FILL IN: each drift that changes a later task's assumptions>

verdict: <FILL IN: PASS | BLOCKED>
```
**Why this shape**: the verdict line is what the orchestrator greps; sections 2–3 give TASK-3316 and the spec
update exact post-FEAT-562 facts. Do not add sections that interpret FEAT-563 design — only facts.

### FILL IN checklist
- [ ] Merge status — exit code of `merge-base --is-ancestor` and FEAT-562 index state; bounded by R11
- [ ] Every anchor row — status from a fresh read; bounded by spec §6
- [ ] Marker inventory — full list of registered markers and marker hooks; bounded by TASK-3316's "extend, never duplicate"
- [ ] Verdict — `PASS` iff FEAT-562 merged

---

## Acceptance Criteria

- [ ] `artifacts/logs/feat-563-contract-reverify.md` exists with all four sections filled and a `verdict:` line
- [ ] `verdict: PASS` only if `git merge-base --is-ancestor origin/feat-FEAT-562-… origin/dev` exits 0 (or the FEAT-562 index on `origin/dev` has `completed_at` set)
- [ ] With `verdict: BLOCKED` the attempt is reported as failed (task stays pending)
- [ ] No file other than the log is changed; nothing under `sdd/` is touched
- [ ] Supports spec R11 and AC8 prerequisites

## Validation Commands

- `grep -E "^verdict: (PASS|BLOCKED)$" artifacts/logs/feat-563-contract-reverify.md`

---

## Test Specification

```bash
# No pytest module: the deliverable is evidence. Self-check before committing:
test -f artifacts/logs/feat-563-contract-reverify.md
grep -c "<FILL IN" artifacts/logs/feat-563-contract-reverify.md   # must print 0
grep -E "^verdict: (PASS|BLOCKED)$" artifacts/logs/feat-563-contract-reverify.md
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
5. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-3302-feat562-gate-contract-reverify.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
