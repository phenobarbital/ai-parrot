# TASK-1939: Audit — grep for residual old-bus symbols and verify pyproject.toml pin

**Feature**: eventbus-replacement-evaluation
**Feature ID**: FEAT-381
**Spec**: sdd/specs/eventbus-replacement-evaluation.spec.md
**Status**: [ ] pending | [ ] in-progress | [x] done
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

**AUDIT CLEAN** (2026-07-27)

Scan results:

1. **Deleted-module imports in `src/`** — NONE. Three docstring cross-references
   in `parrot/core/hooks/matrix.py` (lines 6, 19, 36) mention
   `~parrot.core.hooks.base.HookRegistry` in Sphinx `:class:` markup only;
   no Python `import` statement present.

2. **Deleted-module imports in `tests/`** — All expected/legitimate:
   - `test_migration_guard.py` lines 16-19: `parametrize` list that asserts
     these modules *cannot* be imported — correct by design.
   - `test_github_reviewer.py` line 74: docstring comment only.
   - `test_jira_specialist_grounding.py` line 164: `_mk("parrot.core.hooks.models", ...)`
     — registers a `sys.modules` mock stub for test isolation; dead stub
     (module is gone) but harmless. Not an import error; not in scope for
     TASK-1940 fixes (spec Non-Goals).

3. **`class BusCore` / `class EventEnvelope` in `parrot.*`** — NONE found.

4. **`pyproject.toml` pin** — line 107: `navigator-eventbus>=0.2.1` — PyPI
   specifier, no `git+` prefix. CLEAN.

5. **`parrot/core/hooks/__init__.py` re-exports** — `HookManager`, `BaseHook`,
   `HookEvent`, `HookType`, `HookRegistry` all imported from `navigator_eventbus`.
   Lazy-loader map routes broker hooks to `navigator_eventbus.hooks.brokers.*`.
   CLEAN.

Findings for TASK-1940: **none requiring fixes** → TASK-1940 is a no-op.
