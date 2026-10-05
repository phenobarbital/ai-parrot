# TASK-4089: Rewrite SDD markdown to python -m parrot.sdd.scripts.<name>

**Feature**: FEAT-633 — Parrot Bootstrap Installer
**Spec**: `sdd/specs/parrot-installer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4070, TASK-4086, TASK-4087, TASK-4088
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6 moves the 18 doc-referenced SDD helpers into the core package as
`parrot.sdd.scripts.<name>` (TASK-4085 / TASK-4086 / TASK-4087 / TASK-4088) and requires that
**ALL markdown — installed AND monorepo — references the single form
`python -m parrot.sdd.scripts.<name>`**, otherwise the byte-equality sync between `.claude/`
and the packaged `_assets/` (TASK-4090) can never pass (spec §7 "Byte-equality sync vs path
rewrite"). An SDD flow installed into a foreign repository (TASK-4091) has no `scripts/sdd/`
directory, so every reference to the old repo-relative path is a broken instruction there.

This task performs that rewrite across every SDD markdown/agent asset (and the Codex TOML
agent), keeps every twin/copy byte-identical, updates the four existing contract tests that
pin the old string literally, and adds a regression test built on the spike-S5 scanner
(`parrot.sdd.audit`, TASK-4070) so no `repo-script` reference to a moved helper can come back.

The 18 moved helpers (spec §3 M6): `sdd_meta`, `id_ledger`, `reserve_ids`,
`check_id_collisions`, `ensure_worktree`, `finalize_task`, `check_task_state`,
`check_task_graph`, `worktree_status`, `close_task`, `heal_orphans`, `doc_taxonomy`,
`backfill_taxonomy`, `migrate_index`, `select_tests`, `insight`, `install_hooks`
(+ the package `__init__`) — plus `prune_intake`, which the coordinator added to TASK-4088's move
(`install_hooks`' rendered git hook runs `python -m scripts.sdd.prune_intake`). Verified on `6c4ca5482`:
no markdown/agent asset references `prune_intake`, so it adds 0 hits; it is still in the rewrite
script's and the regression test's name list so a future reference is caught.

---

## Scope

- Rewrite every reference to a moved helper in the 57 files listed below, using EXACTLY the
  substitution table in the Implementation Blueprint (applied by the one-off script, never by
  hand-editing individual occurrences).
- Keep every twin byte-identical: `.claude/agents/<n>.md` ↔
  `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/<n>.md` (sdd-autopilot,
  sdd-planner, sdd-research, sdd-worker), `.claude/agents/sdd-ideation.md` ↔
  `packages/ai-parrot/src/parrot/flows/dev_flow/_subagent_data/sdd-ideation.md`, and the
  `.claude/commands/` ↔ `.agent/workflows/` command twins (sdd-spec, sdd-task — frontmatter
  + one tolerated line excepted, see `tests/sdd_scripts/test_command_twin_parity.py`).
- Update the four existing tests that assert the OLD literal string in markdown.
- Create `packages/ai-parrot/tests/sdd/test_no_repo_script_refs.py`.

**NOT in scope**:
- References to NON-moved helpers stay untouched: `scripts.sdd.review_checkpoint`
  (`.claude/agents/sdd-worker.md:588,607` and its `_subagent_data` copy), `lint_new`,
  `token_audit`, `codex_hook` (`.codex/hooks.json:9`),
  `regen_core_paths`, `calibrate_rlimit_as`, `profile_execution`, `tag_yaml_fixtures`.
  The substitution table matches the 18 moved names only, by construction.
- Python sources that embed `scripts.sdd.*` strings
  (`parrot/flows/dev_loop/nodes/research.py`, `nodes/base.py`, `sdd_coder/checkpoint.py`,
  `sdd_coder/background.py`) and `.github/workflows/ci.yml` (`python -m
  scripts.sdd.check_id_collisions` / `check_task_state`) — they run inside the monorepo, where
  the `scripts/sdd/*.py` shims (TASK-4085..4088) keep them working.
- `backfill_taxonomy._SDD_TOOLING_RE` (`scripts/sdd/backfill_taxonomy.py:41`,
  `re.compile(r"scripts/sdd/|\.claude/commands/|sdd/templates/")`) — it is a taxonomy heuristic that
  classifies *changed file paths*, not a reference to a helper; it still correctly matches the repo's
  `scripts/sdd/` shims. Do NOT "fix" it ad hoc in this task (or when TASK-4088 moves the module).
- Other docs under `docs/` (7 files outside `docs/sdd/WORKFLOW.md` mention moved helpers) —
  not installed assets; leave for a follow-up.
- Tests that EXECUTE the helpers via the repo path (`tests/sdd/test_close_task_ledger.py`,
  `tests/sdd/test_ledger_lifecycle_acceptance.py`, `tests/sdd_scripts/test_*.py` importing
  `scripts.sdd.*`) — the shims keep them valid; owned by the move tasks.
- Packaging the assets into `_assets/` (TASK-4090) and the installer (TASK-4091).
- `AGENTS.md`, `.claude/skills/`, `.agent/rules/` and
  `packages/ai-parrot/src/parrot/flows/_rules_data/` were searched and contain **no**
  reference to a moved helper — nothing to change there.

---

## Files to Create / Modify

Enumerated on `dev` @ `6c4ca5482` with
`grep -rlE "scripts[./]sdd[./](<18 names>)\b"` over `.claude/commands/ .claude/agents/
.claude/rules/ .claude/skills/ .agent/ .agents/ .codex/ sdd/WORKFLOW.md docs/sdd/WORKFLOW.md
CLAUDE.md AGENTS.md sdd/templates/ packages/ai-parrot/src/parrot/flows/**/_subagent_data/
packages/ai-parrot/src/parrot/flows/_rules_data/` (187 occurrences in 57 files; dry run of the
blueprint script leaves 0 residuals and preserves every `_subagent_data` byte-parity pair).

| File | Action | Description |
|---|---|---|
| `.agent/agents/sdd-autopilot/agent.md` | MODIFY | Rewrite 1 line(s): select_tests |
| `.agent/agents/sdd-ideation/agent.md` | MODIFY | Rewrite 1 line(s): sdd_meta |
| `.agent/agents/sdd-worker/agent.md` | MODIFY | Rewrite 6 line(s): close_task,ensure_worktree,finalize_task,sdd_meta,select_tests |
| `.agents/agents/sdd-ideation/agent.md` | MODIFY | Rewrite 1 line(s): sdd_meta |
| `.agents/agents/sdd-worker/agent.md` | MODIFY | Rewrite 4 line(s): close_task,ensure_worktree,sdd_meta |
| `.agent/skills/worktree-management/SKILL.md` | MODIFY | Rewrite 3 line(s): ensure_worktree,sdd_meta |
| `.agents/skills/sdd-brainstorm/SKILL.md` | MODIFY | Rewrite 1 line(s): sdd_meta |
| `.agents/skills/sdd-done/SKILL.md` | MODIFY | Rewrite 6 line(s): close_task,heal_orphans,sdd_meta,select_tests |
| `.agents/skills/sdd-fix/SKILL.md` | MODIFY | Rewrite 2 line(s): ensure_worktree,reserve_ids |
| `.agents/skills/sdd-fromjira/SKILL.md` | MODIFY | Rewrite 1 line(s): sdd_meta |
| `.agents/skills/sdd-insight/SKILL.md` | MODIFY | Rewrite 4 line(s): insight |
| `.agents/skills/sdd-next/SKILL.md` | MODIFY | Rewrite 2 line(s): doc_taxonomy,worktree_status |
| `.agents/skills/sdd-proposal/SKILL.md` | MODIFY | Rewrite 1 line(s): sdd_meta |
| `.agents/skills/sdd-spec/SKILL.md` | MODIFY | Rewrite 4 line(s): reserve_ids,sdd_meta |
| `.agents/skills/sdd-start/SKILL.md` | MODIFY | Rewrite 6 line(s): ensure_worktree,finalize_task |
| `.agents/skills/sdd-status/SKILL.md` | MODIFY | Rewrite 4 line(s): doc_taxonomy,worktree_status |
| `.agents/skills/sdd-task/SKILL.md` | MODIFY | Rewrite 6 line(s): check_task_graph,reserve_ids,sdd_meta |
| `.agent/workflows/sdd-brainstorm.md` | MODIFY | Rewrite 1 line(s): sdd_meta |
| `.agent/workflows/sdd-done.md` | MODIFY | Rewrite 8 line(s): check_task_state,close_task,heal_orphans,sdd_meta,select_tests |
| `.agent/workflows/sdd-fix.md` | MODIFY | Rewrite 2 line(s): ensure_worktree,reserve_ids |
| `.agent/workflows/sdd-insight.md` | MODIFY | Rewrite 3 line(s): insight |
| `.agent/workflows/sdd-next.md` | MODIFY | Rewrite 1 line(s): doc_taxonomy |
| `.agent/workflows/sdd-proposal.md` | MODIFY | Rewrite 1 line(s): sdd_meta |
| `.agent/workflows/sdd-spec.md` | MODIFY | Rewrite 7 line(s): reserve_ids,sdd_meta |
| `.agent/workflows/sdd-start.md` | MODIFY | Rewrite 5 line(s): close_task,ensure_worktree,finalize_task,sdd_meta |
| `.agent/workflows/sdd-status.md` | MODIFY | Rewrite 4 line(s): doc_taxonomy,worktree_status |
| `.agent/workflows/sdd-task.md` | MODIFY | Rewrite 5 line(s): check_task_graph,reserve_ids,sdd_meta |
| `.agent/workflows/sdd-tojira.md` | MODIFY | Rewrite 1 line(s): sdd_meta |
| `.claude/agents/qa-runner.md` | MODIFY | Rewrite 1 line(s): select_tests |
| `.claude/agents/sdd-autopilot.md` | MODIFY | Rewrite 2 line(s): ensure_worktree,select_tests |
| `.claude/agents/sdd-ideation.md` | MODIFY | Rewrite 1 line(s): sdd_meta |
| `.claude/agents/sdd-planner.md` | MODIFY | Rewrite 2 line(s): ensure_worktree,sdd_meta |
| `.claude/agents/sdd-research.md` | MODIFY | Rewrite 3 line(s): ensure_worktree,sdd_meta |
| `.claude/agents/sdd-worker.md` | MODIFY | Rewrite 6 line(s): close_task,ensure_worktree,finalize_task,sdd_meta,select_tests |
| `.claude/commands/sdd-brainstorm.md` | MODIFY | Rewrite 1 line(s): sdd_meta |
| `.claude/commands/sdd-done.md` | MODIFY | Rewrite 8 line(s): check_task_state,close_task,heal_orphans,sdd_meta,select_tests |
| `.claude/commands/sdd-fix.md` | MODIFY | Rewrite 2 line(s): ensure_worktree,reserve_ids |
| `.claude/commands/sdd-insight.md` | MODIFY | Rewrite 3 line(s): insight |
| `.claude/commands/sdd-next.md` | MODIFY | Rewrite 2 line(s): doc_taxonomy,worktree_status |
| `.claude/commands/sdd-proposal.md` | MODIFY | Rewrite 1 line(s): sdd_meta |
| `.claude/commands/sdd-spec.md` | MODIFY | Rewrite 7 line(s): reserve_ids,sdd_meta |
| `.claude/commands/sdd-start.md` | MODIFY | Rewrite 5 line(s): close_task,ensure_worktree,finalize_task,sdd_meta |
| `.claude/commands/sdd-status.md` | MODIFY | Rewrite 4 line(s): doc_taxonomy,worktree_status |
| `.claude/commands/sdd-task.md` | MODIFY | Rewrite 5 line(s): check_task_graph,reserve_ids,sdd_meta |
| `.claude/commands/sdd-tojira.md` | MODIFY | Rewrite 1 line(s): sdd_meta |
| `CLAUDE.md` | MODIFY | Rewrite 3 line(s): ensure_worktree,migrate_index,reserve_ids |
| `.claude/rules/worktree-management.md` | MODIFY | Rewrite 3 line(s): ensure_worktree,sdd_meta |
| `.codex/agents/sdd-worker.toml` | MODIFY | Rewrite 3 line(s): finalize_task,sdd_meta |
| `docs/sdd/WORKFLOW.md` | MODIFY | Rewrite 4 line(s): close_task,ensure_worktree,reserve_ids,select_tests |
| `packages/ai-parrot/src/parrot/flows/dev_flow/_subagent_data/sdd-ideation.md` | MODIFY | Rewrite 1 line(s): sdd_meta (twin of `.claude/agents/sdd-ideation.md`) |
| `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-autopilot.md` | MODIFY | Rewrite 2 line(s): ensure_worktree,select_tests (twin) |
| `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-planner.md` | MODIFY | Rewrite 2 line(s): ensure_worktree,sdd_meta (twin) |
| `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-research.md` | MODIFY | Rewrite 3 line(s): ensure_worktree,sdd_meta (twin) |
| `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-worker.md` | MODIFY | Rewrite 6 line(s): close_task,ensure_worktree,finalize_task,sdd_meta,select_tests (twin) |
| `sdd/templates/intake.procedure.md` | MODIFY | Rewrite 1 line(s): reserve_ids |
| `sdd/templates/task.md` | MODIFY | Rewrite 2 line(s): close_task,ensure_worktree |
| `sdd/WORKFLOW.md` | MODIFY | Rewrite 12 line(s): backfill_taxonomy,check_id_collisions,close_task,doc_taxonomy,ensure_worktree,id_ledger,install_hooks,migrate_index,reserve_ids |
| `tests/sdd_scripts/test_command_contracts.py` | MODIFY | `ensure_worktree` contract asserts the new module path |
| `tests/sdd/test_codex_sdd_sync.py` | MODIFY | Codex worker TOML asserts `parrot.sdd.scripts.finalize_task` |
| `packages/ai-parrot/tests/flows/dev_loop/test_worker_prompt_orchestrator.py` | MODIFY | Orchestrator-loop assert uses `python -m parrot.sdd.scripts.finalize_task` |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_start_optimization_contract.py` | MODIFY | Closure-block markers: new finalize_task / close_task module form |
| `packages/ai-parrot/tests/sdd/test_no_repo_script_refs.py` | CREATE | Regression: zero `repo-script` findings for the 18 moved names across the asset set |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
from __future__ import annotations
from pathlib import Path          # stdlib
import pytest                     # test dependency (used by every file under tests/)
# Created by TASK-4070 (does not exist yet on dev — verify the exact names in
# packages/ai-parrot/src/parrot/sdd/audit.py before use):
from parrot.sdd.audit import AssumptionFinding, scan_paths   # AssumptionFinding(path, line, kind, snippet); kind "repo-script"
# Created by TASK-4085..4088 — every rewritten reference must resolve:
#   python -m parrot.sdd.scripts.<name>   for each of the 18 moved names
```

### Existing Signatures to Use
```python
# tests/sdd_scripts/test_command_contracts.py
_CREATORS: dict[str, bool] = {...}                              # line 23 (6 command/agent files)
def test_no_command_hand_rolls_a_worktree(rel: str) -> None:    # line 43; message line 46 names the CLI
def test_every_creator_calls_ensure_worktree(rel: str) -> None: # line 51; `assert "scripts.sdd.ensure_worktree" in _read(` line 53
#   module docstring line 7 also names `scripts.sdd.ensure_worktree`; grep -c 'scripts.sdd.ensure_worktree' == 4

# tests/sdd/test_codex_sdd_sync.py
def test_worker_uses_deterministic_finalization_and_scoped_force_add() -> None:  # line 27
#   assert "scripts.sdd.finalize_task" in worker                                   # line 33 (reads .codex/agents/sdd-worker.toml)

# packages/ai-parrot/tests/flows/dev_loop/test_worker_prompt_orchestrator.py
def test_worker_prompt_uses_finalize_task_not_manual_jq_close_in_orchestrator_loop():  # line 208
#   docstring line 210 names `scripts.sdd.finalize_task`; assert line 214

# packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_start_optimization_contract.py
_MARKDOWN_TWINS = (...)                                        # line 12 (.claude/commands/sdd-start.md,
                                                               #   .agent/workflows/sdd-start.md,
                                                               #   .agents/skills/sdd-start/SKILL.md,
                                                               #   .agent/agents/sdd-worker/agent.md)
def test_start_twins_preserve_semantic_gates(tmp_path: Path) -> None:  # line 30
#   marker "python -m scripts.sdd.finalize_task",              # line 43
#   assert "close_task.sh" in body, ...                         # line 59 (comment line 51)

# Twin-parity tests that MUST stay green after the rewrite (read-only for this task):
# tests/sdd_scripts/test_command_twin_parity.py::test_command_twin_parity     line 64 (sdd-spec, sdd-task)
# packages/ai-parrot/tests/flows/dev_loop/test_subagent_parity.py::test_prompt_parity  line 44
# packages/ai-parrot/tests/flows/dev_flow/test_subagent_defs.py::test_prompt_parity_with_repo_twin  line 260
# tests/sdd/test_ledger_workflow_twins.py  — asserts "reserve_ids"/"ensure_worktree" substrings (lines 172, 250-251):
#   still satisfied by the new form (substring of parrot.sdd.scripts.reserve_ids)
```

### Does NOT Exist
- ~~`parrot.sdd`, `parrot.sdd.audit`, `parrot.sdd.scripts`~~ on `dev` today — created by
  TASK-4070 / TASK-4085..4088 (this task's dependencies). Do not start before they are `done`.
- ~~a sync/regeneration script for `_subagent_data/` or `_rules_data/`~~ — twins are kept
  byte-identical by hand + parity tests only; apply the same rewrite to both copies.
- ~~`scripts/sdd/close_task.py` / `heal_orphans.py` in the repo~~ — the Python ports are
  `parrot.sdd.scripts.close_task` / `.heal_orphans` (TASK-4087); `scripts/sdd/*.sh` remain as
  wrappers. Markdown must call the module, never the `.sh`.
- ~~any reference to moved helpers in `AGENTS.md`, `.claude/skills/`, `.agent/rules/`,
  `flows/_rules_data/`~~ — verified zero hits; do not touch them.
- ~~`parrot.sdd.scripts.review_checkpoint` / `lint_new` / `token_audit`~~ — NOT moved; never
  rewrite those references.

---

## Complexity Contract

> **MANDATORY.** Declares the measurable targets and contract symbols used for
> deterministic complexity routing (FEAT-561) before any coder is dispatched.
> This is a declaration, not a hand-authored score — the evaluator computes
> classification from measured evidence, never from this section's prose.

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": ".agent/agents/sdd-autopilot/agent.md",
      "action": "MODIFY"
    },
    {
      "path": ".agent/agents/sdd-ideation/agent.md",
      "action": "MODIFY"
    },
    {
      "path": ".agent/agents/sdd-worker/agent.md",
      "action": "MODIFY"
    },
    {
      "path": ".agents/agents/sdd-ideation/agent.md",
      "action": "MODIFY"
    },
    {
      "path": ".agents/agents/sdd-worker/agent.md",
      "action": "MODIFY"
    },
    {
      "path": ".agent/skills/worktree-management/SKILL.md",
      "action": "MODIFY"
    },
    {
      "path": ".agents/skills/sdd-brainstorm/SKILL.md",
      "action": "MODIFY"
    },
    {
      "path": ".agents/skills/sdd-done/SKILL.md",
      "action": "MODIFY"
    },
    {
      "path": ".agents/skills/sdd-fix/SKILL.md",
      "action": "MODIFY"
    },
    {
      "path": ".agents/skills/sdd-fromjira/SKILL.md",
      "action": "MODIFY"
    },
    {
      "path": ".agents/skills/sdd-insight/SKILL.md",
      "action": "MODIFY"
    },
    {
      "path": ".agents/skills/sdd-next/SKILL.md",
      "action": "MODIFY"
    },
    {
      "path": ".agents/skills/sdd-proposal/SKILL.md",
      "action": "MODIFY"
    },
    {
      "path": ".agents/skills/sdd-spec/SKILL.md",
      "action": "MODIFY"
    },
    {
      "path": ".agents/skills/sdd-start/SKILL.md",
      "action": "MODIFY"
    },
    {
      "path": ".agents/skills/sdd-status/SKILL.md",
      "action": "MODIFY"
    },
    {
      "path": ".agents/skills/sdd-task/SKILL.md",
      "action": "MODIFY"
    },
    {
      "path": ".agent/workflows/sdd-brainstorm.md",
      "action": "MODIFY"
    },
    {
      "path": ".agent/workflows/sdd-done.md",
      "action": "MODIFY"
    },
    {
      "path": ".agent/workflows/sdd-fix.md",
      "action": "MODIFY"
    },
    {
      "path": ".agent/workflows/sdd-insight.md",
      "action": "MODIFY"
    },
    {
      "path": ".agent/workflows/sdd-next.md",
      "action": "MODIFY"
    },
    {
      "path": ".agent/workflows/sdd-proposal.md",
      "action": "MODIFY"
    },
    {
      "path": ".agent/workflows/sdd-spec.md",
      "action": "MODIFY"
    },
    {
      "path": ".agent/workflows/sdd-start.md",
      "action": "MODIFY"
    },
    {
      "path": ".agent/workflows/sdd-status.md",
      "action": "MODIFY"
    },
    {
      "path": ".agent/workflows/sdd-task.md",
      "action": "MODIFY"
    },
    {
      "path": ".agent/workflows/sdd-tojira.md",
      "action": "MODIFY"
    },
    {
      "path": ".claude/agents/qa-runner.md",
      "action": "MODIFY"
    },
    {
      "path": ".claude/agents/sdd-autopilot.md",
      "action": "MODIFY"
    },
    {
      "path": ".claude/agents/sdd-ideation.md",
      "action": "MODIFY"
    },
    {
      "path": ".claude/agents/sdd-planner.md",
      "action": "MODIFY"
    },
    {
      "path": ".claude/agents/sdd-research.md",
      "action": "MODIFY"
    },
    {
      "path": ".claude/agents/sdd-worker.md",
      "action": "MODIFY"
    },
    {
      "path": ".claude/commands/sdd-brainstorm.md",
      "action": "MODIFY"
    },
    {
      "path": ".claude/commands/sdd-done.md",
      "action": "MODIFY"
    },
    {
      "path": ".claude/commands/sdd-fix.md",
      "action": "MODIFY"
    },
    {
      "path": ".claude/commands/sdd-insight.md",
      "action": "MODIFY"
    },
    {
      "path": ".claude/commands/sdd-next.md",
      "action": "MODIFY"
    },
    {
      "path": ".claude/commands/sdd-proposal.md",
      "action": "MODIFY"
    },
    {
      "path": ".claude/commands/sdd-spec.md",
      "action": "MODIFY"
    },
    {
      "path": ".claude/commands/sdd-start.md",
      "action": "MODIFY"
    },
    {
      "path": ".claude/commands/sdd-status.md",
      "action": "MODIFY"
    },
    {
      "path": ".claude/commands/sdd-task.md",
      "action": "MODIFY"
    },
    {
      "path": ".claude/commands/sdd-tojira.md",
      "action": "MODIFY"
    },
    {
      "path": "CLAUDE.md",
      "action": "MODIFY"
    },
    {
      "path": ".claude/rules/worktree-management.md",
      "action": "MODIFY"
    },
    {
      "path": ".codex/agents/sdd-worker.toml",
      "action": "MODIFY"
    },
    {
      "path": "docs/sdd/WORKFLOW.md",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_flow/_subagent_data/sdd-ideation.md",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-autopilot.md",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-planner.md",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-research.md",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-worker.md",
      "action": "MODIFY"
    },
    {
      "path": "sdd/templates/intake.procedure.md",
      "action": "MODIFY"
    },
    {
      "path": "sdd/templates/task.md",
      "action": "MODIFY"
    },
    {
      "path": "sdd/WORKFLOW.md",
      "action": "MODIFY"
    },
    {
      "path": "tests/sdd_scripts/test_command_contracts.py",
      "action": "MODIFY"
    },
    {
      "path": "tests/sdd/test_codex_sdd_sync.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/test_worker_prompt_orchestrator.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_start_optimization_contract.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/sdd/test_no_repo_script_refs.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:tests/sdd_scripts/test_command_contracts.py#test_no_command_hand_rolls_a_worktree",
    "sym:tests/sdd_scripts/test_command_contracts.py#test_every_creator_calls_ensure_worktree",
    "sym:tests/sdd/test_codex_sdd_sync.py#test_worker_uses_deterministic_finalization_and_scoped_force_add",
    "sym:packages/ai-parrot/tests/flows/dev_loop/test_worker_prompt_orchestrator.py#test_worker_prompt_uses_finalize_task_not_manual_jq_close_in_orchestrator_loop",
    "sym:packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_start_optimization_contract.py#test_start_twins_preserve_semantic_gates",
    "sym:tests/sdd_scripts/test_command_twin_parity.py#test_command_twin_parity",
    "sym:packages/ai-parrot/tests/flows/dev_loop/test_subagent_parity.py#test_prompt_parity",
    "sym:packages/ai-parrot/tests/flows/dev_flow/test_subagent_defs.py#test_prompt_parity_with_repo_twin"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
The FEAT-553 twin discipline: one source text, copies kept byte-identical and pinned by
parity tests (`packages/ai-parrot/tests/flows/dev_loop/test_subagent_parity.py`,
`test_rules_parity.py`). A deterministic, idempotent substitution applied to the whole file
list preserves parity automatically — never hand-edit one side.

### Key Constraints
- The rewrite is **mechanical and idempotent**: re-running the script must report
  `total=0 residual=0`.
- `close_task.sh` / `heal_orphans.sh` invocations become `python -m parrot.sdd.scripts.close_task`
  / `.heal_orphans` with the **same positional arguments** (TASK-4087 preserves the `.sh` CLI:
  `<TASK-ID> <feature-slug> <verified|partial|forced>` and `<feature-slug>`). Verify against
  `parrot/sdd/scripts/close_task.py` before running; if TASK-4087 changed the argv, STOP and report.
- Interpreter tokens are preserved (`python3 scripts/sdd/insight.py` →
  `python3 -m parrot.sdd.scripts.insight`); `bash ` prefixes are dropped.
- Never match across a newline (a fenced ```` ```bash ```` line followed by
  `scripts/sdd/heal_orphans.sh` must not become ```` ```python -m … ````) — the regexes use
  `[ \t]+`, not `\s+`.
- Do NOT rewrite `.claude/worktrees/**` (separate checkouts) — the file list excludes them.

### References in Codebase
- `scripts/sdd/sdd_meta.py` — existing re-export shim precedent (FEAT-633 brief).
- `tests/sdd_scripts/test_command_twin_parity.py` — the twin rule for commands ↔ workflows.

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. Never change a signature,
> class name, or file path the blueprint fixes.

### Steps (in order)
1. Confirm dependencies landed: `python -c "import parrot.sdd.audit, parrot.sdd.scripts"` and
   `python -m parrot.sdd.scripts.<n> --help` for each of the 18 names — *why*: rewriting to a
   module that does not resolve breaks every SDD command.
2. Regenerate the file list with the grep in "Files to Create / Modify" and diff it against the
   table — *why*: other features may have touched these files since `6c4ca5482`; a new hit file
   means STOP and update this task's table first.
3. Save the one-off script below OUTSIDE the repo (scratchpad), run it without `--write`
   (dry run), then with `--write` — *why*: deterministic and idempotent; never committed.
4. Review `git diff --stat` and spot-check every `close_task`/`heal_orphans` line (per-file
   checklist) — *why*: these change shape (`.sh` → `python -m`), not just a prefix.
5. Apply the four test edits, create `test_no_repo_script_refs.py`, run the Validation
   Commands — *why*: parity + contract tests prove twins and pins are intact.

### Substitution table (old → new; 18 names `N` only)

| # | Old (regex, `[ \t]` = same line) | New |
|---|---|---|
| 1 | `(bash\|sh)[ \t]+(./)?scripts/sdd/<N>.sh` | `python -m parrot.sdd.scripts.<N>` |
| 2 | `(python\|python3)[ \t]+(./)?scripts/sdd/<N>.py` | `<interp> -m parrot.sdd.scripts.<N>` |
| 3 | `(./)?scripts/sdd/<N>.sh` (bare, invoked or named) | `python -m parrot.sdd.scripts.<N>` |
| 4 | `scripts/sdd/<N>.py` (bare prose file reference) | `parrot.sdd.scripts.<N>` |
| 5 | `scripts.sdd.<N>` (`python -m …`, `from … import`, `…sdd_meta.plan_worktree` prose) | `parrot.sdd.scripts.<N>` |

### All 57 markdown / TOML targets (MODIFY — one-off script, NOT committed)
```python
# occurrences: 187 across 57 files (verified: grep -cE "scripts[./]sdd[./](<18 names>)\b" <each file>, summed)
# REPLACE — every match of the five rules below, in every file of the table (no single anchor:
#           mechanical rewrite; per-file counts are in the Files table)
"""One-off FEAT-633 TASK-4089 rewrite (scratchpad only). Usage: python rewrite_refs.py --list files.txt [--write]"""
import re
import sys
from pathlib import Path

MOVED = (
    "sdd_meta id_ledger reserve_ids check_id_collisions ensure_worktree finalize_task check_task_state "
    "check_task_graph worktree_status close_task heal_orphans doc_taxonomy backfill_taxonomy migrate_index "
    "select_tests insight install_hooks prune_intake"
).split()
N = "|".join(MOVED)
RULES = [
    (re.compile(rf"\b(?:bash|sh)[ \t]+(?:\./)?scripts/sdd/({N})\.sh\b"), r"python -m parrot.sdd.scripts.\1"),
    (re.compile(rf"\b(python3?)[ \t]+(?:\./)?scripts/sdd/({N})\.py\b"), r"\1 -m parrot.sdd.scripts.\2"),
    (re.compile(rf"(?<![\w/.-])(?:\./)?scripts/sdd/({N})\.sh\b"), r"python -m parrot.sdd.scripts.\1"),
    (re.compile(rf"(?<![\w/.-])scripts/sdd/({N})\.py\b"), r"parrot.sdd.scripts.\1"),
    (re.compile(rf"(?<![\w.])scripts\.sdd\.({N})\b"), r"parrot.sdd.scripts.\1"),
]
RESIDUAL = re.compile(rf"scripts[./]sdd[./]({N})\b")


def main(argv: list[str]) -> int:
    write = "--write" in argv
    files = [Path(p) for p in Path(argv[argv.index("--list") + 1]).read_text().split()]
    total = leftovers = 0
    for path in files:
        text = path.read_text(encoding="utf-8")
        new, count = text, 0
        for rx, repl in RULES:
            new, n = rx.subn(repl, new)
            count += n
        rest = RESIDUAL.findall(new.replace("parrot.sdd.scripts.", "@@"))
        total, leftovers = total + count, leftovers + len(rest)
        sys.stdout.write(f"{count:3d} {path}{'  RESIDUAL ' + str(rest) if rest else ''}\n")
        if write and new != text:
            path.write_text(new, encoding="utf-8")
    sys.stdout.write(f"total={total} residual={leftovers}\n")
    return 1 if leftovers else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
```
**Why this shape**: one deterministic pass over both sides of every twin is the only way to
keep byte parity; the residual count makes the run self-verifying (expected first run:
`total=187 residual=0`, second run `total=0 residual=0`). Write `files.txt` with the 57
paths of the table (one per line).

### `tests/sdd_scripts/test_command_contracts.py` (MODIFY)
```python
# occurrences: 4 (verified: grep -c 'scripts.sdd.ensure_worktree' tests/sdd_scripts/test_command_contracts.py)
# REPLACE — all 4 lines (docstring :7, message :46, assert :53, message :55)
#   `scripts.sdd.ensure_worktree` → `parrot.sdd.scripts.ensure_worktree`
# e.g. line 53 becomes:
    assert "parrot.sdd.scripts.ensure_worktree" in _read(
```
**Why**: the old substring is NOT contained in the new form (`…sdd.scripts.ensure_worktree`),
so the FEAT-552 contract would fail; the contract itself is unchanged.

### `tests/sdd/test_codex_sdd_sync.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    assert "scripts.sdd.finalize_task" in worker' tests/sdd/test_codex_sdd_sync.py)
# REPLACE — `    assert "scripts.sdd.finalize_task" in worker` (verified: tests/sdd/test_codex_sdd_sync.py:33)
    assert "parrot.sdd.scripts.finalize_task" in worker
```
**Why**: `.codex/agents/sdd-worker.toml` is rewritten by this task.

### `packages/ai-parrot/tests/flows/dev_loop/test_worker_prompt_orchestrator.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    assert "python -m scripts.sdd.finalize_task" in loop' packages/ai-parrot/tests/flows/dev_loop/test_worker_prompt_orchestrator.py)
# REPLACE — `    assert "python -m scripts.sdd.finalize_task" in loop` (verified: test_worker_prompt_orchestrator.py:214)
    assert "python -m parrot.sdd.scripts.finalize_task" in loop
# also REPLACE the docstring mention at :210 `scripts.sdd.finalize_task` → `parrot.sdd.scripts.finalize_task`
# (grep -c 'scripts.sdd.finalize_task' == 2: lines 210 and 214)
```
**Why**: `load_subagent_definition("sdd-worker")` reads the rewritten `_subagent_data` copy.

### `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_start_optimization_contract.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '"python -m scripts.sdd.finalize_task",' .../test_start_optimization_contract.py)
# REPLACE — `            "python -m scripts.sdd.finalize_task",` (verified: test_start_optimization_contract.py:43)
            "python -m parrot.sdd.scripts.finalize_task",
# occurrences: 1 (verified: grep -c '        assert "close_task.sh" in body, f"{rel_path} lost its close_task.sh reference"' ...)
# REPLACE — line 59 (and the comment at :51 naming close_task.sh)
        assert "parrot.sdd.scripts.close_task" in body, f"{rel_path} lost its close_task reference"
```
**Why**: the closure block now calls the Python port; the AC8/AC17 intent (closure still goes
through the deterministic closer) is unchanged.

### `packages/ai-parrot/tests/sdd/test_no_repo_script_refs.py` (CREATE)
```python
"""FEAT-633 M6: no SDD asset references a moved helper by its repo-relative path.

Every helper listed in ``_MOVED`` lives in ``parrot.sdd.scripts`` (TASK-4085..4088); an installed
asset that still says ``python -m scripts.sdd.<name>`` / ``scripts/sdd/<name>.py`` is broken in
any repository that is not this monorepo. Non-moved helpers (``review_checkpoint``,
``lint_new`` …) are allowed and deliberately not asserted here.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

from parrot.sdd.audit import scan_paths  # created by TASK-4070

_REPO_ROOT = Path(__file__).resolve().parents[4]  # packages/ai-parrot/tests/sdd/ -> repo root
_MOVED: tuple[str, ...] = (
    "sdd_meta", "id_ledger", "reserve_ids", "check_id_collisions", "ensure_worktree", "finalize_task",
    "check_task_state", "check_task_graph", "worktree_status", "close_task", "heal_orphans",
    "doc_taxonomy", "backfill_taxonomy", "migrate_index", "select_tests", "insight", "install_hooks",
    "prune_intake",  # added to TASK-4088 by the coordinator
)
_ASSET_GLOBS: tuple[str, ...] = (
    ".claude/commands/*.md", ".claude/agents/*.md", ".claude/rules/*.md", ".claude/skills/**/*.md",
    ".agent/**/*.md", ".agents/**/*.md", ".codex/agents/*.toml",
    "sdd/WORKFLOW.md", "docs/sdd/WORKFLOW.md", "CLAUDE.md", "AGENTS.md", "sdd/templates/*.md",
    "packages/ai-parrot/src/parrot/flows/**/_subagent_data/*.md",
    "packages/ai-parrot/src/parrot/flows/_rules_data/*.md",
)
_MOVED_RE = re.compile(rf"scripts[./]sdd[./]({'|'.join(_MOVED)})\b")


def _asset_files() -> list[Path]:
    """Every SDD asset in the checkout (``.claude/worktrees/`` excluded)."""
    if not (_REPO_ROOT / ".claude").is_dir():
        pytest.skip("not a repo checkout (installed package)")
    files = {p for g in _ASSET_GLOBS for p in _REPO_ROOT.glob(g) if p.is_file()}
    return sorted(p for p in files if "worktrees" not in p.parts)


def test_no_repo_script_findings_for_moved_helpers() -> None:
    """parrot.sdd.audit reports zero ``repo-script`` findings naming a moved helper."""
    findings = scan_paths(_asset_files())
    # FILL IN: adapt the call/filters to the exact TASK-4070 signature — bounded by
    #          AssumptionFinding(path, line, kind, snippet) and kind == "repo-script"
    offenders = [f for f in findings if f.kind == "repo-script" and _MOVED_RE.search(f.snippet)]
    assert not offenders, "\n".join(f"{f.path}:{f.line}: {f.snippet}" for f in offenders)


def test_every_rewritten_reference_resolves() -> None:
    """Each ``parrot.sdd.scripts.<name>`` named by an asset is an importable module."""
    pattern = re.compile(r"parrot\.sdd\.scripts\.([a-z_]+)")
    names = {m for p in _asset_files() for m in pattern.findall(p.read_text(encoding="utf-8"))}
    missing = sorted(n for n in names if importlib.util.find_spec(f"parrot.sdd.scripts.{n}") is None)
    assert not missing, f"unresolvable parrot.sdd.scripts modules referenced: {missing}"
```
**Why this shape**: the first test is the spec-mandated S5-scanner gate; the second proves the
new form actually resolves (spec §5 "every helper referenced by installed markdown resolves").
`parents[4]` mirrors `tests/sdd_scripts/test_command_twin_parity.py`'s fixed-depth root.

### Per-file checklist (after `--write`)
- [ ] `git diff --stat` lists exactly the 57 markdown/TOML files + the 5 test files.
- [ ] `.claude/commands/sdd-done.md` / `.agent/workflows/sdd-done.md` / `.agents/skills/sdd-done/SKILL.md`:
      `(cd "$WORKTREE_PATH" && python -m parrot.sdd.scripts.close_task "$TASK_ID" …)` and the
      `heal_orphans` lines keep their arguments; the ```` ```bash ```` fence lines are intact.
- [ ] `sdd-start` (3 hosts) + `sdd-worker` (4 copies): `close_task` / `finalize_task` lines read naturally.
- [ ] `sdd-insight` (3 hosts): `python3 -m parrot.sdd.scripts.insight \` continuation lines intact.
- [ ] `sdd-spec`/`sdd-task` `python -c "…; from parrot.sdd.scripts.sdd_meta import …"` one-liners intact.
- [ ] `sdd/templates/task.md` lines 329 and 344 now name `python -m parrot.sdd.scripts.ensure_worktree`
      / `python -m parrot.sdd.scripts.close_task`.
- [ ] `review_checkpoint` references in `sdd-worker.md` (both copies) unchanged.
- [ ] `cmp` each `.claude/agents/<n>.md` with its `_subagent_data` copy (5 pairs) — identical.

### FILL IN checklist
- [ ] Confirm `parrot.sdd.scripts.prune_intake` exists (TASK-4088) before running; it has 0 markdown hits today.
- [ ] `test_no_repo_script_refs.py::test_no_repo_script_findings_for_moved_helpers` — match the
      real `scan_paths` signature/return type; bounded by TASK-4070's `AssumptionFinding` and kind `repo-script`.
- [ ] `close_task` / `heal_orphans` argv parity — confirm TASK-4087 kept the `.sh` positional CLI;
      bounded by spec §5 ("`scripts/sdd/` wrappers keep the monorepo's existing invocations working").

---

## Acceptance Criteria

- [ ] `grep -rlE "scripts[./]sdd[./](<18 names>)\b"` over the asset paths listed in this task
      returns nothing (spec §5: every helper referenced by installed markdown resolves as
      `python -m parrot.sdd.scripts.<name>`).
- [ ] References to non-moved helpers (`review_checkpoint`, `lint_new`, …) are byte-unchanged.
- [ ] All twin/copy parity tests pass (commands ↔ workflows, `.claude/agents` ↔ `_subagent_data`).
- [ ] The four updated contract tests pass against the rewritten assets.
- [ ] `test_no_repo_script_refs.py` passes (zero `repo-script` findings for the 18 names; every
      referenced `parrot.sdd.scripts.<name>` resolves).
- [ ] Re-running the rewrite script reports `total=0 residual=0` (idempotent).
- [ ] No linting errors: `ruff check packages/ai-parrot/tests/sdd/test_no_repo_script_refs.py`
      and the four modified test files.

---

## Validation Commands

Run from the feature worktree with `PYTHONPATH=packages/ai-parrot/src` (the shared venv is
editable-installed against the main checkout).

- `pytest packages/ai-parrot/tests/sdd/test_no_repo_script_refs.py -q`
- `pytest tests/sdd_scripts/test_command_twin_parity.py -q`
- `pytest tests/sdd_scripts/test_command_contracts.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_subagent_parity.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_flow/test_subagent_defs.py::test_prompt_parity_with_repo_twin -q`
- `pytest tests/sdd/test_codex_sdd_sync.py -q`
- `pytest tests/sdd/test_ledger_workflow_twins.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_worker_prompt_orchestrator.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_start_optimization_contract.py -q`

---

## Test Specification

> Minimal test scaffold. The agent must make these pass.

```python
# packages/ai-parrot/tests/sdd/test_no_repo_script_refs.py — see the CREATE block above:
#   test_no_repo_script_findings_for_moved_helpers   (S5 scanner gate)
#   test_every_rewritten_reference_resolves          (new form imports)
# Existing tests updated (assert the new form; intent unchanged):
#   tests/sdd_scripts/test_command_contracts.py::test_every_creator_calls_ensure_worktree
#   tests/sdd/test_codex_sdd_sync.py::test_worker_uses_deterministic_finalization_and_scoped_force_add
#   packages/ai-parrot/tests/flows/dev_loop/test_worker_prompt_orchestrator.py::
#       test_worker_prompt_uses_finalize_task_not_manual_jq_close_in_orchestrator_loop
#   packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_start_optimization_contract.py::
#       test_start_twins_preserve_semantic_gates
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug parrot-installer --feature-id FEAT-633`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in the
   per-spec index `sdd/tasks/index/parrot-installer.json`
4. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
5. **Update status** in `sdd/tasks/index/parrot-installer.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
7. **Verify** all acceptance criteria are met — run the Validation Commands
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4089 parrot-installer verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
