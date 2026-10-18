# TASK-4434: `sdd-worker` runs a brief from inside its worktree

**Feature**: FEAT-698 — /sdd-brief One-Command Brief Flow for Hotfixes and Single-Issue Fixes
**Spec**: `sdd/specs/sdd-brief-hotfix-flow.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4425, TASK-4427, TASK-4431
**Assigned-to**: unassigned

---

## Context

Spec rev 0.2 — the user's requirement is that `sdd-worker`/`sdd-coder` work
in the brief worktree "as usual". The four `sdd-worker` prompt twins
hardcode `sdd/tasks/index/` (feature resolution §1, `--index` in §3,
`INDEX=` in §4.5 and the closure step, `TASK_FILES` jq) and close tasks with
`close_task.sh` (active → completed move). A brief differs in three ways:
its index is `sdd/briefs/<slug>.index.json` and exists **only inside the
worktree**; its worktree is provisioned with `--brief-key`; its tasks close
**in place** (no move). TASK-4431 already makes the MCP engine resolve
brief indexes, so `coder_plan("BRIEF-<KEY>", wt)` works once the prompt
points at the right index.

---

## Scope

In each of the four twins, add a **Brief lane (FEAT-698)** subsection right
after §1 "Resolve the Feature", and route the existing steps through it:

- **Detection**: §1 also considers `sdd/briefs/*.index.json`; a matching
  header with `"type": "brief"` selects the brief lane.
- **Must run inside the brief worktree**: `IN_WORKTREE=0` + brief ⇒ STOP:
  `⚠️  Briefs exist only inside their worktree: cd <worktree> and re-run sdd-worker.`
- **§3**: `python -m scripts.sdd.ensure_worktree --slug <feature> --brief-key <KEY> --base-branch <base_branch>`
  (KEY = `feature_id` minus the `BRIEF-` prefix) — reuses the current worktree.
- **§4.5 and closure**: `INDEX` is the brief index path; task files come from
  `tasks[].file`.
- **Closure**: no `close_task.sh`; flip the task's index entry to
  `"done"` + `completed_at`, fill the Completion Note in the task file **in
  place**, then `git add` the brief index + that task file.
- Feature-lane text stays byte-for-byte identical outside these insertions.
- Create `tests/sdd_scripts/test_sdd_worker_brief_contract.py`.

**NOT in scope**: `sdd-planner` / `sdd-autopilot` twins (briefs never go
through planning); `/sdd-done` (TASK-4435); engine code (TASK-4431).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.claude/agents/sdd-worker.md` | MODIFY | Brief lane subsection + routing |
| `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-worker.md` | MODIFY | byte-identical copy (may need `git add -f`) |
| `.agents/agents/sdd-worker/agent.md` | MODIFY | codex twin (FEAT-549 suite) |
| `.agent/agents/sdd-worker/agent.md` | MODIFY | codex twin (differs from `.agents/` — edit on its own terms) |
| `tests/sdd_scripts/test_sdd_worker_brief_contract.py` | CREATE | brief-lane guards |

---

## Codebase Contract (Anti-Hallucination)

### Existing Signatures to Use
- `.claude/agents/sdd-worker.md` (identical to `_subagent_data/sdd-worker.md` today):
  - §1 anchor (occurrences 1, line 189): ``Glob `sdd/tasks/index/*.json` (excluding `_orphans.json`) and find the``
  - §1 jq lookup over `sdd/tasks/index/*.json`: lines 198-205
  - §3 `ensure_worktree … --index "sdd/tasks/index/<feature-slug>.json"`: lines 230-237
  - `IN_WORKTREE=1` detection: line 157
  - §4.5 `INDEX="sdd/tasks/index/<feature-slug>.json"`: line 265
  - `TASK_FILES=$(jq -r '.tasks[].file' sdd/tasks/index/<feature-slug>.json)`: line 362
  - closure `scripts/sdd/close_task.sh TASK-<NNN> <feature-slug> verified`: line 566; `INDEX=`: line 559
- Codex twins: §1 anchor at `.agents/agents/sdd-worker/agent.md:138` and `.agent/agents/sdd-worker/agent.md:138`.
- `python -m scripts.sdd.ensure_worktree --slug <s> --brief-key <K> --base-branch <b>` — TASK-4427.
- Per-brief index header: `feature_id: "BRIEF-<KEY>"`, `type: "brief"`, `spec: sdd/briefs/<slug>.brief.md` — TASK-4425.

### Does NOT Exist
- ~~`close_task.sh` brief support~~ — briefs close in place.
- ~~`sdd/briefs/` in the primary checkout~~ — the brief lane never reads the main checkout.
- ~~a `--brief` flag on `sdd-worker`~~ — detection is by index header `type`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": ".claude/agents/sdd-worker.md", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-worker.md", "action": "MODIFY"},
    {"path": ".agents/agents/sdd-worker/agent.md", "action": "MODIFY"},
    {"path": ".agent/agents/sdd-worker/agent.md", "action": "MODIFY"},
    {"path": "tests/sdd_scripts/test_sdd_worker_brief_contract.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- **Insert, don't rewrite**: the feature lane is in heavy use; add one
  subsection plus one-line "brief lane: use `$INDEX`/see §1b" pointers at
  each hardcoded site. Do not reflow unrelated paragraphs.
- Claude twin → copy byte-for-byte to `_subagent_data/` (identical today).
- Codex twins differ from each other (auto-memory "two suites, FEAT-543 vs
  FEAT-549") — make the same semantic insertion in each without
  "harmonizing" their other differences.

---

## Implementation Blueprint

### Steps (in order)
1. Insert §1b into the Claude twin after §1 — *why*: one place describes the lane.
2. Add pointers at §3, §4.5, the TASK_FILES jq, and the closure step — *why*: each hardcoded site must defer to the lane.
3. Copy to `_subagent_data/`; apply to both codex twins — *why*: parity.
4. Write the contract test — *why*: AC-1..AC-4.

### `.claude/agents/sdd-worker.md` (MODIFY)
```markdown
# occurrences: 1 (verified: grep -c 'Glob `sdd/tasks/index/\*.json` (excluding `_orphans.json`) and find the' .claude/agents/sdd-worker.md)
# AFTER — insert as a new subsection after §1 ends (before `### 2. Never Write Task State on \`BASE_BRANCH\``)
### 1b. Brief Lane (FEAT-698)

Also consider `sdd/briefs/*.index.json` (after the feature indexes; a
feature index wins a tie). A match whose header has `"type": "brief"` is a
**brief**: it exists only inside its worktree.

- `IN_WORKTREE=0` ⇒ STOP: `⚠️  Briefs exist only inside their worktree: cd <worktree> and re-run sdd-worker.`
- §3 provisions with `--brief-key "${FEATURE_ID#BRIEF-}" --base-branch "<base_branch>"` instead of `--feature-id`/`--jira-key`.
- `INDEX` (§4.5, closure) is the matched `sdd/briefs/<slug>.index.json`; task files come from `tasks[].file`.
- Closure: NO `close_task.sh`. <!-- FILL IN: exact jq to set status "done" + completed_at for one id, the
     in-place Completion Note edit, and `git add "$INDEX" <task file>` -->
```
```markdown
# FILL IN: one-line pointer at each hardcoded site (lines 230-237, 265, 362, 559-571):
#          "Brief lane: see §1b." — do not change the feature-lane command text
```

### `tests/sdd_scripts/test_sdd_worker_brief_contract.py` (CREATE)
```python
"""sdd-worker twins carry the FEAT-698 brief lane — TASK-4434."""

from __future__ import annotations

from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_TWINS = (
    ".claude/agents/sdd-worker.md",
    "packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-worker.md",
    ".agents/agents/sdd-worker/agent.md",
    ".agent/agents/sdd-worker/agent.md",
)


@pytest.mark.parametrize("rel", _TWINS)
def test_twin_mentions_brief_index_and_brief_key(rel: str) -> None:
    text = (_ROOT / rel).read_text(encoding="utf-8")
    assert "sdd/briefs/" in text and "--brief-key" in text

# FILL IN: test_inside_worktree_refusal_text_present (AC-2)
# FILL IN: test_brief_lane_forbids_close_task — the §1b section says no close_task.sh (AC-3)
# FILL IN: test_claude_twin_matches_subagent_data_byte_for_byte (AC-4)
```

### FILL IN checklist
- [ ] §1b closure jq + in-place Completion Note
- [ ] pointers at every hardcoded site
- [ ] `_subagent_data` copy + both codex twins
- [ ] contract tests AC-2..AC-4

---

## Acceptance Criteria

- [ ] AC-1: every twin documents `sdd/briefs/*.index.json` discovery and `--brief-key` provisioning.
- [ ] AC-2: running a brief with `IN_WORKTREE=0` is a documented STOP with the exact message.
- [ ] AC-3: the brief lane closes tasks in place — `close_task.sh` is explicitly not used for briefs.
- [ ] AC-4: `.claude/agents/sdd-worker.md` and `_subagent_data/sdd-worker.md` are byte-identical.
- [ ] AC-5: feature-lane command text is unchanged (`git diff` shows only insertions plus pointer lines).

---

## Validation Commands

- `pytest tests/sdd_scripts/test_sdd_worker_brief_contract.py -q`
- `pytest tests/sdd_scripts/test_command_contracts.py -q`

---

## Test Specification

See the CREATE block above.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug sdd-brief-hotfix-flow --feature-id FEAT-698`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in
   `sdd/tasks/index/sdd-brief-hotfix-flow.json`
4. **Verify the Codebase Contract** before writing ANY code
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:`; never change a fixed signature or path
7. **Verify** all acceptance criteria — run the Validation Commands from the worktree root
8. **Commit the code** — stage only the files this task lists (`git add -f` for `_subagent_data/` if needed)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4434 sdd-brief-hotfix-flow verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
