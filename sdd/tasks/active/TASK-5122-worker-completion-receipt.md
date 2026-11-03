# TASK-5122: Completion receipt and host notifier

**Feature**: FEAT-793 — tmux worker completion notifications
**Spec**: `sdd/specs/tmux-notify-worker.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: none
**Assigned-to**: unassigned

## Rework Notice (attempt 2, after review)

Both files already exist from a rejected first delivery (qwen) and are now MODIFY targets. The existing code is a happy-path draft and MUST be reworked to satisfy every AC below. Confirmed gaps to fix:
- `main()` returns 1 on invalid input/operational failure; AC-4/AC-5 require exit 0, empty stdout, at most one concise warning.
- Missing validation: symlinked state files/cache, UUID-v4 cache name, 0700 cache mode, `schema_version == 1` and field types on context AND receipt, index path containment under the worktree, exact context fields from spec §2, oversize/malformed JSON.
- `handle_stop` must not require `slug` outside the validated context, must use captured desktop env only (`env=` exact title/body from spec), and must claim `notify-attempted` with `os.open(O_CREAT|O_EXCL, 0o600)`.
- Tests are happy-path only. Replace with the full spec §4 matrix: real competing `--hook` subprocesses for the claim race, `python -S` runs with a fake `notify-send` capturing argv/env, a living fake CLI process, poisoned ambient env, metacharacter/space paths, stale HEAD, fresh UUID, symlink and escaping-index rejection, mode checks. Remove the assertion that invalid input returns nonzero.
Read the spec (`sdd/specs/tmux-notify-worker.spec.md`) §2–§4 in full before editing.

## Context

Implement spec §2 launch/delivery contract and §3 M1. Completion is explicitly recorded after review and push; a Stop event alone is never proof of completion.

## Scope

- Implement the four fixed helper interfaces, private validation helpers and internal CLI.
- Use version-1 context/receipt documents, existing launch UUID and cache; validate types, paths and feature identity.
- Gate one bounded host delivery on an explicit valid receipt and exclusive attempt marker.
- Cover all negative paths and an isolated `python -S` integration with a living fake CLI.

**NOT in scope**: launcher wiring, worker instruction edits, desktop installation, process-exit hooks, remote delivery or review/push verification.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/scripts/worker_notification.py` | MODIFY | Stdlib receipt and Stop delivery helper |
| `packages/ai-parrot/tests/sdd/test_worker_notification.py` | MODIFY | Runtime, failure and concurrency tests |

## Codebase Contract (Anti-Hallucination)

Freshness checked on dev `cce37eb09570cda92d86fd1242825da3f3890426`. Re-verify after dependencies land.

### Verified Imports

```python
from __future__ import annotations
import argparse
import html
import importlib.util
import json
import logging
import os
from pathlib import Path
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
from typing import Mapping, Sequence
import uuid
from types import ModuleType
import pytest
```

All except pytest are Python stdlib; Python >=3.11 is declared in `packages/ai-parrot/pyproject.toml:18`. Pytest is already declared at `pyproject.toml:63`. Test-only `importlib.util` loads the helper by its current checkout path without importing parrot. Do not import pytest into the helper.

### Existing Signatures to Use

No existing project symbol is imported or called. New interfaces are fixed by spec §3 M1:

```python
def configure_notification(cache: Path, *, worktree: Path, env: Mapping[str, str]) -> str | None:
    """Write validated launch context and return the quoted Stop command."""
def record_completion(env: Mapping[str, str]) -> bool:
    """Record explicit eligible completion in the session cache."""
def handle_stop(payload: Mapping[str, object], *, cache: Path) -> None:
    """Attempt delivery for a valid Stop and receipt."""
def main(argv: Sequence[str] | None = None) -> int:
    """Dispatch internal modes, returning zero for operational failures."""
```

Verified data references: `sdd/tasks/index/composite-datasets.json:17` uses task status `done`; native cache allocation at `packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py:700` uses UUID-v4 directory names, 0700 mode and `owner.pid`. Preserve that lifecycle; this task does not allocate another cache.

### Does NOT Exist

- `packages/ai-parrot/src/parrot/sdd/scripts/worker_notification.py` and `packages/ai-parrot/tests/sdd/test_worker_notification.py` do not exist before this task.
- There is no launcher completion callback: detached startup is not completion.
- `notify-send` is an external optional executable, not a Python dependency or tmux command.


## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/sdd/scripts/worker_notification.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/sdd/test_worker_notification.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": []
}
```

## Implementation Notes

No dependencies; owns new worker_notification.py and test_worker_notification.py. All Git, process and filesystem fixtures are temporary and isolated.

Follow the spec’s stdlib-only host-script boundary; this is synchronous CLI work, not an async application I/O path. Add no dependencies. Do not change sandbox permissions. Blueprint gaps below are planning markers; completed implementation must contain none.

## Implementation Blueprint

### Steps (in order)

1. Implement strict state validation first — because a forged path or stale receipt must not become a completion event.
2. Implement recording and the atomic delivery claim — because overlapping Stop events must produce at most one attempt.
3. Implement bounded host argv delivery and CLI error containment — because desktop failures must never fail or control Claude.
4. Test via current-checkout script paths and fake executables — because editable installs and real desktop services would hide packaging or environment bugs.

### `packages/ai-parrot/src/parrot/sdd/scripts/worker_notification.py` (CREATE)

```python
"""Best-effort feature completion receipts and host desktop delivery (stdlib only)."""
from __future__ import annotations

import argparse
import html
import json
import logging
import os
from pathlib import Path
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
from typing import Mapping, Sequence
import uuid

logger = logging.getLogger(__name__)
DESKTOP_KEYS = (
    "PATH", "HOME", "DISPLAY", "WAYLAND_DISPLAY",
    "DBUS_SESSION_BUS_ADDRESS", "XDG_RUNTIME_DIR",
)
MAX_PAYLOAD_BYTES = 64 * 1024


def configure_notification(cache: Path, *, worktree: Path, env: Mapping[str, str]) -> str | None:
    """Write validated launch context; return a quoted Stop command or None."""
    # FILL IN: strict metadata/root/index validation and 0600 context write; AC-1/AC-5.
    # FILL IN: shlex.join([absolute interpreter, '-S', installed script,
    # '--hook', '--cache', absolute cache]); no parrot imports; AC-5.


def record_completion(env: Mapping[str, str]) -> bool:
    """Atomically record eligible feature completion in the existing session cache."""
    # FILL IN: use PARROT_SDD_CACHE_DIR, validate context and current Git root/HEAD,
    # require matching index identity, nonempty all-done tasks; AC-1/AC-2.
    # FILL IN: atomic 0600 receipt replacement, never reset notify-attempted; AC-3.


def handle_stop(payload: Mapping[str, object], *, cache: Path) -> None:
    """Attempt one notification for a valid receipt without propagating operational errors."""
    # FILL IN: validate Stop payload/context/receipt/root/HEAD and defer busy CLI; AC-2.
    # FILL IN: exclusive notify-attempted claim before subprocess; AC-3.
    # FILL IN: captured desktop env only, argv/markup safety, 3s timeout; AC-4.


def main(argv: Sequence[str] | None = None) -> int:
    """Dispatch complete/hook mode; return zero on success, skip, or notification failure."""
    # FILL IN: mutually exclusive modes, bounded binary stdin read and strict JSON;
    # empty stdout and concise logger warning on operational failure; AC-4/AC-5.


if __name__ == "__main__":
    raise SystemExit(main())
```

**Why**: Keep all runtime imports stdlib-compatible with python -S; private helpers may be added with complete types and Google-style docstrings.

### `packages/ai-parrot/tests/sdd/test_worker_notification.py` (CREATE)

```python
"""Deterministic stdlib receipt and desktop-hook tests; no desktop or Claude required."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid
from types import ModuleType

import pytest

HELPER = Path(__file__).resolve().parents[2] / "src/parrot/sdd/scripts/worker_notification.py"


@pytest.fixture
def notification_module() -> ModuleType:
    """Load this checkout's helper without importing parrot in child interpreters."""
    # FILL IN: return a types.ModuleType loaded from HELPER; AC-5.


def test_completion_and_stop_keep_cli_alive(tmp_path: Path) -> None:
    """A fake host notifier is called once while an independent CLI fixture stays alive."""
    # FILL IN: temporary Git repo/index/cache, fake notify-send capturing argv/env,
    # python -S --complete, --hook subprocesses, process lifetime assertions; AC-1/AC-5.


def test_overlapping_stop_claims_once(tmp_path: Path) -> None:
    """Concurrent hooks and repeated recording cannot issue a second notification."""
    # FILL IN: overlapping processes, one persistent claim and one fake call; AC-3.


def test_invalid_state_is_nonblocking(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Malformed/stale state and delivery errors are safe and quiet."""
    # FILL IN: parameterize the negative and delivery matrix below; AC-2/AC-4.
```

**Why**: The test fixture owns local Git state and subprocess lifetimes; it must clean up every child without relying on a desktop.

### FILL IN checklist

- [ ] Implement context/receipt field and filesystem checks from spec §2.
- [ ] Implement atomic state replacement and exclusive claim, including races and repeated --complete.
- [ ] Complete CLI payload limits, delivery failure containment and the full test matrix.

## Acceptance Criteria

- [ ] AC-1: Valid feature metadata and nonempty all-done tasks at the current worktree produce a 0600 receipt with schema_version, launch_id, feature_id, worktree and current HEAD; context uses the exact spec fields and 0700 existing cache.
- [ ] AC-2: No receipt, partial/blocked/empty tasks, wrong feature/root/UUID/HEAD, malformed or oversized JSON, symlink state or escaping index path never deliver. Require hook_event_name Stop; nonempty background_tasks/session_crons defer without claiming; absent optional fields permit a valid receipt.
- [ ] AC-3: Exclusive notify-attempted creation precedes sending; concurrent hooks, repeated Stop and repeated --complete never reset the claim. A fresh launch UUID has independent state.
- [ ] AC-4: Use captured allowlisted env only; resolve notify-send from captured PATH or platform default when absent. Use literal argv, shell=False, timeout=3, normal urgency, app AI-Parrot SDD, exact title and escaped body from spec. Missing executable, nonzero exit, D-Bus/timeout/filesystem failures return zero, empty stdout, at most one concise warning with no secrets.
- [ ] AC-5: Helper runs with python -S outside the monorepo; hook command uses shlex.join and absolute installed paths. Read no more than 64 KiB plus one overflow-detection byte; malformed arguments/input are nonblocking. All helper subprocesses are bounded so hook execution fits the five-second hook budget; a living CLI remains alive after delivery.

## Validation Commands

- `pytest packages/ai-parrot/tests/sdd/test_worker_notification.py -q`

## Test Specification

Use isolated temporary Git repositories with explicit local author configuration, one version-1 index, UUID cache and fake notify-send executable. Cover every row in spec §4; use real competing hook subprocesses for the claim race. Exercise missing desktop keys, a poisoned ambient environment, shell/markup metacharacters, paths with spaces, stale HEAD and fresh UUID. Verify state modes and symlink rejection for each state file and index containment. Assert stderr never includes environment contents or subprocess output, stdout is empty and exit status is zero on invalid input and operational failures. No network, real Claude or notification service.

## Agent Instructions

1. Use `$sdd-start TASK-5122` in the FEAT-793 feature worktree; never implement on dev.
2. Read the spec, verify dependencies are done in `sdd/tasks/index/tmux-notify-worker.json`, and re-check this contract before editing.
3. Follow the implementation blueprint and complete all bounded gaps; modify only declared files.
4. Run the Validation Commands and applicable formatting/lint checks; save test logs under `artifacts/logs/`.
5. Commit only scoped implementation files. Follow the Codex adaptation contract: finalize through `scripts.sdd.finalize_task` with real `TaskCompletionEvidence` and the exact implementation HEAD. The finalizer owns the Completion Note and active-to-completed move; do not edit or move them manually.

## Completion Note

Pending; populated by the evidence-backed finalizer.
