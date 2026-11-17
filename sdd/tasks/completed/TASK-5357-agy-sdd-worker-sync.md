# TASK-5357: Sync the Google `sdd-worker` agent with the Claude orchestrator (FEAT-549/584/698)

**Feature**: FEAT-847 — SDD Antigravity CLI (AGY) Operational Compatibility
**Spec**: `sdd/specs/sdd-agy-compatibility.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-5358
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5, items 3 and 6. `.agents/agents/sdd-worker/agent.md` (415 lines) predates the FEAT-549
orchestrator loop, the FEAT-584 execution optimizations and the FEAT-698 brief lane that
`.claude/agents/sdd-worker.md` (827 lines) carries. This task ports the Claude prompt to agy primitives.

**Spec correction — orchestrator tool names.** Spec §1 lists `coder_init_run`, `coder_next_wave`,
`coder_record_native`, `coder_run_wave`, `coder_finalize_task`. **None of these exist** (0 hits in
`.claude/agents/sdd-worker.md` and in `packages/ai-parrot/src/parrot/`). The real `parrot-sdd-coder` loop, as the
Claude prompt uses it, is `coder_begin_execution` → `coder_plan` → `coder_run_chunk` / `coder_prepare_native`
(native seat dispatched as a sub-agent) → `coder_wait` / `coder_bg_wait` → `coder_merge` → `coder_end_execution`,
plus `coder_status`, `coder_task_context`, `coder_record_native_observation`, `coder_record_feedback`,
`coder_record_review`, `coder_run_validation`, `coder_delivery_report`, `coder_suspend_model`, `coder_cleanup`.

---

## Scope

- Rewrite `.agents/agents/sdd-worker/agent.md` section by section from `.claude/agents/sdd-worker.md`:
  Shared environment policy, Cardinal rules, Input, Task-Scoped Mode, Startup (0–5, including **1b. Brief Lane
  (FEAT-698)**), **Orchestrator Loop (FEAT-549)**, **Execution optimization (FEAT-584)**, Per-delivery correction
  feedback, Fallback sequential loop (a–h incl. b2 delegated implementation), Completion, Structured Output
  Contract, STOP conditions.
- Apply the AGY adaptations (below), the fresh-shell rule and the approval semantics.
- Regenerate the packaged copy; add `packages/ai-parrot/tests/sdd/test_agy_worker_prompt.py`.

**NOT in scope**: the Claude prompt; `sdd-coder`/`code-reviewer` agent files (TASK-5355 ships them — this prompt
only names them); `docs/sdd/AGY.md` (TASK-5358).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.agents/agents/sdd-worker/agent.md` | MODIFY | full AGY port of the Claude orchestrator prompt |
| `packages/ai-parrot/src/parrot/sdd/_assets/agents/agents/sdd-worker/agent.md` | MODIFY | regenerated copy |
| `packages/ai-parrot/tests/sdd/test_agy_worker_prompt.py` | CREATE | structural tests for the port |

---

## Codebase Contract (Anti-Hallucination)

> Verified on `dev` @ `ae3b48c7f3` (2026-11-09).

### Verified Imports
```python
from pathlib import Path   # the test reads the repo and packaged files directly
```

### Existing Signatures to Use
```text
.claude/agents/sdd-worker.md (source, 827 lines): sections at lines 47 (Shared environment policy), 71 (Cardinal
  rules), 109 (Input), 117 (Task-Scoped Mode), 148 (Startup), 216 (1b. Brief Lane FEAT-698), 309 (Orchestrator Loop
  FEAT-549), 311 (Execution optimization FEAT-584), 454 (Per-delivery correction feedback), 503 (Fallback
  sequential loop), 525 (b2 delegated implementation), 624 (Completion), 783 (Structured Output Contract), 814 (STOP)
  Claude dispatch forms to translate: line 365 `Agent(subagent_type="sdd-coder", model=<prepared.model>, prompt=...)`,
  line 435 (same), line 671 `Agent(code-reviewer)`; frontmatter `tools:` line 26 (drop).
.agents/agents/sdd-worker/agent.md (target): frontmatter lines 1-8 (name: sdd-worker, subagent: true,
  mainAgent: true, model: inherit) — keep; H1 `# SDD Worker — Autonomous Feature Implementer` (line 10).
  Spec §6 quotes a different H1 (`… Implementation Agent`, line 9) — stale.
AGY sub-agent tools: invoke_subagent(TypeName, Role, Prompt, Model, Workspace); manage_subagents(Action="list"|"kill"|"kill_all")
```

### Does NOT Exist
- ~~`coder_init_run`, `coder_next_wave`, `coder_record_native`, `coder_run_wave`, `coder_finalize_task`~~ — spec §1 names; not real tools.
- ~~`Agent(...)`, `TaskStop`, `SendMessage`, `Monitor` in agy~~ — use `invoke_subagent` / `manage_subagents`; background work is checked reactively (`coder_bg_status` / `coder_wait`), not with a monitor.
- ~~`Model="haiku"` / `Model="sonnet"`~~ — map a prepared native model `haiku -> flash`, every other value `-> inherit`.
- ~~`subagent_type: "fork"`~~ — `TypeName="self"` only (never `research`).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": ".agents/agents/sdd-worker/agent.md", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/sdd/_assets/agents/agents/sdd-worker/agent.md", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/sdd/test_agy_worker_prompt.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### AGY adaptations (apply in every ported section)
- `Agent(subagent_type="sdd-coder", model=<m>, prompt=P)` → `invoke_subagent(TypeName="sdd-coder", Role="coder",
  Prompt=P, Model=<"flash" if m == "haiku" else "inherit">, Workspace=<absolute sub-worktree path>)`.
- `Agent(code-reviewer)` → `invoke_subagent(TypeName="code-reviewer", …, Model="inherit", Workspace=<feature worktree>)`.
- `TaskStop` → `manage_subagents(Action="kill")`; `Bash` → `run_command`; `Read`/`Write`/`Edit` → `view_file`/`write_file`/`edit_file`.
- Fresh shells: every multi-step command uses the absolute worktree path or `WT=<abs> && cd "$WT" && …` in one
  `run_command`; the sub-agent `Workspace` is that same absolute path.
- Approval: the worker runs headless under `--dangerously-skip-permissions` started by
  `parrot sdd launch worker <FEAT-ID> --host google`, which sets `PARROT_SDD_AGY_UNATTENDED=1`; a `deny` from the
  hook ends that call — report it, never work around it.
- Shipped asset: no `packages/`, `scripts/`, `PYTHONPATH=`, `CLAUDE.md`, branch literals or non-SDD ticket keys.

---

## Implementation Blueprint

### Steps (in order)
1. Keep the frontmatter (lines 1-8) and H1; replace the body with the ported sections, in the Claude order — *why*: spec M5 item 3.
2. Apply every AGY adaptation; grep the result for the forbidden names — *why*: AC item 4 and the Does-NOT-Exist list.
3. `python scripts/sdd/check_asset_sync.py --write --root .` — *why*: regenerate the packaged copy.
4. Write `test_agy_worker_prompt.py`.

### `.agents/agents/sdd-worker/agent.md` (MODIFY)
```markdown
<!-- occurrences: 1 (verified: grep -c '^# SDD Worker — Autonomous Feature Implementer' .agents/agents/sdd-worker/agent.md) — line 10 -->
<!-- Keep lines 1-10. Then, in this order: -->
## Antigravity runtime
<!-- FILL IN (new, short): tool mapping, fresh-shell rule, model mapping, unattended approval semantics — bounded by
     the AGY adaptations above; link `docs/sdd/AGY.md#antigravity-adaptation-contract` for details. -->
## Shared environment policy
## ⛔ CARDINAL RULES — NEVER VIOLATE THESE
## Input
## Task-Scoped Mode (FEAT-323)
## Startup Sequence            <!-- incl. "### 1b. Brief Lane (FEAT-698)" -->
## Orchestrator Loop (FEAT-549)
## Execution optimization (FEAT-584)
## Per-delivery correction feedback
## Fallback: Sequential Loop (no parrot-sdd-coder server)
## Completion
## Structured Output Contract (dispatched runs)
## STOP Conditions
<!-- FILL IN: each section ported from .claude/agents/sdd-worker.md (line numbers in the Codebase Contract) with
     the AGY adaptations — bounded by spec §3 M5 items 3 and 6. -->
```

### `packages/ai-parrot/tests/sdd/test_agy_worker_prompt.py` (CREATE)
```python
"""FEAT-847 M5 — the Google sdd-worker prompt carries the FEAT-549 loop in agy primitives."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
WORKER = REPO_ROOT / ".agents/agents/sdd-worker/agent.md"
PACKAGED = REPO_ROOT / "packages/ai-parrot/src/parrot/sdd/_assets/agents/agents/sdd-worker/agent.md"


@pytest.fixture(scope="module")
def text() -> str:
    return WORKER.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "needle",
    ["invoke_subagent", "manage_subagents", "coder_begin_execution", "coder_plan", "coder_run_chunk",
     "coder_prepare_native", "coder_merge", "coder_end_execution", "Brief Lane", "FEAT-584", 'Model="flash"'],
)
def test_worker_has_agy_orchestrator_loop(text: str, needle: str) -> None:
    assert needle in text


# FILL IN tests:
#  - forbidden: "Agent(", "TaskStop", "subagent_type", 'Model="haiku"', 'Model="sonnet"', "coder_init_run",
#    "coder_next_wave", "coder_run_wave", "coder_finalize_task", "--mode auto"
#  - every line containing "$WT" also contains "WT=" (fresh-shell rule)
#  - packaged copy is byte-identical to WORKER
```

### FILL IN checklist
- [ ] "Antigravity runtime" section; bounded by the AGY adaptations
- [ ] every ported section; bounded by spec §3 M5
- [ ] remaining tests

---

## Acceptance Criteria

- [ ] The Google worker prompt contains the FEAT-549 loop with real `coder_*` tool names, the FEAT-584 section and the FEAT-698 brief lane.
- [ ] It dispatches through `invoke_subagent` / `manage_subagents` with `haiku -> flash`, else `inherit`; no Claude-only primitive or non-existent tool name remains.
- [ ] All worktree commands are self-contained; `check_asset_sync.py --check` exits 0.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/sdd/test_agy_worker_prompt.py -q`
- `pytest tests/sdd_scripts/test_check_asset_sync.py -q`

---

## Test Specification

See `test_agy_worker_prompt.py` in the Implementation Blueprint.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug sdd-agy-compatibility --feature-id FEAT-847`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/sdd-agy-compatibility.json`
4. **Verify the Codebase Contract** before writing any code; fix stale entries first
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the Implementation Blueprint, completing every `# FILL IN:` marker
7. **Verify** all acceptance criteria — run the Validation Commands (prefix `PYTHONPATH=packages/ai-parrot/src` in a worktree)
8. **Commit the code** — stage only the files this task lists
9. **Close the task** with `parrot sdd task close TASK-5357 sdd-agy-compatibility verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

**Completed by**: sdd-worker orchestrator; seat qwen (nova), 1 attempt (salvaged)
**Date**: 2026-11-09
**Notes**: Google sdd-worker prompt ported to agy. Orchestrator review found the delivery incomplete (missing Fallback/Per-delivery sections, duplicated loop block, outdated Completion) and fixed it in 71f03387aa; feedback recorded. Merge-tier validation green (102 passed).

**Deviations from spec**: none
