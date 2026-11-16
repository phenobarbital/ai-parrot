# TASK-5596: Host hook runtime and launcher fast path

**Feature**: FEAT-887 — SDD Experience Memory (experience.pitfall)
**Spec**: `sdd/specs/sdd-experience-memory.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5595
**Assigned-to**: unassigned

## Context

Implement Module 4 of the approved spec, with §2 behavioral contracts and §4 regression coverage. This task is a bounded portion of that module; its file table is authoritative.

## Scope

Implement main, host payload extraction, transcript-tail joins and response envelopes from M4; use shared transitions. Agy PostToolUse queues commands and PostInvocation resolves them. Unknown outcomes produce no evidence. Insert launcher fast path before Click fallback, including isolated -m entry. Hooks read only bounded published triggers/session state, never refresh, graduate or export. On normal known outcomes, adapt to an immutable stdlib record with command/ok/error/observation_id attributes; do not import the Pydantic CommandOutcome at runtime.

**NOT in scope**: Other task-owned files, new dependencies, changing public signatures fixed by the spec, or implementing the future procedure plane.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/scripts/experience_hook.py` | CREATE | Scoped deliverable |
| `packages/ai-parrot/src/parrot/launcher.py` | MODIFY | Scoped deliverable |
| `packages/ai-parrot/tests/sdd/test_experience_hook.py` | CREATE | Task-specific regression coverage |
| `packages/ai-parrot/tests/sdd/test_launcher_experience_fast_path.py` | CREATE | Task-specific regression coverage |

## Codebase Contract

Verified against `0c5acf0915`. Existing references below were re-read during decomposition. New experience imports are dependency-provided interfaces, not claims of pre-existing code.

### Verified Imports

```python
from __future__ import annotations
from collections.abc import Mapping, Sequence
from parrot.knowledge.wiki.experience.fastpath import load_triggers, safe_open, update_session
from parrot.knowledge.wiki.experience.transitions import on_outcome
from parrot.sdd.scripts import experience_hook
from parrot.sdd.scripts.experience_hook import main
from pathlib import Path
from typing import Any
import pytest
import sys
```

Standard-library imports use Python's installed library; Pydantic v2 is declared in packages/ai-parrot/pyproject.toml and pytest in root pyproject.toml. Existing project symbols are anchored below. New symbols are fixed by the matching producer blueprint and must be verified after dependencies land.

### Existing Signatures to Use

- `sym:packages/ai-parrot/src/parrot/launcher.py#main_parrot` — `packages/ai-parrot/src/parrot/launcher.py:357`
```python
def main_parrot() -> int:
```

### Dependency Interfaces

hooks: TASK-5595: consumes the transitions contract in packages/ai-parrot/src/parrot/knowledge/wiki/experience/transitions.py

### Does NOT Exist

- `packages/ai-parrot/src/parrot/sdd/scripts/experience_hook.py` — absent at 0c5acf0915; supplied by this task or its declared predecessor.
- `packages/ai-parrot/tests/sdd/test_experience_hook.py` — absent at 0c5acf0915; supplied by this task or its declared predecessor.
- `packages/ai-parrot/tests/sdd/test_launcher_experience_fast_path.py` — absent at 0c5acf0915; supplied by this task or its declared predecessor.
- `parrot sdd task start` is not a CLI verb; task-start priming is workflow prose.
- Experience functionality is new; imported producer symbols must be rechecked after dependencies land.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/sdd/scripts/experience_hook.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/launcher.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/sdd/test_experience_hook.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/sdd/test_launcher_experience_fast_path.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/launcher.py#main_parrot"
  ]
}
```

## Implementation Notes

Use async service calls and bounded IO. Keep stdlib hook imports lazy, preserve the exception/cancellation semantics of callers, and log through the module logger. Blueprint gaps are planning instructions only: delivered code must contain no unfinished placeholders. All tests use temporary roots; do not mutate real global experience data. Each asset writer owns its packaged twins.

## Implementation Blueprint

### Steps (in order)

1. Verify the existing anchors and dependency interfaces — they fix the allowed integration surface.
2. Apply the per-file starting points and complete the scoped behavior — Implement main, host payload extraction, transcript-tail joins and response envelopes from M4; use shared transitions. Agy PostToolUse queues commands and PostInvocation resolves them. Unknown outcomes produce no evidence. Insert launcher fast path before Click fallback, including isolated -m entry. Hooks read only bounded published triggers/session state, never refresh, graduate or export. On normal known outcomes, adapt to an immutable stdlib record with command/ok/error/observation_id attributes; do not import the Pydantic CommandOutcome at runtime.
3. Exercise the listed failure and boundary cases — these protect the feature's event, sandbox and host contracts.
4. Run the task's validation commands and inspect the diff — commit only declared files and task state.

### `packages/ai-parrot/src/parrot/sdd/scripts/experience_hook.py` (CREATE)

```python
"""Bounded stdlib hook adapter; executable as an isolated module."""
from __future__ import annotations
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
from parrot.knowledge.wiki.experience.fastpath import load_triggers, safe_open, update_session
from parrot.knowledge.wiki.experience.transitions import on_outcome

def main(argv: Sequence[str] | None = None) -> int:
    """Read bounded stdin and emit advisory host JSON; all paths return zero."""
    # FILL IN: parse host/event, enforce limits, fail open; reserved pre does nothing.
def session_of(payload: Mapping[str, Any], env: Mapping[str, str]) -> str:
    """Return env/host session key suffixed by nonempty agent_id."""
    # FILL IN: exact §2 session precedence; never use key as a path.
def command_of(payload: Mapping[str, Any], host: str) -> str:
    """Extract Bash or run_command input; otherwise return empty string."""
    # FILL IN: exact M4 payload keys; no output-derived commands.
def outcome_of(payload: Mapping[str, Any], host: str, event: str) -> tuple[bool, str] | None:
    """Return a known command outcome, otherwise None."""
    # FILL IN: Claude event status; Codex rollout join; agy post is unknown.
def codex_outcome(transcript_path: Path, tool_use_id: str, *, max_bytes: int) -> tuple[bool, str] | None:
    """Join a bounded rollout tail by CommandExecution item.id."""
    # FILL IN: safe_open, tail boundary and unknown status; AC1-AC3.
def agy_outcome(transcript_path: Path, step_idx: int, *, max_bytes: int) -> tuple[bool, str] | None:
    """Read a GENERIC step result and header-only exit status."""
    # FILL IN: match step_index and use fastpath.agy_exit_code; AC1-AC3.
def observation_of(payload: Mapping[str, Any], host: str) -> str:
    """Return tool_use_id or conversationId:stepIdx."""
    # FILL IN: retain identity and Codex occurrence alias for replay; AC3.
def handle_post(payload: Mapping[str, Any], *, host: str, event: str, plane_dir: Path) -> str | None:
    """Handle known outcomes, or queue an agy pending transcript lookup."""
    # FILL IN: call the shared transition engine; bounded published triggers only.
def handle_post_invocation(payload: Mapping[str, Any], *, plane_dir: Path) -> str | None:
    """Resolve agy pending commands; unknown results defer to replay."""
    # FILL IN: no pending -> cheap exit; drop unreadable pending without event.
def render(advice: str, *, host: str, event: str) -> dict[str, Any]:
    """Return the exact M4 host response envelope."""
    # FILL IN: additionalContext or flat injectSteps; no permissions or updatedInput.

if __name__ == "__main__":
    sys.exit(main())
```

**Why**: This file owns the hooks behavior described in Scope. Preserve its existing callers and complete only the bounded cases in this task.

### `packages/ai-parrot/src/parrot/launcher.py` (MODIFY)

```python
# Anchor occurrences: 1; verified packages/ai-parrot/src/parrot/launcher.py:378 at 0c5acf0915.
# Anchor: from parrot.cli import cli
import sys
EXPERIENCE_HOOK_ARGV = ["sdd", "experience", "hook"]
# Insert inside main_parrot.load before the Click fallback:
if sys.argv[1:4] == EXPERIENCE_HOOK_ARGV:
    try:
        from parrot.sdd.scripts.experience_hook import main
        return lambda: main(sys.argv[4:])
    except Exception:
        return lambda: 0
# FILL IN: verify load() callable contract; preserve _launch entry handling.
```

**Why**: This file owns the hooks behavior described in Scope. Preserve its existing callers and complete only the bounded cases in this task.

### `packages/ai-parrot/tests/sdd/test_experience_hook.py` (CREATE)

```python
"""Deterministic experience-memory regression tests."""
from pathlib import Path
import pytest
from parrot.sdd.scripts import experience_hook

def test_hook_envelopes_per_host(tmp_path: Path) -> None:
    """Verify hook envelopes per host. """
    # FILL IN: arrange isolated fixtures and assert behavior, including failure paths;
    # use Test Specification and AC1-AC3, never a tautological/mock-only assertion.

def test_hook_session_key_includes_agent_id(tmp_path: Path) -> None:
    """Verify hook session key includes agent id. """
    # FILL IN: arrange isolated fixtures and assert behavior, including failure paths;
    # use Test Specification and AC1-AC3, never a tautological/mock-only assertion.

def test_hook_agy_outcome_from_transcript(tmp_path: Path) -> None:
    """Verify hook agy outcome from transcript. """
    # FILL IN: arrange isolated fixtures and assert behavior, including failure paths;
    # use Test Specification and AC1-AC3, never a tautological/mock-only assertion.

def test_hook_budget_overflow_is_noop(tmp_path: Path) -> None:
    """Verify hook budget overflow is noop. """
    # FILL IN: arrange isolated fixtures and assert behavior, including failure paths;
    # use Test Specification and AC1-AC3, never a tautological/mock-only assertion.
```

**Why**: This file owns the hooks behavior described in Scope. Preserve its existing callers and complete only the bounded cases in this task.

### `packages/ai-parrot/tests/sdd/test_launcher_experience_fast_path.py` (CREATE)

```python
"""Deterministic experience-memory regression tests."""
from pathlib import Path
import pytest
from parrot.sdd.scripts import experience_hook

def test_launcher_fast_path_stdlib_only(tmp_path: Path) -> None:
    """Verify launcher fast path stdlib only. """
    # FILL IN: arrange isolated fixtures and assert behavior, including failure paths;
    # use Test Specification and AC1-AC3, never a tautological/mock-only assertion.

def test_success_hook_under_latency_budget(tmp_path: Path) -> None:
    """Verify success hook under latency budget. """
    # FILL IN: arrange isolated fixtures and assert behavior, including failure paths;
    # use Test Specification and AC1-AC3, never a tautological/mock-only assertion.
```

**Why**: This file owns the hooks behavior described in Scope. Preserve its existing callers and complete only the bounded cases in this task.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/sdd/scripts/experience_hook.py` — finish its marked branches/examples using Scope and Test Specification.
- [ ] `packages/ai-parrot/src/parrot/launcher.py` — finish its marked branches/examples using Scope and Test Specification.
- [ ] `packages/ai-parrot/tests/sdd/test_experience_hook.py` — finish its marked branches/examples using Scope and Test Specification.
- [ ] `packages/ai-parrot/tests/sdd/test_launcher_experience_fast_path.py` — finish its marked branches/examples using Scope and Test Specification.

## Acceptance Criteria

- [ ] AC1: All declared files implement Scope using the spec's exact public interfaces; existing behavior remains compatible.
- [ ] AC2: The stated no-op, bounded IO, trust and error-handling constraints hold; no new dependency or unrelated file is introduced.
- [ ] AC3: all three host payloads, Claude subagent keys, rollout lookup by tool_use_id, agy header-only transcript outcome, unreadable transcript fallback, exact envelopes, no pre-hook, over-budget no-op, no index/ledger writes, installed-entry stdlib success path median under 50 ms excluding interpreter start.
- [ ] AC4: All Validation Commands pass; applicable asset twins remain synchronized.

## Validation Commands

- `pytest packages/ai-parrot/tests/sdd/test_experience_hook.py -q`
- `pytest packages/ai-parrot/tests/sdd/test_launcher_experience_fast_path.py -q`

## Test Specification

Required behavioral cases: all three host payloads, Claude subagent keys, rollout lookup by tool_use_id, agy header-only transcript outcome, unreadable transcript fallback, exact envelopes, no pre-hook, over-budget no-op, no index/ledger writes, installed-entry stdlib success path median under 50 ms excluding interpreter start.

Use the spec §4 payload fixtures, with deterministic temporary Git roots and PARROT_HOME. Assert state/events/outputs, including unknown outcomes and failures; mocks alone are not evidence. Each test file listed above belongs to this task. Preserve all existing regression cases in modified tests.

## Agent Instructions

1. Use `$sdd-start TASK-5596` and the feature worktree; do not implement on dev.
2. Verify dependencies are done in `sdd/tasks/index/sdd-experience-memory.json` and recheck this contract after they land.
3. Implement only the declared files, run validation, and commit scoped changes.
4. Use `parrot sdd task finalize` with real TaskCompletionEvidence and the exact implementation HEAD. The finalizer owns the completion note and active-to-completed move; never edit them manually.
