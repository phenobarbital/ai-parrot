# TASK-5185: Shared tri-state portability decision

**Feature**: FEAT-804 — Installer portability gaps — one root, one portable rule
**Spec**: `sdd/specs/installer-portability-gaps.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (1–2h)
**Depends-on**: TASK-5184
**Assigned-to**: unassigned

## Context

Implement the approved revision 0.4 of FEAT-804. This task owns the following bounded deliverable;
the dependency graph separates disjoint host implementations and serializes overlapping test writers.
Source references and literal edit anchors were verified at `62aaa17228` on 2026-11-05.

## Scope

- Implement spec M2 PortableDecision and resolve_portable_mode with the exact four-row precedence table.
- Own only the new decision module and focused truth-table tests appended to the existing parity suite; host adoption belongs to later tasks.

**NOT in scope**: worktree-root relocation (FEAT-802), wiki discovery redesign, non-Python worktree
provisioning, dependency additions, or edits outside the declared files. This is an implementation
task artifact; generation of this artifact makes no runtime changes.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/mcp/portability.py` | CREATE | A single pure decision boundary prevents each host from redefining the fresh-config default. |
| `packages/ai-parrot/tests/knowledge/wiki/test_portable_mode_parity.py` | MODIFY | Exercise all tri-state combinations without relying on the developer PATH. |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

Existing imports below resolve in the referenced source/test modules; `click`, `pytest` and
`pydantic` are already declared in the workspace pyproject files. Stdlib imports require no new
dependency. Imports explicitly marked with a task ID are future dependency contracts, not claims
that those symbols exist at planning HEAD. Preserve existing imports not shown in the blueprint.

```python
import dataclasses
import sys
from typing import Literal
import pytest
from parrot.launcher import managed_launcher_on_path  # provided by TASK-5184
from parrot.mcp import portability  # created by this task
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/launcher.py:24
def parrot_home(env: Mapping[str, str] | None = None) -> Path:
```

### Does NOT Exist

- parrot.mcp.portability does not exist before this task.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/mcp/portability.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/test_portable_mode_parity.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/launcher.py#parrot_home"
  ]
}
```

## Implementation Notes

TASK-5184 creates managed_launcher_on_path in launcher.py, consumed by the new decision function.

Use the approved stdlib-only launcher/decision structures from the spec. Keep public signatures
and existing ownership checks; use black (120 columns) and ruff for Python edits. New test functions
must have type hints and explanatory docstrings, matching production conventions. Keep HOME/PATH,
Google user-global config, credential probes and Git fixtures isolated under tmp_path. Never run
installers against the developer checkout/home as a test. Store test logs in artifacts/logs/.

## Implementation Blueprint

The blocks below are scoped edit plans, not wholesale replacements of existing files. CREATE
blocks are whole-file starting points; fill their bounded bodies before committing. Preserve
surrounding implementation and imports. No FILL IN or unfinished body may remain in implemented code.

### Steps (in order)

1. Revalidate listed anchors and prerequisite signatures — because dependencies or FEAT-802 may move adjacent code.
2. Apply the declared per-file edits in the order below — because caller and callee contracts must remain coherent.
3. Implement every bounded test case in Acceptance Criteria — because wiring-only spies do not verify emitted artifacts.
4. Run the Validation Commands and scoped lint — because the final state must preserve existing regression coverage.

### `packages/ai-parrot/src/parrot/mcp/portability.py` (CREATE)

New file; absence verified at planning HEAD.

```python
"""Shared command-form decision for installer emitters."""
from __future__ import annotations
import dataclasses
import sys
from typing import Literal
from parrot.launcher import managed_launcher_on_path

PortableReason = Literal["explicit", "sticky", "launcher", "baked-fallback"]

@dataclasses.dataclass(frozen=True)
class PortableDecision:
    """Chosen form, provenance and optional fallback explanation."""
    portable: bool
    reason: PortableReason
    note: str | None

BAKED_NOTE_TEMPLATE: str = (
    "note: host config baked to absolute paths ({prefix}); install the global launcher "
    "(install-parrot.sh --global) and re-run with --portable to commit a machine-independent config"
)

def resolve_portable_mode(explicit: bool | None, *, current: bool | None) -> PortableDecision:
    """Resolve explicit, sticky, launcher and baked-fallback choices in that order."""
    # FILL IN: exact spec M2 truth table; test identity with None, never truthiness.
```

**Why**: A single pure decision boundary prevents each host from redefining the fresh-config default.

### `packages/ai-parrot/tests/knowledge/wiki/test_portable_mode_parity.py` (MODIFY)

Anchor `def test_no_config_is_baked(root: Path) -> None:` — occurrences: 1; verified `packages/ai-parrot/tests/knowledge/wiki/test_portable_mode_parity.py:118`.

```python
# Append decision-only truth-table coverage; retain existing host parity tests unchanged here.
import sys
import pytest
from parrot.mcp import portability

@pytest.mark.parametrize("explicit", [None, False, True])
@pytest.mark.parametrize("current", [None, False, True])
@pytest.mark.parametrize("launcher", [False, True])
def test_resolve_portable_mode_truth_table(explicit: bool | None, current: bool | None,
                                         launcher: bool, monkeypatch: pytest.MonkeyPatch) -> None:
    """All precedence combinations produce the expected form, reason and note."""
    monkeypatch.setattr(portability, "managed_launcher_on_path", lambda: launcher)
    # FILL IN: expected values from spec truth table; assert sys.prefix and exact fallback note.
```

**Why**: Exercise all tri-state combinations without relying on the developer PATH.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/mcp/portability.py` — complete the bounded changes above and acceptance cases; retain unrelated behavior.
- [ ] `packages/ai-parrot/tests/knowledge/wiki/test_portable_mode_parity.py` — complete the bounded changes above and acceptance cases; retain unrelated behavior.

## Acceptance Criteria

- [ ] Explicit True/False beats existing form and PATH; existing True/False beats PATH.
- [ ] Fresh config follows managed launcher availability; only baked-fallback returns the exact note naming sys.prefix and --portable.
- [ ] Decision values are immutable and the module introduces no provider/dependency imports.

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_portable_mode_parity.py -q`

Run with the activated project environment and `PYTHONPATH=packages/ai-parrot/src`.
These commands are this task's relevant tests; the index carries the cached spec-wide contract.

## Test Specification

Use the cases and assertions in Acceptance Criteria and each test-file blueprint. Assert outputs,
exit statuses and before/after file snapshots as appropriate. Tests for malformed config and
worktree refusal must prove no unintended write; avoid network services and real user config.

## Agent Instructions

1. Use `$sdd-start TASK-5185` in the feature workflow; implementation belongs in its provisioned worktree.
2. Read the spec and verify dependencies are done in `sdd/tasks/index/installer-portability-gaps.json`.
3. Verify this contract before editing; refresh stale anchors explicitly rather than inventing interfaces.
4. Implement only declared files, complete every blueprint gap, run validation and scoped lint.
5. Commit only the implementation scope. Finalize through `scripts.sdd.finalize_task` with real
   TaskCompletionEvidence and exact implementation HEAD per docs/sdd/CODEX.md; never hand-edit
   the Completion Note or move this task to completed manually. Commit the resulting SDD state.

## Completion Note

Pending. The finalizer records verified implementation evidence when this task is complete.
