# TASK-5124: Worker completion protocol and operator documentation

**Feature**: FEAT-793 — tmux worker completion notifications
**Spec**: `sdd/specs/tmux-notify-worker.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (<2h)
**Depends-on**: TASK-5123
**Assigned-to**: unassigned

## Context

Implement spec §3 M3. The worker is the explicit witness that task execution, child settlement, review and push finished; the receipt cannot be inferred from Stop or index status alone.

## Scope

- Insert the guarded --complete command between successful feature push and summary in both worker twins.
- Explicitly exclude task-scoped JSON briefs, unfinished work/review, child results, interrupts and failed pushes.
- Document automatic same-host best-effort delivery, once-per-launch behavior, asset update and open CLI lifetime.
- Add the dedicated protocol test file for the instruction/asset contract; this is the task-local test realization of spec §4.

**NOT in scope**: helper/runtime implementation, launcher changes, manifest/global asset regeneration, task-scoped completion behavior or merge/closeout approval.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.claude/agents/sdd-worker.md` | MODIFY | Feature-only receipt after successful push |
| `packages/ai-parrot/src/parrot/sdd/_assets/claude/agents/sdd-worker.md` | MODIFY | Byte-identical shipped instruction |
| `docs/dev_loop/claude-native-sandbox.md` | MODIFY | Delivery conditions and operational limitations |
| `packages/ai-parrot/tests/sdd/test_worker_notification_protocol.py` | CREATE | Protocol ordering, shell guard and asset parity tests |

## Codebase Contract (Anti-Hallucination)

Freshness checked on dev `cce37eb09570cda92d86fd1242825da3f3890426`. Re-verify after dependencies land.

### Verified Imports

```python
from __future__ import annotations
from pathlib import Path
import subprocess
import pytest
```

Path/subprocess are stdlib; pytest is already declared at `pyproject.toml:63`. No application import is required. Run the existing `scripts/sdd/check_asset_sync.py --check` using the activated Python environment; read-only checker exists at line 1.

### Existing Signatures to Use

No existing application symbol is consumed. Protocol anchors verified with `grep -Fc`:

| File | Anchor | Line | Count |
|---|---|---|---|
| `.claude/agents/sdd-worker.md` | `3. **Print summary:**` | 713 | 1 |
| `packages/ai-parrot/src/parrot/sdd/_assets/claude/agents/sdd-worker.md` | `3. **Print summary:**` | 713 | 1 |
| `docs/dev_loop/claude-native-sandbox.md` | `## Supported launch paths` | 24 | 1 |

Both worker files are byte-identical. Feature `## Completion` starts at line 617; step 2 at line 708 pushes with `git push origin HEAD`, followed by step 3. Task-scoped handling is separately defined at line 121. Existing manifest at `packages/ai-parrot/src/parrot/sdd/_assets/manifest.json:341` already ships this worker; do not modify the manifest.

Dependency contract: TASK-5123 exports PARROT_SDD_NOTIFY_PYTHON and PARROT_SDD_NOTIFY_HELPER for configured launches; transitively TASK-5122 supplies `--complete`. These are planned interfaces to re-check after dependencies land.

### Does NOT Exist

- Neither worker twin has a notification completion instruction yet.
- `packages/ai-parrot/tests/sdd/test_worker_notification_protocol.py` does not exist; this task owns the new test file.
- Stop itself is not a completion detector; no task-scoped receipt or process-exit notification is introduced.


## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": ".claude/agents/sdd-worker.md",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/sdd/_assets/claude/agents/sdd-worker.md",
      "action": "MODIFY"
    },
    {
      "path": "docs/dev_loop/claude-native-sandbox.md",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/sdd/test_worker_notification_protocol.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

## Implementation Notes

Consumes PARROT_SDD_NOTIFY_PYTHON and PARROT_SDD_NOTIFY_HELPER exports from TASK-5123 and transitively the TASK-5122 --complete CLI. Owns both worker assets, operator documentation and a separate protocol test file; no overlapping writers.

Follow the spec’s stdlib-only host-script boundary; this is synchronous CLI work, not an async application I/O path. Add no dependencies. Do not change sandbox permissions. Blueprint gaps below are planning markers; completed implementation must contain none.

## Implementation Blueprint

### Steps (in order)

1. Insert a feature-only guarded receipt after successful push — because the worker protocol, not the hook, attests completed review and push.
2. Apply identical text to the shipped twin — because installed users execute the packaged asset.
3. Document service requirements and best-effort semantics — because at-most-once attempts are not guaranteed desktop delivery.
4. Test ordering, variable guards and parity — because a prose placement regression could announce incomplete work.

### `.claude/agents/sdd-worker.md` (MODIFY)

````markdown
<!-- BEFORE `3. **Print summary:**`; occurrences: 1; verified .claude/agents/sdd-worker.md:713 -->
2a. **Record optional desktop completion (feature scope only).** Only after all
    tasks are done, children have settled, review/deferred-finding handling is
    complete and step 2 pushed successfully, run from the feature worktree:
    ```bash
    if [ -n "${PARROT_SDD_NOTIFY_PYTHON:-}" ] && [ -n "${PARROT_SDD_NOTIFY_HELPER:-}" ]; then
      "$PARROT_SDD_NOTIFY_PYTHON" -S "$PARROT_SDD_NOTIFY_HELPER" --complete
    fi
    ```
    Never run this in task-scoped JSON brief mode, for child completion,
    interrupts, blocked/unfinished tasks, unfinished review or a failed push.
    A recording failure is advisory: log it and continue the final summary;
    never widen sandbox permissions or retry outside the sandbox. The helper's
    warning is the diagnostic even when its best-effort CLI exits zero.
    The next eligible Stop event attempts delivery while Claude remains open.
````

**Why**: Preserve existing completion steps and task-scoped exit paths; the new instruction is subordinate to successful step 2.

### `packages/ai-parrot/src/parrot/sdd/_assets/claude/agents/sdd-worker.md` (MODIFY)

````markdown
<!-- BEFORE `3. **Print summary:**`; occurrences: 1; verified packages/ai-parrot/src/parrot/sdd/_assets/claude/agents/sdd-worker.md:713 -->
2a. **Record optional desktop completion (feature scope only).** Only after all
    tasks are done, children have settled, review/deferred-finding handling is
    complete and step 2 pushed successfully, run from the feature worktree:
    ```bash
    if [ -n "${PARROT_SDD_NOTIFY_PYTHON:-}" ] && [ -n "${PARROT_SDD_NOTIFY_HELPER:-}" ]; then
      "$PARROT_SDD_NOTIFY_PYTHON" -S "$PARROT_SDD_NOTIFY_HELPER" --complete
    fi
    ```
    Never run this in task-scoped JSON brief mode, for child completion,
    interrupts, blocked/unfinished tasks, unfinished review or a failed push.
    A recording failure is advisory: log it and continue the final summary;
    never widen sandbox permissions or retry outside the sandbox. The helper's
    warning is the diagnostic even when its best-effort CLI exits zero.
    The next eligible Stop event attempts delivery while Claude remains open.

<!-- Apply exactly the same inserted prose/command as the source; no manifest regeneration. -->
````

**Why**: Copy only the declared worker source change; the manifest already includes this asset.

### `docs/dev_loop/claude-native-sandbox.md` (MODIFY)

````markdown
<!-- BEFORE `## Supported launch paths`; occurrences: 1; verified claude-native-sandbox.md:24 -->
## Tmux feature completion notifications

New `parrot sdd launch worker FEAT-ID --tmux` sessions automatically enable
best-effort host desktop notifications. The feature worker records completion
only after its tasks, child settlement, review/deferred findings and successful
feature-branch push. A host Stop hook consumes that explicit receipt; ordinary
pauses and task-scoped workers do not announce completion. This is worker
completion, not merge approval or successful `/sdd-done` closeout.

Claude Code and its pane remain open. Delivery needs `notify-send` and a usable
desktop session on the same host; SSH/headless hosts may show nothing. Nothing
is installed. Missing services and delivery failures never fail the worker.
One launch permits at most one attempt, including failed delivery; reattach does
not install new hooks or resend. Updating an existing installation's managed
worker asset is required to obtain the receipt instruction; launch a new session.

The launch captures only PATH, HOME, DISPLAY, WAYLAND_DISPLAY,
DBUS_SESSION_BUS_ADDRESS and XDG_RUNTIME_DIR from the operator environment.
Host delivery runs outside the worker's Bash sandbox; sandbox permissions and
socket grants stay unchanged. A changed HEAD invalidates a recorded receipt.
````

**Why**: Describe observable behavior without promising a popup on hosts lacking a local desktop.

### `packages/ai-parrot/tests/sdd/test_worker_notification_protocol.py` (CREATE)

```python
"""Qualify the feature-only notification instruction and its installed twin."""
from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[4]
SOURCE = ROOT / ".claude/agents/sdd-worker.md"
SHIPPED = ROOT / "packages/ai-parrot/src/parrot/sdd/_assets/claude/agents/sdd-worker.md"


def test_worker_notification_protocol_order() -> None:
    """Only feature completion records after push and before the final summary."""
    # FILL IN: isolate feature Completion section; assert single quoted --complete
    # invocation between successful push and summary with explicit exclusions; AC-1.


def test_notification_worker_asset_matches_source() -> None:
    """Source and installed worker bytes implement the same protocol."""
    assert SOURCE.read_bytes() == SHIPPED.read_bytes()


def test_completion_command_is_guarded(tmp_path: Path) -> None:
    """Execute the extracted command with fake helpers, absent vars and spaced paths."""
    # FILL IN: extract the fenced shell block, invoke bash with isolated env and
    # recording fake Python/helper; assert both vars required and literal -S/--complete;
    # fail the fake helper and verify no privilege-widening fallback; AC-1/AC-3.


def test_operator_notification_documentation() -> None:
    """Document feature completion, same-host delivery and CLI lifetime accurately."""
    # FILL IN: check required operator concepts without locking incidental wording; AC-2.
```

**Why**: Use structural ordering and executable guard assertions, with no Claude or desktop dependency.

### FILL IN checklist

- [ ] Verify insertion remains feature-only and the quoted command is identical in both assets.
- [ ] Complete protocol-order, extracted-shell, parity and documentation tests.
- [ ] Run the read-only asset sync check without regenerating unrelated assets.

## Acceptance Criteria

- [ ] AC-1: Exactly one guarded --complete invocation appears after successful push and before summary in feature Completion. Explicit exclusions cover task-scoped briefs, children, interrupts, blocked/unfinished work, incomplete review and failed pushes.
- [ ] AC-2: Source/shipped worker bytes match; docs explain same-host optional notify-send, automatic new tmux launch setup, one attempt per launch, no reattach retrofit/replay, asset update requirement, stale HEAD behavior and open CLI/pane lifetime.
- [ ] AC-3: Absent either exported variable skips the command; quoted paths preserve spaces and literal argv. Recording failure remains advisory with logging and no retries or sandbox widening. Existing completion steps and task-scoped path remain intact.
- [ ] AC-4: Protocol tests pass and `python scripts/sdd/check_asset_sync.py --check` passes; record logs under artifacts/logs. No unrelated assets or manifest edits.

## Validation Commands

- `pytest packages/ai-parrot/tests/sdd/test_worker_notification_protocol.py -q`

## Test Specification

Assert source/shipped parity and structural placement within feature Completion. Execute only the extracted guarded Bash snippet with a local fake executable under a minimal environment: neither variable, either variable alone, both with spaces/metacharacters, and helper failure. Check excluded scope language without hard-coding complete paragraphs. In addition to the registered pytest command, run the mandatory read-only asset checker from the activated environment; do not put this non-runner command in Validation Commands.

## Agent Instructions

1. Use `$sdd-start TASK-5124` in the FEAT-793 feature worktree; never implement on dev.
2. Read the spec, verify dependencies are done in `sdd/tasks/index/tmux-notify-worker.json`, and re-check this contract before editing.
3. Follow the implementation blueprint and complete all bounded gaps; modify only declared files.
4. Run the Validation Commands and applicable formatting/lint checks; save test logs under `artifacts/logs/`.
5. Commit only scoped implementation files. Follow the Codex adaptation contract: finalize through `scripts.sdd.finalize_task` with real `TaskCompletionEvidence` and the exact implementation HEAD. The finalizer owns the Completion Note and active-to-completed move; do not edit or move them manually.

## Completion Note

Implemented by seat qwen (nova), attempt 1 on the third dispatch, 183s, 48 turns. Earlier dispatches on mistral and glm failed (turn budget exhausted / invalid tool-name 400). Orchestrator review of the worker-instruction twins, docs and diff found no defects (coder-review:82fdfef2fa8335efef34b3ff); twins are byte-identical. Merge-tier validation: 4 passed (test_worker_notification_protocol.py). Closed with `parrot sdd task close` (the finalizer needs an EvidenceRef for review evidence, which coder_record_review does not return).
