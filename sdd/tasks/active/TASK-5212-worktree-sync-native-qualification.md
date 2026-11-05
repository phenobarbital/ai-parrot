# TASK-5212: Qualify patch sync under the real native filesystem policy

**Feature**: FEAT-806 — Worktree Sync Base
**Spec**: `sdd/specs/worktree-sync-base.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5208
**Assigned-to**: unassigned

## Context

Spec §4 requires actual native-policy evidence: an environment flag and stubbed gh outside the sandbox cannot prove protected configuration compatibility.

## Scope

Extend the existing sync tests with a bounded real-native sandbox qualification using host-provisioned disposable worktrees and a local gh stub. Keep deterministic unit tests available everywhere, but report an unavailable native backend as an unvalidated required gate. NOT in scope: relaxing policy, provider network calls, changing native sandbox implementation or shared Git configuration.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/sdd_scripts/test_worktree_sync.py` | MODIFY | Native policy integration and protected-config canaries |

## Codebase Contract (Anti-Hallucination)

Verified at `cd57902e64`. Dependency-created symbols are explicitly identified below; verify them after dependencies land.

### Verified Imports
```python
import os
import json
import subprocess
from pathlib import Path
import pytest
from parrot.sdd.scripts import native_claude_sandbox
```
Dependency import: `from parrot.sdd.scripts import worktree_sync` (TASK-5207, completed sandbox behavior TASK-5208).

### Existing Signatures to Use
- `packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py:330`: `native_sandbox_available() -> tuple[bool, str]`.
- `packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py:388`: `native_sandbox_settings(cwd: Path, *, allowed_domains: Sequence[str] = (), include_sandbox: bool = True) -> dict[str, Any]`.
- `packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py:216`: `_denied_write_paths(root: Path, git_dir: Path) -> list[str]` protects common config and own config.worktree.
- Existing deterministic policy tests: packages/ai-parrot/tests/flows/dev_loop/test_native_claude_sandbox.py. Existing live qualification patterns: test_native_claude_sandbox_live.py in that directory; these use opt-in real Claude sessions and must not be mistaken for deterministic local tests.
- TASK-5208 adds `test_sandbox_cherry_pick_via_gh_patch` in the modified file; verify this dependency anchor after it lands.

### Does NOT Exist
- No proof of OS enforcement from setting BACKEND_ENV alone.
- No authorization to widen native deny rules or install another sandbox runtime/dependency.


## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "tests/sdd_scripts/test_worktree_sync.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py#native_sandbox_available",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py#native_sandbox_settings",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py#_denied_write_paths"
  ]
}
```

## Implementation Notes

Consumes TASK-5208 sandbox transport and modifies its test_worktree_sync.py after TASK-5208; TASK-5207 is transitively required. Uses only disposable repositories and per-test sandbox resources, not shared configuration.

Use repository tools from the activated environment; preserve shared environments. Keep changes within declared files, use typed functions and Google-style docstrings, black (120 columns), and ruff. Tests must import this worktree's source, not another editable checkout. No new dependency is authorized. CLI subprocess I/O is synchronous by design; do not introduce blocking I/O into async entry points. Run no network or destructive operations against the real repository in tests.

## Implementation Blueprint

Blueprint gaps below are planning instructions only; finished code must have no placeholders.

### Steps (in order)

1. Inspect installed native runtime and existing qualification patterns — use the repository policy without new dependencies or weaker substitutes.
2. Build disposable primary/feature/sibling repos, host setup and local gh stub — no real remote or config mutation.
3. Run sync under the actual native boundary and test protected-write canaries — successful sync alone does not prove enforcement.
4. Record bounded logs and explicit availability outcome — missing runtime is an unvalidated required gate, not a passed feature.

### `tests/sdd_scripts/test_worktree_sync.py` (MODIFY)

```python
# After TASK-5208's test_sandbox_cherry_pick_via_gh_patch (expected occurrences: 1).
# Re-read the completed dependency before editing; preserve all deterministic tests.
def test_native_policy_sync_with_protected_config(tmp_path: Path) -> None:
    """A real native sandbox applies patches without writing protected config."""
    # FILL IN: host-provision a disposable linked worktree; use repository-generated native
    # policy and the available native runtime, with local gh stub and bounded subprocess timeout.
    # Assert actual enforcement with denied config-write canaries, successful patch application,
    # unchanged common/worktree config bytes and untouched primary/sibling/remote refs.
    # Backend unavailable: record explicit unvalidated qualification; never claim feature success.


def test_native_policy_missing_protection_refuses(tmp_path: Path) -> None:
    """Missing host protection is refused without attempted config repair."""
    # FILL IN: real-policy invocation, exit 5, no download/application, exact state snapshots.
```

**Why**: The qualifying test must observe OS enforcement and the full command path, not just policy dictionaries.


### FILL IN checklist

- [ ] With an available native backend, a valid patch applies while common config and own config.worktree stay protected and byte-identical.
- [ ] Protected-write probes actually fail under OS enforcement; primary/sibling state and remote refs remain unchanged.
- [ ] Missing push protection returns 5 with no config repair or patch application under the same boundary.
- [ ] The command uses only gh remote transport; tests use a local gh stub and do not require provider/network calls.
- [ ] Unavailable runtime is explicitly recorded as an unvalidated required gate in completion evidence and blocks claiming full feature validation; deterministic suite results are reported separately.

## Acceptance Criteria

- [ ] With an available native backend, a valid patch applies while common config and own config.worktree stay protected and byte-identical.
- [ ] Protected-write probes actually fail under OS enforcement; primary/sibling state and remote refs remain unchanged.
- [ ] Missing push protection returns 5 with no config repair or patch application under the same boundary.
- [ ] The command uses only gh remote transport; tests use a local gh stub and do not require provider/network calls.
- [ ] Unavailable runtime is explicitly recorded as an unvalidated required gate in completion evidence and blocks claiming full feature validation; deterministic suite results are reported separately.
- [ ] All task validation commands pass and touched Python files pass `ruff check`; apply `black --line-length 120` to touched Python files.

## Validation Commands

- `pytest tests/sdd_scripts/test_worktree_sync.py -q`

## Test Specification

Keep a strict distinction between deterministic unit tests and native integration evidence. If the installed native boundary cannot be exercised without an actual provider session, report that limitation and required opt-in instead of silently substituting a weaker sandbox. Use finite subprocess timeouts and artifacts/logs; do not authorize live provider spending implicitly.

## Agent Instructions

1. Use `$sdd-start TASK-5212` in the FEAT-806 feature worktree; never implement on dev.
2. Verify dependencies are done in `sdd/tasks/index/worktree-sync-base.json` and revalidate contracts before editing.
3. Implement only declared files, finish every blueprint gap, and run the listed validation commands. Store logs under `artifacts/logs/`.
4. Commit implementation files, then finalize through `scripts.sdd.finalize_task` using real `TaskCompletionEvidence` and the exact implementation HEAD, following the Codex adaptation contract. Do not manually move tasks or write completion evidence.
5. Commit only the resulting task/index state. Do not push from the worker.

## Completion Note

Pending; populated by the finalization tool after implementation and validation.
