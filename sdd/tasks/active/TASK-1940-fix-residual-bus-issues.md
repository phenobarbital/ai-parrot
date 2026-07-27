# TASK-1940: Fix — apply targeted fixes for any residual old-bus references found in audit

**Feature**: eventbus-replacement-evaluation
**Feature ID**: FEAT-381
**Spec**: sdd/specs/eventbus-replacement-evaluation.spec.md
**Status**: [ ] pending | [ ] in-progress | [ ] done
**Priority**: high
**Effort**: S
**Depends-on**: TASK-1939
**Assigned-to**: unassigned

## Context

After the audit (TASK-1939) produces its findings list, this task applies the
minimal surgical fixes. If TASK-1939 reported "AUDIT CLEAN", this task is a
no-op — mark it done immediately with note "No fixes needed (audit clean)".

## Scope

For each finding from TASK-1939:
- Redirect stale import to the correct `navigator_eventbus` path.
- Delete dead code / dead comments referencing deleted modules.
- Fix any eventbus-related `ruff check` violations (F401 on deleted import,
  E402 import order, etc.) in the flagged files ONLY.

**Do NOT** run `ruff --fix` globally. Only touch files explicitly flagged by the
audit or by an eventbus-specific `ruff check` error.

## Implementation Notes

- Read each flagged file before editing.
- One edit per file — batch all fixes in a single `Edit` call per file.
- After all edits, run `ruff check <edited_files>` to confirm no regressions.
- Reference the approved import paths:
  ```python
  # Correct: from navigator_eventbus
  from navigator_eventbus import EventBus, Event, EventEnvelope, EventPriority, EventSubscription
  from navigator_eventbus.hooks.manager import HookManager
  from navigator_eventbus.hooks.base import BaseHook
  from navigator_eventbus.hooks.models import HookEvent, HookType
  ```
- The local `parrot.core.hooks.__init__` re-export shim is the approved bridge
  for domain hooks — do not break it.

## Acceptance Criteria

- [ ] All findings from TASK-1939 addressed (or "No fixes needed").
- [ ] `ruff check <edited_files>` exits 0 (no new violations).
- [ ] No functional changes — only import redirects and dead code removal.

## Output

When complete:
1. Write completion note below: list files edited (or "No fixes needed").
2. Update `sdd/tasks/index/eventbus-replacement-evaluation.json` status to "done".
3. Move this file to `sdd/tasks/completed/`.

### Completion Note
(Agent fills this in when done)
