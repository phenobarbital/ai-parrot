# HOTFIX-sdd-coder-execution-id-guidance-1: sdd-worker prompt — generate execution_id with a command

**Feature**: sdd-coder-execution-id-guidance (brief)
**Spec**: sdd/briefs/sdd-coder-execution-id-guidance.brief.md
**Status**: done
**Priority**: high
**Estimated effort**: XS
**Depends-on**: none
**Assigned-to**: unassigned

## Context
Agents hand-write `execution_id` and produce non-hex UUIDs (`...-184pbac00001`), so the first
`coder_begin_execution` fails with `invalid tool arguments`. See brief § Root cause (1).

## Scope
- Replace "Generate one UUID for this worker invocation" (step 0) with an explicit instruction:
  obtain it from a command, e.g. `python -c 'import uuid; print(uuid.uuid4())'` (fallback
  `cat /proc/sys/kernel/random/uuid`); NEVER compose it by hand or derive it from the feature
  name; it must be a lowercase canonical UUID (36 chars, hex + hyphens).
- Add one line: on `invalid_arguments` naming `execution_id`, regenerate via the command and retry once.
- Apply the IDENTICAL edit to both twins.

**NOT in scope**: any Python code; other prompt sections.

## Files to Create / Modify
- `.claude/agents/sdd-worker.md` (line 334) — needs `git add -f` (`.claude/` is ignored).
- `packages/ai-parrot/src/parrot/sdd/_assets/claude/agents/sdd-worker.md` (same paragraph).

## Codebase Contract
### Existing anchors
- `.claude/agents/sdd-worker.md:334`: `0. **Begin execution, then plan.** Generate one UUID for this worker invocation and call`
### Does NOT Exist
- No helper CLI like `parrot sdd new-execution-id` — do not reference one.

## Acceptance Criteria
- [ ] Both twins contain the command-based instruction and the "never hand-written" rule.
- [ ] `diff` between the twins shows no difference in this paragraph.

## Validation Commands
- `grep -n "uuid.uuid4" .claude/agents/sdd-worker.md packages/ai-parrot/src/parrot/sdd/_assets/claude/agents/sdd-worker.md`
- `diff .claude/agents/sdd-worker.md packages/ai-parrot/src/parrot/sdd/_assets/claude/agents/sdd-worker.md`

## Completion Note

Verified in 67da154d37: `coder_begin_execution` test suite passes (38 passed, test_toolkit.py); both .claude/agents/sdd-worker.md twins identical; diff covers the change described in this task.
