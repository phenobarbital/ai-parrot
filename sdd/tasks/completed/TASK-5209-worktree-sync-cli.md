# TASK-5209: Register the sync-base CLI verb

**Feature**: FEAT-806 — Worktree Sync Base
**Spec**: `sdd/specs/worktree-sync-base.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5207
**Assigned-to**: unassigned

## Context

M3 exposes the core entry through the installed parrot sdd CLI.

## Scope

Add only the new registry leaf and targeted tests. NOT in scope: transport behavior, parser duplication, launcher or documentation.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/cli.py` | MODIFY | Add worktree sync-base mapping |
| `packages/ai-parrot/tests/sdd/test_sdd_cli.py` | MODIFY | Dispatch/help and exit-code coverage |

## Codebase Contract (Anti-Hallucination)

Verified at `cd57902e64`. Dependency-created symbols are explicitly identified below; verify them after dependencies land.

### Verified Imports
```python
from click.testing import CliRunner
from parrot.cli import cli
from parrot.sdd.cli import sdd
import pytest
```
These imports already exist in `packages/ai-parrot/tests/sdd/test_sdd_cli.py`. click and pytest are installed project dependencies.

### Existing Signatures to Use
`packages/ai-parrot/src/parrot/sdd/cli.py:237`: VERBS maps noun/verb to `(module, fixed_args, help)`; worktree group begins :238 and remove leaf :248. Helper dispatch imports parrot.sdd.scripts module main lazily. `packages/ai-parrot/tests/sdd/test_sdd_cli.py:195`: `test_sdd_cli_mounts_every_helper() -> None` checks every helper and --help. TASK-5207 provides `worktree_sync.main(argv: Sequence[str] | None = None) -> int`.

### Does NOT Exist
- No sync-base registry leaf exists today.
- No `tests/sdd_scripts/test_sdd_cli.py`; use the verified package test path above.


## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/sdd/cli.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/sdd/test_sdd_cli.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/sdd/cli.py#VERBS"
  ]
}
```

## Implementation Notes

Consumes TASK-5207 worktree_sync.main through lazy registry dispatch; sandbox transport TASK-5208 is not required for registration/help tests.

Use repository tools from the activated environment; preserve shared environments. Keep changes within declared files, use typed functions and Google-style docstrings, black (120 columns), and ruff. Tests must import this worktree's source, not another editable checkout. No new dependency is authorized. CLI subprocess I/O is synchronous by design; do not introduce blocking I/O into async entry points. Run no network or destructive operations against the real repository in tests.

## Implementation Blueprint

Blueprint gaps below are planning instructions only; finished code must have no placeholders.

### Steps (in order)

1. Verify registry anchor — add the leaf only within worktree.
2. Exercise help and failure propagation through CliRunner — direct main calls do not prove the wiring.

### `packages/ai-parrot/src/parrot/sdd/cli.py` (MODIFY)

Anchor `"remove": (` — packages/ai-parrot/src/parrot/sdd/cli.py:248, occurrences: 1 (verified at cd57902e64).

```python
# Insert sibling entry immediately before "remove" inside VERBS["worktree"].
"sync-base": ("worktree_sync", (), "Bring origin/<base_branch> (or chosen commits) into a worktree; never pushes."),
```

**Why**: Existing lazy helper dispatch already handles argument forwarding and exit codes.

### `packages/ai-parrot/tests/sdd/test_sdd_cli.py` (MODIFY)

Anchor `def test_sdd_cli_mounts_every_helper() -> None:` — packages/ai-parrot/tests/sdd/test_sdd_cli.py:195, occurrences: 1 (verified at cd57902e64).

```python
# Append a focused test near the verified registry tests.
def test_worktree_sync_base_help() -> None:
    """The installed CLI dispatches sync-base help to its helper."""
    result = CliRunner().invoke(cli, ["sdd", "worktree", "sync-base", "--help"])
    assert result.exit_code == 0, result.output
    assert "--cherry-pick" in result.output
    assert "--dry-run" in result.output
# FILL IN: refusal exit propagation with a missing target and --json result contract.
```

**Why**: Test real click-to-helper wiring without performing a network sync.


### FILL IN checklist

- [ ] worktree sync-base --help exits 0 and advertises supported options.
- [ ] Unknown target/refusal exit codes survive click dispatch; no network or state mutation in tests.
- [ ] Existing registry completeness and all CLI tests pass.

## Acceptance Criteria

- [ ] worktree sync-base --help exits 0 and advertises supported options.
- [ ] Unknown target/refusal exit codes survive click dispatch; no network or state mutation in tests.
- [ ] Existing registry completeness and all CLI tests pass.
- [ ] All task validation commands pass and touched Python files pass `ruff check`; apply `black --line-length 120` to touched Python files.

## Validation Commands

- `pytest packages/ai-parrot/tests/sdd/test_sdd_cli.py -q`

## Test Specification

Use CliRunner and disposable/missing target for refusal; retain test_sdd_cli_mounts_every_helper.

## Agent Instructions

1. Use `$sdd-start TASK-5209` in the FEAT-806 feature worktree; never implement on dev.
2. Verify dependencies are done in `sdd/tasks/index/worktree-sync-base.json` and revalidate contracts before editing.
3. Implement only declared files, finish every blueprint gap, and run the listed validation commands. Store logs under `artifacts/logs/`.
4. Commit implementation files, then finalize through `scripts.sdd.finalize_task` using real `TaskCompletionEvidence` and the exact implementation HEAD, following the Codex adaptation contract. Do not manually move tasks or write completion evidence.
5. Commit only the resulting task/index state. Do not push from the worker.

## Completion Note

Implemented by seat gpt-5.6-sol codex, attempt 1, 182s. engine lint commit a032003fcc; merge-tier validation green (60 + 7 passed). Merged by the engine; no fidelity violations. Closed via `parrot sdd task close`
because `coder_record_review` fails server-side (no review EvidenceRef for `parrot sdd task finalize`). Delivery
checked only through the engine gate and tests, not a line-by-line review.
