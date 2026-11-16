# TASK-5611: Documentation — experience memory and native sandbox

**Feature**: FEAT-887 — SDD Experience Memory (experience.pitfall)
**Spec**: `sdd/specs/sdd-experience-memory.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5588, TASK-5589, TASK-5590, TASK-5591, TASK-5592, TASK-5593, TASK-5594, TASK-5595, TASK-5596, TASK-5597, TASK-5598, TASK-5599, TASK-5600, TASK-5601, TASK-5602, TASK-5603, TASK-5604, TASK-5605, TASK-5606, TASK-5607, TASK-5608, TASK-5609, TASK-5610
**Assigned-to**: unassigned

## Context

Implement Module 12 of the approved spec, with §2 behavioral contracts and §4 regression coverage. This task is a bounded portion of that module; its file table is authoritative.

## Scope

Use sdd/templates/techwiki-page.md to document both required pages, API references, lifecycle, CLI, tiers, namespace, sharing, graduation, host differences and troubleshooting. Correct writable experience directory and isolated-hook control-file policy in worktree rule and twin. Use the implemented integration scenario as the runnable usage example; retain read-only wiki/HOME and reviewed shared-log trust model.

**NOT in scope**: Other task-owned files, new dependencies, changing public signatures fixed by the spec, or implementing the future procedure plane.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `wiki/sdd-tooling/sdd/experience-memory.md` | CREATE | Scoped deliverable |
| `wiki/sdd-tooling/dev_loop/claude-native-sandbox.md` | MODIFY | Scoped deliverable |
| `.claude/rules/worktree-management.md` | MODIFY | Scoped deliverable |
| `packages/ai-parrot/src/parrot/sdd/_assets/claude/rules/worktree-management.md` | MODIFY | Scoped deliverable |

## Codebase Contract

Verified against `0c5acf0915`. Existing references below were re-read during decomposition. New experience imports are dependency-provided interfaces, not claims of pre-existing code.

### Verified Imports

No Python imports are introduced by this documentation-only task.

Standard-library imports use Python's installed library; Pydantic v2 is declared in packages/ai-parrot/pyproject.toml and pytest in root pyproject.toml. Existing project symbols are anchored below. New symbols are fixed by the matching producer blueprint and must be verified after dependencies land.

### Existing Signatures to Use

No existing class/function is consumed beyond the standard library and declared dependencies. Existing edit anchors are quoted per file below.

### Dependency Interfaces

documentation: TASK-5588: consumes the fastpath contract in packages/ai-parrot/src/parrot/knowledge/wiki/experience/__init__.py, packages/ai-parrot/src/parrot/knowledge/wiki/experience/fastpath.py; TASK-5589: consumes the domain-models contract in packages/ai-parrot/src/parrot/knowledge/wiki/experience/models.py; TASK-5590: consumes the event-schemas contract in packages/ai-parrot/src/parrot/knowledge/wiki/experience/models.py; TASK-5591: consumes the reducer contract in packages/ai-parrot/src/parrot/knowledge/wiki/experience/reducer.py; TASK-5592: consumes the index contract in packages/ai-parrot/src/parrot/knowledge/wiki/experience/index.py, packages/ai-parrot/src/parrot/knowledge/wiki/project.py; TASK-5593: consumes the service contract in packages/ai-parrot/src/parrot/knowledge/wiki/experience/service.py; TASK-5594: consumes the sandbox contract in packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py, packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py; TASK-5595: consumes the transitions contract in packages/ai-parrot/src/parrot/knowledge/wiki/experience/transitions.py; TASK-5596: consumes the hooks contract in packages/ai-parrot/src/parrot/sdd/scripts/experience_hook.py, packages/ai-parrot/src/parrot/launcher.py; TASK-5597: consumes the graduation contract in packages/ai-parrot/src/parrot/knowledge/wiki/experience/graduation.py; TASK-5598: consumes the sync contract in packages/ai-parrot/src/parrot/knowledge/wiki/experience/sync.py; TASK-5599: consumes the cli contract in packages/ai-parrot/src/parrot/sdd/scripts/experience_cli.py, packages/ai-parrot/src/parrot/sdd/cli.py; TASK-5600: consumes the claude-install contract in packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py, packages/ai-parrot/src/parrot/sdd/installer.py; TASK-5601: consumes the interceptor contract in packages/ai-parrot/src/parrot/flows/dev_loop/experience.py, packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py; TASK-5602: consumes the codex-replay contract in packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/codex.py; TASK-5603: consumes the agy-replay contract in packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/google_coding.py; TASK-5604: consumes the gemini-replay contract in packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/gemini.py; TASK-5605: consumes the host-install contract in packages/ai-parrot/src/parrot/sdd/installer.py, .codex/hooks.json; TASK-5606: consumes the output-models contract in packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py, packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py; TASK-5607: consumes the engine contract in packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py; TASK-5608: consumes the authoring-assets contract in .claude/commands/sdd-start.md, .agent/workflows/sdd-start.md; TASK-5609: consumes the lifecycle contract in packages/ai-parrot/src/parrot/flows/dev_loop/feature_launcher.py, packages/ai-parrot/src/parrot/sdd/installer.py; TASK-5610: consumes the tested A/B/C/D usage scenario in packages/ai-parrot/tests/knowledge/wiki/experience/test_end_to_end.py

### Does NOT Exist

- `wiki/sdd-tooling/sdd/experience-memory.md` — absent at 0c5acf0915; supplied by this task or its declared predecessor.
- `parrot sdd task start` is not a CLI verb; task-start priming is workflow prose.
- Experience functionality is new; imported producer symbols must be rechecked after dependencies land.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "wiki/sdd-tooling/sdd/experience-memory.md",
      "action": "CREATE"
    },
    {
      "path": "wiki/sdd-tooling/dev_loop/claude-native-sandbox.md",
      "action": "MODIFY"
    },
    {
      "path": ".claude/rules/worktree-management.md",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/sdd/_assets/claude/rules/worktree-management.md",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": []
}
```

## Implementation Notes

Use async service calls and bounded IO. Keep stdlib hook imports lazy, preserve the exception/cancellation semantics of callers, and log through the module logger. Blueprint gaps are planning instructions only: delivered code must contain no unfinished placeholders. All tests use temporary roots; do not mutate real global experience data. Each asset writer owns its packaged twins.

## Implementation Blueprint

### Steps (in order)

1. Verify the existing anchors and dependency interfaces — they fix the allowed integration surface.
2. Apply the per-file starting points and complete the scoped behavior — Use sdd/templates/techwiki-page.md to document both required pages, API references, lifecycle, CLI, tiers, namespace, sharing, graduation, host differences and troubleshooting. Correct writable experience directory and isolated-hook control-file policy in worktree rule and twin. Use the implemented integration scenario as the runnable usage example; retain read-only wiki/HOME and reviewed shared-log trust model.
3. Exercise the listed failure and boundary cases — these protect the feature's event, sandbox and host contracts.
4. Run the task's validation commands and inspect the diff — commit only declared files and task state.

### `wiki/sdd-tooling/sdd/experience-memory.md` (CREATE)

```text
---
title: SDD experience memory
summary: Scoped, replayable operational lessons for SDD agents.
---

# SDD experience memory

## Purpose
FILL IN: lifecycle, reviewed-log trust boundary and operational scope.

## Public API
- [ExperienceService](ref:parrot.knowledge.wiki.experience.service.ExperienceService)
- [ExperienceIndex](ref:parrot.knowledge.wiki.experience.index.ExperienceIndex)

## Configuration & Parameters
FILL IN: ExperienceConfig defaults, PARROT_HOME and PARROT_EXPERIENCE_SESSION.

## Usage Examples
FILL IN: init, record, brief, query --ns experience, sync/export and retire;
use the deterministic A/B/C/D integration scenario.

## Gotchas
FILL IN: candidate advice, quarantine, revisions, locales, stale generations,
unknown outcomes, bounded IO, replay identity, hook timing and host differences.

## Related
- [Native sandbox](../dev_loop/claude-native-sandbox.md)
```

**Why**: This file owns the documentation behavior described in Scope. Preserve its existing callers and complete only the bounded cases in this task.

### `wiki/sdd-tooling/dev_loop/claude-native-sandbox.md` (MODIFY)

```text
# Anchor occurrences: 1; verified wiki/sdd-tooling/dev_loop/claude-native-sandbox.md:14 at 0c5acf0915.
# Anchor: ## What it protects — and what it does not
Update protection, hook delivery and troubleshooting sections from the shipped behavior.
Document .parrot/experience/ as writable; wiki and HOME remain read-only.
PostToolUse and PostToolUseFailure are advisory, use isolated shared Python,
and their runtime files are protected. No experience PreToolUse hook is registered.
Link to ../sdd/experience-memory.md and the tested hook-integrity scenario.
FILL IN: reconcile existing lists and cross-links without deleting platform qualifications.
```

**Why**: This file owns the documentation behavior described in Scope. Preserve its existing callers and complete only the bounded cases in this task.

### `.claude/rules/worktree-management.md` (MODIFY)

```text
# Anchor occurrences: 1; verified .claude/rules/worktree-management.md:55 at 0c5acf0915.
# Anchor: - SDD in-process commands and native Claude Bash hooks use Bubblewrap filesystem protection. The checkout, Git metadata, the primary checkout's worktree root (so `/sdd-done` can add the ledger-snapshot worktree and remove the feature worktree from inside it), the primary checkout's `.parrot/ledger/` (so `wikitoolkit ledger open/claim/close` work from inside a worktree) and the primary checkout's sdd-coder evidence store (`${SDD_HOOKS_ARTIFACT_ROOT}`, so `parrot sdd task review prepare` and `finalize` can write; the rest of `artifacts/` stays read-only) are writable; the rest of the primary checkout and shared environments are mounted read-only, with private temporary storage — except Claude Code's scratchpad root (`/tmp/claude-<uid>`), which is bound back in so the session scratchpad persists across Bash calls. When `rtk` is on `PATH`, the native hook also passes each command through `rtk rewrite` (after the test-scope guard), so RTK runs inside the sandbox; `PARROT_SANDBOX_RTK=0` turns this off. RTK's data directory stays read-only, because it holds RTK's trust store for project `.rtk/filters.toml`; sandboxed runs are therefore not counted by `rtk gain`. Another `PreToolUse` hook that rewrites Bash input (RTK's global hook included) can replace the sandbox wrapper, so sandboxed sessions never load the `user` setting source (`issue:6756c929a450`): launch a worker with `parrot sdd launch worker <FEAT-ID|KEY>` (features and briefs; add `--tmux [--detach]` to run it unattended), and the dev-loop dispatcher forces the same for `sdd-worker`/`sdd-coder` seats. With `PARROT_SDD_SANDBOX_BACKEND` unset the hook runs each command natively when Claude Code's native sandbox is active and through Bubblewrap otherwise; `PARROT_SDD_SANDBOX_BACKEND=bubblewrap` forces the legacy wrapper. Missing Bubblewrap or denied namespaces must stop execution, never trigger an unsandboxed retry. Other CLI hosts must provide equivalent protection. Command allowlists and prompt rules alone do not guarantee this policy.
Add the primary checkout .parrot/experience/ directory to the existing writable policy.
Keep .parrot/wiki, HOME and shared environments read-only.
Worker experience hooks use the absolute shared-venv Python with -I -m;
experience_hook.py, fastpath.py and launcher.py copies are OS-denied control files.
FILL IN: integrate this text into the existing policy paragraph and retain all other protections.
```

**Why**: This file owns the documentation behavior described in Scope. Preserve its existing callers and complete only the bounded cases in this task.

### `packages/ai-parrot/src/parrot/sdd/_assets/claude/rules/worktree-management.md` (MODIFY)

```text
# Anchor occurrences: 1; verified packages/ai-parrot/src/parrot/sdd/_assets/claude/rules/worktree-management.md:55 at 0c5acf0915.
# Anchor: - SDD in-process commands and native Claude Bash hooks use Bubblewrap filesystem protection. The checkout, Git metadata, the primary checkout's worktree root (so `/sdd-done` can add the ledger-snapshot worktree and remove the feature worktree from inside it), the primary checkout's `.parrot/ledger/` (so `wikitoolkit ledger open/claim/close` work from inside a worktree) and the primary checkout's sdd-coder evidence store (`${SDD_HOOKS_ARTIFACT_ROOT}`, so `parrot sdd task review prepare` and `finalize` can write; the rest of `artifacts/` stays read-only) are writable; the rest of the primary checkout and shared environments are mounted read-only, with private temporary storage — except Claude Code's scratchpad root (`/tmp/claude-<uid>`), which is bound back in so the session scratchpad persists across Bash calls. When `rtk` is on `PATH`, the native hook also passes each command through `rtk rewrite` (after the test-scope guard), so RTK runs inside the sandbox; `PARROT_SANDBOX_RTK=0` turns this off. RTK's data directory stays read-only, because it holds RTK's trust store for project `.rtk/filters.toml`; sandboxed runs are therefore not counted by `rtk gain`. Another `PreToolUse` hook that rewrites Bash input (RTK's global hook included) can replace the sandbox wrapper, so sandboxed sessions never load the `user` setting source (`issue:6756c929a450`): launch a worker with `parrot sdd launch worker <FEAT-ID|KEY>` (features and briefs; add `--tmux [--detach]` to run it unattended), and the dev-loop dispatcher forces the same for `sdd-worker`/`sdd-coder` seats. With `PARROT_SDD_SANDBOX_BACKEND` unset the hook runs each command natively when Claude Code's native sandbox is active and through Bubblewrap otherwise; `PARROT_SDD_SANDBOX_BACKEND=bubblewrap` forces the legacy wrapper. Missing Bubblewrap or denied namespaces must stop execution, never trigger an unsandboxed retry. Other CLI hosts must provide equivalent protection. Command allowlists and prompt rules alone do not guarantee this policy.
Add the primary checkout .parrot/experience/ directory to the existing writable policy.
Keep .parrot/wiki, HOME and shared environments read-only.
Worker experience hooks use the absolute shared-venv Python with -I -m;
experience_hook.py, fastpath.py and launcher.py copies are OS-denied control files.
FILL IN: integrate this text into the existing policy paragraph and retain all other protections.
```

**Why**: This file owns the documentation behavior described in Scope. Preserve its existing callers and complete only the bounded cases in this task.

### FILL IN checklist

- [ ] `wiki/sdd-tooling/sdd/experience-memory.md` — finish its marked branches/examples using Scope and Test Specification.
- [ ] `wiki/sdd-tooling/dev_loop/claude-native-sandbox.md` — finish its marked branches/examples using Scope and Test Specification.
- [ ] `.claude/rules/worktree-management.md` — finish its marked branches/examples using Scope and Test Specification.
- [ ] `packages/ai-parrot/src/parrot/sdd/_assets/claude/rules/worktree-management.md` — finish its marked branches/examples using Scope and Test Specification.

## Acceptance Criteria

- [ ] AC1: All declared files implement Scope using the spec's exact public interfaces; existing behavior remains compatible.
- [ ] AC2: The stated no-op, bounded IO, trust and error-handling constraints hold; no new dependency or unrelated file is introduced.
- [ ] AC3: techwiki spec check, correct ref links and API modules, documented limits, namespace usage, hook envelopes and asset twin sync.
- [ ] AC4: All Validation Commands pass; applicable asset twins remain synchronized.

## Validation Commands

- `pytest tests/sdd_scripts/test_check_asset_sync.py -q`

## Test Specification

Required behavioral cases: techwiki spec check, correct ref links and API modules, documented limits, namespace usage, hook envelopes and asset twin sync.

Use the spec §4 payload fixtures, with deterministic temporary Git roots and PARROT_HOME. Assert state/events/outputs, including unknown outcomes and failures; mocks alone are not evidence. Each test file listed above belongs to this task. Preserve all existing regression cases in modified tests.

## Required Documentation Verification

Run `parrot sdd techwiki check --spec sdd/specs/sdd-experience-memory.spec.md --root .` and require exit 0. This is a mandatory acceptance gate in addition to the registered pytest command above. The current runner registry has no techwiki adapter, so it cannot appear in the machine-selected Validation Commands section. Record its output with task evidence; do not omit this check.

## Agent Instructions

1. Use `$sdd-start TASK-5611` and the feature worktree; do not implement on dev.
2. Verify dependencies are done in `sdd/tasks/index/sdd-experience-memory.json` and recheck this contract after they land.
3. Implement only the declared files, run validation, and commit scoped changes.
4. Use `parrot sdd task finalize` with real TaskCompletionEvidence and the exact implementation HEAD. The finalizer owns the completion note and active-to-completed move; never edit them manually.
