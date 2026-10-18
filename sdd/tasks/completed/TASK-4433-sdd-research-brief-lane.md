# TASK-4433: `sdd-research` bug runs scaffold through `/sdd-brief`

**Feature**: FEAT-698 — /sdd-brief One-Command Brief Flow for Hotfixes and Single-Issue Fixes
**Spec**: `sdd/specs/sdd-brief-hotfix-flow.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4429, TASK-4432
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5, Decision 6 (hard cut). The dev-loop research subagent
literally runs `/sdd-spec <slug> --type hotfix --base-branch main
--no-interview` for `kind == "bug"`. That invocation is being removed
(TASK-4436), so all four prompt twins must switch bug runs to `/sdd-brief`
and emit the new `index_path` field (TASK-4432) in their ResearchOutput.

Behavior that must be preserved: the Jira ticket is created **first**
(cardinal rule); the brief's `flow_type`/`base_branch` override precedence
(FEAT-466 TASK-2508) is unchanged — a `kind == "bug"` brief overridden to
`flow_type: "feature"` still goes down the **feature** path
(`/sdd-spec … --type feature`), untouched.

---

## Scope

In each of the four twins:

- Step 3 (bug path): replace the hotfix `/sdd-spec` line with
  `/sdd-brief <JIRA-KEY> --no-interview` — plus
  `--base-branch <brief.base_branch>` when the operator overrode it. Keep the
  feature line (`/sdd-spec <slug> --type feature --base-branch dev
  --no-interview`) exactly as it is.
- Step 4: bug runs skip `/sdd-task` (unchanged rule) — reword to "the brief
  already materialized its task files".
- Step 5: bug runs **skip** `ensure_worktree` — `/sdd-brief` provisioned the
  worktree; take `worktree_path` from its handoff output. (Re-running
  `--jira-key` would re-plan through `FlowMeta`, which rejects a non-main
  hotfix.)
- Output Contract, hotfix run: `spec_path` → `sdd/briefs/<slug>.brief.md`,
  add `"index_path": "sdd/briefs/<slug>.index.json"`; `feat_id` stays `""`;
  `branch_name`/`worktree_path` follow the brief naming
  (`hotfix-<KEY>-<slug>` on main, `fix-<KEY>-<slug>` on dev).
- Remove the remaining FEAT-466 "`type: hotfix`" prose that describes the
  old spec path; keep FEAT-466 references that are still true (no ids
  reserved for bugs).
- Create `tests/sdd_scripts/test_sdd_research_brief_contract.py`.

**NOT in scope**: the sdd-worker twins (TASK-4434); any Python change.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.claude/agents/sdd-research.md` | MODIFY | bug path → /sdd-brief |
| `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-research.md` | MODIFY | same (byte-identical twin; may need `git add -f`) |
| `.agents/agents/sdd-research/agent.md` | MODIFY | codex twin |
| `.agent/agents/sdd-research/agent.md` | MODIFY | codex twin |
| `tests/sdd_scripts/test_sdd_research_brief_contract.py` | CREATE | twin parity + no-hotfix-spec guards |

---

## Codebase Contract (Anti-Hallucination)

### Existing Signatures to Use
Anchors (all occurrences 1):
- `.claude/agents/sdd-research.md:75` and `_subagent_data/sdd-research.md:75`:
  `   /sdd-spec <slug> --type hotfix --base-branch main --no-interview       # kind == "bug"`
- `.agents/agents/sdd-research/agent.md:57` and `.agent/agents/sdd-research/agent.md:57`:
  `   /sdd-spec <slug> --type hotfix --base-branch main       # kind == "bug"`
  (the codex twins have no `--no-interview` on these lines)
- Claude twins: step 4 at lines 88-93, step 5 at lines 94-106, Output
  Contract hotfix JSON at lines 139-151.
- `tests/sdd_scripts/test_command_contracts.py::test_unattended_callers_pass_no_interview`
  (lines 67-75) requires every `/sdd-spec <slug>` line in the Claude twins to
  carry `--no-interview` — the remaining feature line still must.
- ResearchOutput field added by TASK-4432: `index_path` (alias `index`).

### Does NOT Exist
- ~~`/sdd-spec --type hotfix`~~ — being removed (TASK-4436); no twin may invoke it.
- ~~`/sdd-brief --type`~~ — `/sdd-brief` has no `--type` flag.
- ~~`ensure_worktree --brief` for research~~ — research never provisions a brief worktree; `/sdd-brief` does.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": ".claude/agents/sdd-research.md", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-research.md", "action": "MODIFY"},
    {"path": ".agents/agents/sdd-research/agent.md", "action": "MODIFY"},
    {"path": ".agent/agents/sdd-research/agent.md", "action": "MODIFY"},
    {"path": "tests/sdd_scripts/test_sdd_research_brief_contract.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- Edit the Claude twin, then copy it byte-for-byte to `_subagent_data/` (they
  are identical today: `diff` returns nothing). The two codex twins are
  condensed variants — apply the same semantic change to each.
- Keep `--no-interview` on every unattended invocation (FEAT-577).
- Auto-memory "sdd-worker prompt: two suites": files under `_subagent_data/`
  may be ignored by a broad rule — stage with `git add -f` if `git add` is a
  no-op, and confirm with `git ls-files`.

---

## Implementation Blueprint

### Steps (in order)
1. Edit `.claude/agents/sdd-research.md` steps 3–5 and the hotfix Output Contract — *why*: the Claude twin is the reference.
2. `cp` it over `_subagent_data/sdd-research.md` — *why*: those two must stay byte-identical.
3. Apply the same change to both codex twins — *why*: twin drift is the recurring failure mode.
4. Write the contract test — *why*: AC-1..AC-4.

### `.claude/agents/sdd-research.md` (MODIFY)
```markdown
# occurrences: 1 (verified: grep -c '/sdd-spec <slug> --type hotfix --base-branch main --no-interview       # kind == "bug"' .claude/agents/sdd-research.md)
# REPLACE line 75 with:
   /sdd-brief <JIRA-KEY> --no-interview                                    # kind == "bug" (FEAT-698)
# FILL IN: rewrite the surrounding prose (lines 78-87) so `kind == "bug"` → /sdd-brief (base main,
#          or the operator's --base-branch override) and the flow_type="feature" override keeps the
#          /sdd-spec --type feature line; steps 4/5 as in Scope; hotfix Output Contract adds index_path
```

### `tests/sdd_scripts/test_sdd_research_brief_contract.py` (CREATE)
```python
"""sdd-research twins scaffold bug runs through /sdd-brief — FEAT-698 / TASK-4433."""

from __future__ import annotations

from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_TWINS = (
    ".claude/agents/sdd-research.md",
    "packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-research.md",
    ".agents/agents/sdd-research/agent.md",
    ".agent/agents/sdd-research/agent.md",
)


def _read(rel: str) -> str:
    return (_ROOT / rel).read_text(encoding="utf-8")


@pytest.mark.parametrize("rel", _TWINS)
def test_no_hotfix_spec_invocation(rel: str) -> None:
    assert "--type hotfix" not in _read(rel)

# FILL IN: test_bug_path_invokes_sdd_brief_no_interview — every "/sdd-brief " invocation line has
#          --no-interview (AC-2)
# FILL IN: test_output_contract_carries_index_path (AC-3)
# FILL IN: test_claude_twin_matches_subagent_data_byte_for_byte (AC-4)
```

### FILL IN checklist
- [ ] Claude twin steps 3/4/5 + Output Contract
- [ ] `_subagent_data` copy
- [ ] both codex twins
- [ ] contract tests AC-2..AC-4

---

## Acceptance Criteria

- [ ] AC-1: no twin contains `--type hotfix`.
- [ ] AC-2: every `/sdd-brief` invocation in the twins carries `--no-interview`; the feature `/sdd-spec <slug> --type feature … --no-interview` line survives in the Claude twins.
- [ ] AC-3: the hotfix Output Contract JSON includes `index_path` and a `sdd/briefs/` `spec_path`.
- [ ] AC-4: `.claude/agents/sdd-research.md` and `_subagent_data/sdd-research.md` are byte-identical.
- [ ] AC-5: bug runs no longer call `ensure_worktree` themselves.
- [ ] `test_command_contracts.py` still passes.

---

## Validation Commands

- `pytest tests/sdd_scripts/test_sdd_research_brief_contract.py -q`
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
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4433 sdd-brief-hotfix-flow verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
