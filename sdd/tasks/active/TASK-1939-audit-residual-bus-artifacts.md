# TASK-1939: Audit — grep for residual old-bus symbols and verify pyproject.toml pin

**Feature**: eventbus-replacement-evaluation
**Feature ID**: FEAT-381
**Spec**: sdd/specs/eventbus-replacement-evaluation.spec.md
**Status**: [ ] pending | [ ] in-progress | [ ] done
**Priority**: high
**Effort**: S
**Depends-on**: none
**Assigned-to**: unassigned

## Context

FEAT-319 (eventbus-consolidation) completed the migration of ai-parrot's internal
bus core to the standalone `navigator-eventbus` package. This audit task verifies
that the migration is clean: no deleted modules are still referenced, the
dependency pin is correct, and hook imports are healthy.

## Scope

1. Grep `packages/ai-parrot/src/` and `packages/ai-parrot/tests/` for:
   - `parrot.core.events.bus` (deleted module)
   - `parrot.core.events.evb` (deleted module)
   - `parrot.core.hooks.base` (deleted module)
   - `parrot.core.hooks.models` (deleted module)
   - class definitions for `BusCore` (must not exist in parrot.*)
   - local `class EventEnvelope` definitions (must not exist in parrot.*)
   - `git+http` or `git+https` for `navigator-eventbus` in pyproject.toml

2. Read `packages/ai-parrot/pyproject.toml` — verify `navigator-eventbus` pin is
   a PyPI specifier (`>=0.2.1`) not a git URL.

3. Read `packages/ai-parrot/src/parrot/core/hooks/__init__.py` — verify
   re-exports of `HookManager`, `BaseHook`, `HookEvent`, `HookType` resolve
   via `navigator_eventbus`.

4. Produce a findings list: each finding = file + line + symbol + recommended fix.
   If zero findings, write "AUDIT CLEAN" in the completion note.

## Files to Read (no edits in this task)

- `packages/ai-parrot/src/parrot/core/hooks/__init__.py`
- `packages/ai-parrot/src/parrot/core/events/__init__.py`
- `packages/ai-parrot/pyproject.toml` (lines 100–120 and any navigator-eventbus refs)
- Any files flagged by grep

## Implementation Notes

- This is a READ-ONLY task. Do NOT edit files.
- Use `grep -rn` or `rg` under `packages/ai-parrot/`.
- Check both `src/` (production code) and `tests/` (test code).
- For the pyproject.toml check, look for any line matching
  `navigator.eventbus` — verify it has no `git+` prefix.

## Acceptance Criteria

- [ ] Grep scan completed over `packages/ai-parrot/src/` and `tests/`.
- [ ] `pyproject.toml` pin verified (PyPI, not git URL).
- [ ] `parrot/core/hooks/__init__.py` re-exports verified.
- [ ] Findings list (or AUDIT CLEAN) written in completion note.

## Output

When complete:
1. Write completion note below with the findings list or "AUDIT CLEAN".
2. Update `sdd/tasks/index/eventbus-replacement-evaluation.json` status to "done".
3. Do NOT move the file — TASK-1940 needs the findings.

### Completion Note
(Agent fills this in when done)
