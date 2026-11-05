# TASK-5210: Document sync safety and update worker prompt twins

**Feature**: FEAT-806 — Worktree Sync Base
**Spec**: `sdd/specs/worktree-sync-base.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

## Context

M4 documents the gh-only worker workflow and trusted-host prerequisites without contradicting existing startup instructions.

## Scope

Update the listed source and packaged copies together. Scope existing fetch/pull/push instructions to host-only contexts and replace sandbox instructions with sync-base. Keep other prompt contracts intact. NOT in scope: new tooling, implementation or broad asset regeneration.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.claude/rules/worktree-management.md` | MODIFY | Host/worker sync guidance |
| `packages/ai-parrot/src/parrot/sdd/_assets/claude/rules/worktree-management.md` | MODIFY | Host/worker sync guidance |
| `.agent/skills/worktree-management/SKILL.md` | MODIFY | Host/worker sync guidance |
| `.claude/agents/sdd-worker.md` | MODIFY | Host/worker sync guidance |
| `packages/ai-parrot/src/parrot/sdd/_assets/claude/agents/sdd-worker.md` | MODIFY | Host/worker sync guidance |
| `.codex/agents/sdd-worker.toml` | MODIFY | Host/worker sync guidance |
| `packages/ai-parrot/src/parrot/sdd/_assets/codex/agents/sdd-worker.toml` | MODIFY | Host/worker sync guidance |
| `docs/sdd/worktree-sync-base.md` | CREATE | Operator guide |

## Codebase Contract (Anti-Hallucination)

Verified at `cd57902e64`. Dependency-created symbols are explicitly identified below; verify them after dependencies land.

### Verified Imports
No new runtime imports. Existing test suites are tests/sdd_scripts/test_check_asset_sync.py and packages/ai-parrot/tests/flows/dev_loop/test_subagent_parity.py plus test_worker_prompt_orchestrator.py.

### Existing Signatures to Use
Documentation anchors are verified individually below. `_subagent_defs.py` loads sdd-worker from `parrot/sdd/_assets/claude/agents/`; there is no separate `_subagent_data/sdd-worker.md` to modify. Codex TOML embeds developer_instructions: preserve valid TOML quoting. Worktree-management currently advises native push; worker startup currently contains raw fetch. Reconcile these conflicting paragraphs, not just append a new one.

### Does NOT Exist
- No operator guide docs/sdd/worktree-sync-base.md yet.
- No permission for a sandbox worker to configure Git or request widened network access.


## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": ".claude/rules/worktree-management.md",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/sdd/_assets/claude/rules/worktree-management.md",
      "action": "MODIFY"
    },
    {
      "path": ".agent/skills/worktree-management/SKILL.md",
      "action": "MODIFY"
    },
    {
      "path": ".claude/agents/sdd-worker.md",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/sdd/_assets/claude/agents/sdd-worker.md",
      "action": "MODIFY"
    },
    {
      "path": ".codex/agents/sdd-worker.toml",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/sdd/_assets/codex/agents/sdd-worker.toml",
      "action": "MODIFY"
    },
    {
      "path": "docs/sdd/worktree-sync-base.md",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

## Implementation Notes

Independent M4: authors the approved command contract, not runtime behavior. No edge to TASK-5207 or TASK-5209: command examples do not consume their new files. All repo/package prompt writers are owned by this task.

Use repository tools from the activated environment; preserve shared environments. Keep changes within declared files, use typed functions and Google-style docstrings, black (120 columns), and ruff. Tests must import this worktree's source, not another editable checkout. No new dependency is authorized. CLI subprocess I/O is synchronous by design; do not introduce blocking I/O into async entry points. Run no network or destructive operations against the real repository in tests.

## Implementation Blueprint

Blueprint gaps below are planning instructions only; finished code must have no placeholders.

### Steps (in order)

1. Read all seven instruction surfaces — contradictory old fetch/push advice must be removed or explicitly host-scoped.
2. Write the guide from approved §2 and §4 — preserve host setup, dry-run exceptions and failure semantics.
3. Apply equivalent edits to each packaged twin and run both prompt suites plus asset parity — wheel-installed users must get the same behavior.

### `.claude/rules/worktree-management.md` (MODIFY)

Anchor `## 4. Work inside` — .claude/rules/worktree-management.md:49, occurrences: 1 (verified at cd57902e64).

```text
Need a base fix inside the sandbox? Run
`parrot sdd worktree sync-base <FEAT-ID|KEY|name|path> --cherry-pick <sha>`.
Never run git fetch/pull/push inside the worker sandbox. Full-base sync is a host
operator action before starting the worker. If push-protection prerequisites are
missing, ask the host operator to provision them; never change protected Git config.
The host entry point prints the stale-base advisory; do not run that check inside the sandbox.
# FILL IN: reconcile contradictory startup fetch/push text in this file; preserve host-only flow.
```

**Why**: Keep repo and packaged instructions consistent, including removing conflicting in-sandbox fetch/push advice.

### `packages/ai-parrot/src/parrot/sdd/_assets/claude/rules/worktree-management.md` (MODIFY)

Anchor `## 4. Work inside` — packages/ai-parrot/src/parrot/sdd/_assets/claude/rules/worktree-management.md:49, occurrences: 1 (verified at cd57902e64).

```text
Need a base fix inside the sandbox? Run
`parrot sdd worktree sync-base <FEAT-ID|KEY|name|path> --cherry-pick <sha>`.
Never run git fetch/pull/push inside the worker sandbox. Full-base sync is a host
operator action before starting the worker. If push-protection prerequisites are
missing, ask the host operator to provision them; never change protected Git config.
The host entry point prints the stale-base advisory; do not run that check inside the sandbox.
# FILL IN: reconcile contradictory startup fetch/push text in this file; preserve host-only flow.
```

**Why**: Keep repo and packaged instructions consistent, including removing conflicting in-sandbox fetch/push advice.

### `.agent/skills/worktree-management/SKILL.md` (MODIFY)

Anchor `## 4. Work inside` — .agent/skills/worktree-management/SKILL.md:47, occurrences: 1 (verified at cd57902e64).

```text
Need a base fix inside the sandbox? Run
`parrot sdd worktree sync-base <FEAT-ID|KEY|name|path> --cherry-pick <sha>`.
Never run git fetch/pull/push inside the worker sandbox. Full-base sync is a host
operator action before starting the worker. If push-protection prerequisites are
missing, ask the host operator to provision them; never change protected Git config.
The host entry point prints the stale-base advisory; do not run that check inside the sandbox.
# FILL IN: reconcile contradictory startup fetch/push text in this file; preserve host-only flow.
```

**Why**: Keep repo and packaged instructions consistent, including removing conflicting in-sandbox fetch/push advice.

### `.claude/agents/sdd-worker.md` (MODIFY)

Anchor `### 0. Sync the Base Branch (FEAT-145)` — .claude/agents/sdd-worker.md:150, occurrences: 1 (verified at cd57902e64).

```text
Need a base fix inside the sandbox? Run
`parrot sdd worktree sync-base <FEAT-ID|KEY|name|path> --cherry-pick <sha>`.
Never run git fetch/pull/push inside the worker sandbox. Full-base sync is a host
operator action before starting the worker. If push-protection prerequisites are
missing, ask the host operator to provision them; never change protected Git config.
The host entry point prints the stale-base advisory; do not run that check inside the sandbox.
# FILL IN: reconcile contradictory startup fetch/push text in this file; preserve host-only flow.
```

**Why**: Keep repo and packaged instructions consistent, including removing conflicting in-sandbox fetch/push advice.

### `packages/ai-parrot/src/parrot/sdd/_assets/claude/agents/sdd-worker.md` (MODIFY)

Anchor `### 0. Sync the Base Branch (FEAT-145)` — packages/ai-parrot/src/parrot/sdd/_assets/claude/agents/sdd-worker.md:150, occurrences: 1 (verified at cd57902e64).

```text
Need a base fix inside the sandbox? Run
`parrot sdd worktree sync-base <FEAT-ID|KEY|name|path> --cherry-pick <sha>`.
Never run git fetch/pull/push inside the worker sandbox. Full-base sync is a host
operator action before starting the worker. If push-protection prerequisites are
missing, ask the host operator to provision them; never change protected Git config.
The host entry point prints the stale-base advisory; do not run that check inside the sandbox.
# FILL IN: reconcile contradictory startup fetch/push text in this file; preserve host-only flow.
```

**Why**: Keep repo and packaged instructions consistent, including removing conflicting in-sandbox fetch/push advice.

### `.codex/agents/sdd-worker.toml` (MODIFY)

Anchor `## Shared environment policy` — .codex/agents/sdd-worker.toml:34, occurrences: 1 (verified at cd57902e64).

```text
Need a base fix inside the sandbox? Run
`parrot sdd worktree sync-base <FEAT-ID|KEY|name|path> --cherry-pick <sha>`.
Never run git fetch/pull/push inside the worker sandbox. Full-base sync is a host
operator action before starting the worker. If push-protection prerequisites are
missing, ask the host operator to provision them; never change protected Git config.
The host entry point prints the stale-base advisory; do not run that check inside the sandbox.
# FILL IN: reconcile contradictory startup fetch/push text in this file; preserve host-only flow.
```

**Why**: Keep repo and packaged instructions consistent, including removing conflicting in-sandbox fetch/push advice.

### `packages/ai-parrot/src/parrot/sdd/_assets/codex/agents/sdd-worker.toml` (MODIFY)

Anchor `## Shared environment policy` — packages/ai-parrot/src/parrot/sdd/_assets/codex/agents/sdd-worker.toml:34, occurrences: 1 (verified at cd57902e64).

```text
Need a base fix inside the sandbox? Run
`parrot sdd worktree sync-base <FEAT-ID|KEY|name|path> --cherry-pick <sha>`.
Never run git fetch/pull/push inside the worker sandbox. Full-base sync is a host
operator action before starting the worker. If push-protection prerequisites are
missing, ask the host operator to provision them; never change protected Git config.
The host entry point prints the stale-base advisory; do not run that check inside the sandbox.
# FILL IN: reconcile contradictory startup fetch/push text in this file; preserve host-only flow.
```

**Why**: Keep repo and packaged instructions consistent, including removing conflicting in-sandbox fetch/push advice.

### `docs/sdd/worktree-sync-base.md` (CREATE)

```markdown
# Worktree base synchronization

## Host usage
`parrot sdd worktree sync-base FEAT-806`
`parrot sdd worktree sync-base FEAT-806 --ff-only`
`parrot sdd worktree sync-base FEAT-806 --dry-run --json`

## Sandbox usage
`parrot sdd worktree sync-base FEAT-806 --cherry-pick <sha>`

## Host setup before sandbox launch
Enable extensions.worktreeConfig only after preserving existing common core.worktree
and core.bare semantics for the primary and linked worktrees. Configure only the target
worktree's remote.origin.pushurl to no_push; never change the common push URL.
# FILL IN: safe exact host commands and migration guidance; missing prerequisites return 5.

## Safety, failure and recovery
# FILL IN: target guards, dry-run exception, ancestry exclusion, atomic rollback, failed-abort
# error versus restored conflict, no overrides, no push/rebase, source-SHA trailers.

## Exit codes
# FILL IN: full 0/2/3/4/5/6 table and JSON status distinction from spec §2.

## Advisory at startup
# FILL IN: host launcher and sdd-start behavior, no-upstream exemption and skipped checks.
```

**Why**: Operator instructions must distinguish host setup from read-only sandbox prerequisite checks.


### FILL IN checklist

- [ ] All listed instruction surfaces use sync-base --cherry-pick for sandbox fixes and never instruct in-sandbox fetch/pull/push or protected config writes.
- [ ] Guide includes host provisioning/migration precautions, every exit code, JSON status semantics, rollback failure guidance and no live override.
- [ ] Guide documents source-SHA trailers, one-batch atomicity and host-only advisory; dry-run skips dirty/live guards but still validates sandbox protection.
- [ ] Packaged twins preserve parity; Codex TOML still parses; existing worker prompt tests pass.

## Acceptance Criteria

- [ ] All listed instruction surfaces use sync-base --cherry-pick for sandbox fixes and never instruct in-sandbox fetch/pull/push or protected config writes.
- [ ] Guide includes host provisioning/migration precautions, every exit code, JSON status semantics, rollback failure guidance and no live override.
- [ ] Guide documents source-SHA trailers, one-batch atomicity and host-only advisory; dry-run skips dirty/live guards but still validates sandbox protection.
- [ ] Packaged twins preserve parity; Codex TOML still parses; existing worker prompt tests pass.
- [ ] All task validation commands pass and touched Python files pass `ruff check`; apply `black --line-length 120` to touched Python files.

## Validation Commands

- `pytest tests/sdd_scripts/test_check_asset_sync.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_subagent_parity.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_worker_prompt_orchestrator.py -q`

## Test Specification

Use existing parity and prompt suites; no new superficial text-matching test is needed. Manually check host commands never alter common remote.origin.pushurl and sandbox examples never write config.

## Agent Instructions

1. Use `$sdd-start TASK-5210` in the FEAT-806 feature worktree; never implement on dev.
2. Verify dependencies are done in `sdd/tasks/index/worktree-sync-base.json` and revalidate contracts before editing.
3. Implement only declared files, finish every blueprint gap, and run the listed validation commands. Store logs under `artifacts/logs/`.
4. Commit implementation files, then finalize through `scripts.sdd.finalize_task` using real `TaskCompletionEvidence` and the exact implementation HEAD, following the Codex adaptation contract. Do not manually move tasks or write completion evidence.
5. Commit only the resulting task/index state. Do not push from the worker.

## Completion Note

Pending; populated by the finalization tool after implementation and validation.
