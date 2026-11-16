# TASK-5588: Bounded experience file IO and failure signatures

**Feature**: FEAT-887 — SDD Experience Memory (experience.pitfall)
**Spec**: `sdd/specs/sdd-experience-memory.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

## Context

Implement Module 1 of the approved spec, with §2 behavioral contracts and §4 regression coverage. This task is a bounded portion of that module; its file table is authoritative.

## Scope

Implement stdlib-only command parsing, normalization, redaction, safe append, bounded session updates and shared-root resolution. Use a stable lock inode across atomic session replacement; reject symlinks, special files and serialized events above 4096 bytes. Parse agy exit codes only before Command output:.

**NOT in scope**: Other task-owned files, new dependencies, changing public signatures fixed by the spec, or implementing the future procedure plane.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/experience/__init__.py` | CREATE | Scoped deliverable |
| `packages/ai-parrot/src/parrot/knowledge/wiki/experience/fastpath.py` | CREATE | Scoped deliverable |
| `packages/ai-parrot/tests/knowledge/wiki/experience/test_fastpath.py` | CREATE | Task-specific regression coverage |

## Codebase Contract

Verified against `0c5acf0915`. Existing references below were re-read during decomposition. New experience imports are dependency-provided interfaces, not claims of pre-existing code.

### Verified Imports

```python
from __future__ import annotations
from collections.abc import Callable, Mapping
from parrot.knowledge.wiki.experience import fastpath
from pathlib import Path
from typing import Any
import pytest
```

Standard-library imports use Python's installed library; Pydantic v2 is declared in packages/ai-parrot/pyproject.toml and pytest in root pyproject.toml. Existing project symbols are anchored below. New symbols are fixed by the matching producer blueprint and must be verified after dependencies land.

### Existing Signatures to Use

- `sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#find_shared_root` — `packages/ai-parrot/src/parrot/knowledge/wiki/project.py:1563`
```python
def find_shared_root(start: Path | None = None) -> Path | None:
```

- `sym:packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py#load_prefix_mcp_config` — `packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py:1100`
```python
def load_prefix_mcp_config(cwd: Path) -> dict[str, Any]:
```

### Dependency Interfaces

Independent fastpath files; no shared state outside declared targets.

### Does NOT Exist

- `packages/ai-parrot/src/parrot/knowledge/wiki/experience/__init__.py` — absent at 0c5acf0915; supplied by this task or its declared predecessor.
- `packages/ai-parrot/src/parrot/knowledge/wiki/experience/fastpath.py` — absent at 0c5acf0915; supplied by this task or its declared predecessor.
- `packages/ai-parrot/tests/knowledge/wiki/experience/test_fastpath.py` — absent at 0c5acf0915; supplied by this task or its declared predecessor.
- `parrot sdd task start` is not a CLI verb; task-start priming is workflow prose.
- Experience functionality is new; imported producer symbols must be rechecked after dependencies land.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/experience/__init__.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/experience/fastpath.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/experience/test_fastpath.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#find_shared_root",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py#load_prefix_mcp_config"
  ]
}
```

## Implementation Notes

Use async service calls and bounded IO. Keep stdlib hook imports lazy, preserve the exception/cancellation semantics of callers, and log through the module logger. Blueprint gaps are planning instructions only: delivered code must contain no unfinished placeholders. All tests use temporary roots; do not mutate real global experience data. Each asset writer owns its packaged twins.

## Implementation Blueprint

### Steps (in order)

1. Verify the existing anchors and dependency interfaces — they fix the allowed integration surface.
2. Apply the per-file starting points and complete the scoped behavior — Implement stdlib-only command parsing, normalization, redaction, safe append, bounded session updates and shared-root resolution. Use a stable lock inode across atomic session replacement; reject symlinks, special files and serialized events above 4096 bytes. Parse agy exit codes only before Command output:.
3. Exercise the listed failure and boundary cases — these protect the feature's event, sandbox and host contracts.
4. Run the task's validation commands and inspect the diff — commit only declared files and task state.

### `packages/ai-parrot/src/parrot/knowledge/wiki/experience/__init__.py` (CREATE)

```python
"""Experience memory package; keep initialization free of eager imports."""
```

**Why**: This file owns the fastpath behavior described in Scope. Preserve its existing callers and complete only the bounded cases in this task.

### `packages/ai-parrot/src/parrot/knowledge/wiki/experience/fastpath.py` (CREATE)

```python
"""fastpath experience component."""
from __future__ import annotations
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

EXPERIENCE_DIR = Path('.parrot') / 'experience'
EVENTS_FILE = 'events.jsonl'
TRIGGERS_FILE = 'triggers.json'
SESSIONS_DIR = 'sessions'
MAX_EVENT_BYTES = 4096

def safe_open(path: Path, flags: int) -> int | None:
    """os.open with O_NOFOLLOW | O_NONBLOCK added; None unless the result is a regular file."""
    # FILL IN: implement the documented contract; bounded by Scope and AC1-AC3.

def session_file(plane_dir: Path, session_key: str) -> Path:
    """plane_dir/sessions/<sha1(session_key)[:16]>.json — keys are never path components."""
    # FILL IN: implement the documented contract; bounded by Scope and AC1-AC3.

def update_session(plane_dir: Path, session_key: str, mutate: Callable[[dict], dict], *, timeout_s: float=1.0) -> dict | None:
    """Lock the session file (fcntl, bounded wait), apply mutate, write temp + rename."""
    # FILL IN: implement the documented contract; bounded by Scope and AC1-AC3.

def agy_exit_code(tool_output: str) -> int | None:
    """Exit code from agy's host-owned header only: match `^Command exited with code (\\d+)\\.$`"""
    # FILL IN: implement the documented contract; bounded by Scope and AC1-AC3.

def leading_command(command: str) -> tuple[str, str]:
    """Return (executable basename, subcommand) of the first real command segment."""
    # FILL IN: implement the documented contract; bounded by Scope and AC1-AC3.

def normalize_error(text: str) -> str:
    """Return the error text with volatile parts removed and whitespace collapsed (<= 300 chars)."""
    # FILL IN: implement the documented contract; bounded by Scope and AC1-AC3.

def redact(text: str) -> str:
    """Mask secrets: tokens, bearer headers, URL credentials, long hex/base64 runs, KEY=value pairs."""
    # FILL IN: implement the documented contract; bounded by Scope and AC1-AC3.

def failure_signature(executable: str, subcommand: str, error: str) -> str:
    """Return 'executable|subcommand|normalize_error(error)'."""
    # FILL IN: implement the documented contract; bounded by Scope and AC1-AC3.

def lesson_id_for(signature: str) -> str:
    """Return 'pit-' + sha1(signature)[:12]."""
    # FILL IN: implement the documented contract; bounded by Scope and AC1-AC3.

def resolve_plane_dir(cwd: Path) -> Path | None:
    """Return <shared-root>/.parrot/experience for cwd, or None outside a git checkout."""
    # FILL IN: implement the documented contract; bounded by Scope and AC1-AC3.

def append_event(plane_dir: Path, record: Mapping[str, Any]) -> bool:
    """Append one JSON line (O_APPEND via safe_open, then fsync)."""
    # FILL IN: implement the documented contract; bounded by Scope and AC1-AC3.

def load_triggers(plane_dir: Path, *, max_bytes: int) -> dict[str, list[dict[str, Any]]]:
    """executable → lesson stubs (lesson_id, state, solution_rev, subcommand, error tokens,"""
    # FILL IN: implement the documented contract; bounded by Scope and AC1-AC3.
```

**Why**: This file owns the fastpath behavior described in Scope. Preserve its existing callers and complete only the bounded cases in this task.

### `packages/ai-parrot/tests/knowledge/wiki/experience/test_fastpath.py` (CREATE)

```python
"""Deterministic experience-memory regression tests."""
from pathlib import Path
import pytest
from parrot.knowledge.wiki.experience import fastpath

def test_leading_command_skips_wrappers(tmp_path: Path) -> None:
    """Verify leading command skips wrappers. """
    # FILL IN: arrange isolated fixtures and assert behavior, including failure paths;
    # use Test Specification and AC1-AC3, never a tautological/mock-only assertion.

def test_leading_command_unwraps_shell_c(tmp_path: Path) -> None:
    """Verify leading command unwraps shell c. """
    # FILL IN: arrange isolated fixtures and assert behavior, including failure paths;
    # use Test Specification and AC1-AC3, never a tautological/mock-only assertion.

def test_normalize_error_strips_volatile(tmp_path: Path) -> None:
    """Verify normalize error strips volatile. """
    # FILL IN: arrange isolated fixtures and assert behavior, including failure paths;
    # use Test Specification and AC1-AC3, never a tautological/mock-only assertion.

def test_redact_masks_secrets(tmp_path: Path) -> None:
    """Verify redact masks secrets. """
    # FILL IN: arrange isolated fixtures and assert behavior, including failure paths;
    # use Test Specification and AC1-AC3, never a tautological/mock-only assertion.

def test_append_event_rejects_oversize(tmp_path: Path) -> None:
    """Verify append event rejects oversize. """
    # FILL IN: arrange isolated fixtures and assert behavior, including failure paths;
    # use Test Specification and AC1-AC3, never a tautological/mock-only assertion.

def test_safe_open_rejects_symlink_and_fifo(tmp_path: Path) -> None:
    """Verify safe open rejects symlink and fifo. """
    # FILL IN: arrange isolated fixtures and assert behavior, including failure paths;
    # use Test Specification and AC1-AC3, never a tautological/mock-only assertion.

def test_update_session_concurrent(tmp_path: Path) -> None:
    """Verify update session concurrent. """
    # FILL IN: arrange isolated fixtures and assert behavior, including failure paths;
    # use Test Specification and AC1-AC3, never a tautological/mock-only assertion.

def test_agy_exit_code_header_only(tmp_path: Path) -> None:
    """Verify agy exit code header only. """
    # FILL IN: arrange isolated fixtures and assert behavior, including failure paths;
    # use Test Specification and AC1-AC3, never a tautological/mock-only assertion.
```

**Why**: This file owns the fastpath behavior described in Scope. Preserve its existing callers and complete only the bounded cases in this task.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/knowledge/wiki/experience/__init__.py` — finish its marked branches/examples using Scope and Test Specification.
- [ ] `packages/ai-parrot/src/parrot/knowledge/wiki/experience/fastpath.py` — finish its marked branches/examples using Scope and Test Specification.
- [ ] `packages/ai-parrot/tests/knowledge/wiki/experience/test_fastpath.py` — finish its marked branches/examples using Scope and Test Specification.

## Acceptance Criteria

- [ ] AC1: All declared files implement Scope using the spec's exact public interfaces; existing behavior remains compatible.
- [ ] AC2: The stated no-op, bounded IO, trust and error-handling constraints hold; no new dependency or unrelated file is introduced.
- [ ] AC3: wrappers, shell -c, volatile errors, secret masking, concurrent process mutations, malformed files, symlink/FIFO refusal, hashed session names, oversized multibyte events, shared-root worktrees and stdlib-only import.
- [ ] AC4: All Validation Commands pass; applicable asset twins remain synchronized.

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/experience/test_fastpath.py -q`

## Test Specification

Required behavioral cases: wrappers, shell -c, volatile errors, secret masking, concurrent process mutations, malformed files, symlink/FIFO refusal, hashed session names, oversized multibyte events, shared-root worktrees and stdlib-only import.

Use the spec §4 payload fixtures, with deterministic temporary Git roots and PARROT_HOME. Assert state/events/outputs, including unknown outcomes and failures; mocks alone are not evidence. Each test file listed above belongs to this task. Preserve all existing regression cases in modified tests.

## Agent Instructions

1. Use `$sdd-start TASK-5588` and the feature worktree; do not implement on dev.
2. Verify dependencies are done in `sdd/tasks/index/sdd-experience-memory.json` and recheck this contract after they land.
3. Implement only the declared files, run validation, and commit scoped changes.
4. Use `parrot sdd task finalize` with real TaskCompletionEvidence and the exact implementation HEAD. The finalizer owns the completion note and active-to-completed move; never edit them manually.
