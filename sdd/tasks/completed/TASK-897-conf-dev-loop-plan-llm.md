# TASK-897: Add `DEV_LOOP_PLAN_LLM` navconfig setting

**Feature**: FEAT-132 — feat-129-upgrades
**Spec**: `sdd/specs/feat-129-upgrades.spec.md`
**Status**: pending
**Priority**: low
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6. The plan summary in TASK-900 reuses the existing
`DEV_LOOP_SUMMARY_LLM` (Haiku) by default but operators may want to
pin a different model for plan generation without changing the
log-summary model. Add an optional `DEV_LOOP_PLAN_LLM` setting that
falls back to `DEV_LOOP_SUMMARY_LLM` when unset.

This task is **independent** of every other FEAT-132 task — it only
touches `parrot/conf.py` and a tiny test. Mark as `parallel: true`.

---

## Scope

- Add `DEV_LOOP_PLAN_LLM` to `parrot/conf.py`. Default fallback: empty
  string (so callers can detect "unset" and route to
  `DEV_LOOP_SUMMARY_LLM`).
- Extend `tests/test_conf.py::TestDevLoopSettingsDefaults` with a
  test that asserts the empty default.
- Document the variable in `examples/dev_loop/README.md` (one row in
  the prerequisites table).

**NOT in scope**:
- Wiring the value into `ResearchNode` (TASK-900).
- Renaming or changing existing summary settings.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/conf.py` | MODIFY | Add `DEV_LOOP_PLAN_LLM = config.get(..., fallback="")`. |
| `packages/ai-parrot/tests/test_conf.py` | MODIFY | Add `test_plan_llm_default_empty`. |
| `examples/dev_loop/README.md` | MODIFY | Add table row for `DEV_LOOP_PLAN_LLM`. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot import conf
# verified: parrot/conf.py is the navconfig wrapper

# Inside conf.py, settings are read as:
config.get("KEY", fallback="<default>")        # for str
config.getint("KEY", fallback=<int>)           # for int
config.getlist("KEY", fallback=[...])          # for list
# verified: parrot/conf.py:618-643 (existing FEAT-129 settings)
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/conf.py

# Existing FEAT-129 dev-loop settings (lines 618-643):
CLAUDE_CODE_MAX_CONCURRENT_DISPATCHES: int = config.getint(
    "CLAUDE_CODE_MAX_CONCURRENT_DISPATCHES", fallback=3
)
FLOW_BOT_JIRA_ACCOUNT_ID: str = config.get(
    "FLOW_BOT_JIRA_ACCOUNT_ID", fallback=""
)
WORKTREE_BASE_PATH: str = config.get(
    "WORKTREE_BASE_PATH", fallback=".claude/worktrees"
)
FLOW_STREAM_TTL_SECONDS: int = config.getint(
    "FLOW_STREAM_TTL_SECONDS", fallback=604800
)
ACCEPTANCE_CRITERION_ALLOWLIST: list[str] = config.getlist(
    "ACCEPTANCE_CRITERION_ALLOWLIST",
    fallback=["task", "flowtask", "pytest", "ruff", "mypy", "pylint"],
) or [...]

# Existing summary-LLM consumer pattern (research.py):
def _summarizer_llm_default() -> str:
    return conf.config.get(
        "DEV_LOOP_SUMMARY_LLM",
        fallback="anthropic:claude-haiku-4-5-20251001",
    )
# verified: parrot/flows/dev_loop/nodes/research.py
```

### Does NOT Exist

- ~~`DEV_LOOP_PLAN_MODEL`~~ — use `DEV_LOOP_PLAN_LLM` (matches the
  existing `DEV_LOOP_SUMMARY_LLM` naming).
- ~~`config.get(..., default=...)`~~ — navconfig Kardex uses
  `fallback=`. Memory note exists at
  `~/.claude/projects/.../memory/feedback_navconfig_kardex_fallback.md`.

---

## Implementation Notes

### Pattern to Follow

```python
# packages/ai-parrot/src/parrot/conf.py — append in the FEAT-129
# settings block:

# Plan-summary LLM override. Empty string means "fall back to
# DEV_LOOP_SUMMARY_LLM" — see _plan_llm_default() in research.py
# (TASK-900). FEAT-132.
DEV_LOOP_PLAN_LLM: str = config.get(
    "DEV_LOOP_PLAN_LLM", fallback=""
)
```

### Key Constraints

- Default must be `""` (NOT a model id). The consuming code in
  TASK-900 detects empty and routes to `DEV_LOOP_SUMMARY_LLM`.
- Use `fallback=` not `default=` — Kardex API quirk.

### References in Codebase

- `parrot/conf.py:618-643` — adjacent dev-loop settings, follow
  the same comment style.
- `parrot/flows/dev_loop/nodes/research.py::_summarizer_llm_default`
  — the pattern TASK-900 will mirror.

---

## Acceptance Criteria

- [ ] `parrot.conf.DEV_LOOP_PLAN_LLM` resolves to `""` by default and
  to the env value when set.
- [ ] `tests/test_conf.py::TestDevLoopSettingsDefaults::test_plan_llm_default_empty`
  passes.
- [ ] `examples/dev_loop/README.md` documents the variable.
- [ ] No other FEAT-129 settings have changed.

---

## Test Specification

```python
# packages/ai-parrot/tests/test_conf.py
class TestDevLoopSettingsDefaults:
    ...

    def test_plan_llm_default_empty(self):
        # Empty string means "use DEV_LOOP_SUMMARY_LLM".
        assert conf.DEV_LOOP_PLAN_LLM == ""
```

If the user has `DEV_LOOP_PLAN_LLM` set in their shell env, the
assertion will fail locally — same caveat as the pre-existing
`test_jira_account_default_empty`. Acceptable for this project; CI
runs without env overrides.

---

## Agent Instructions

1. Add the setting in `conf.py` next to the FEAT-129 block.
2. Add the test in `test_conf.py`.
3. Append one row to the README prerequisites table.
4. Run `pytest packages/ai-parrot/tests/test_conf.py -q`.
5. Commit; move task file to `sdd/tasks/done/`; update index.

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-04-28
**Notes**: Added DEV_LOOP_PLAN_LLM = config.get("DEV_LOOP_PLAN_LLM", fallback="") to conf.py in the FEAT-129 settings block. Added test_plan_llm_default_empty to test_conf.py. Added README row for DEV_LOOP_PLAN_LLM. The test passes (pre-existing test_jira_account_default_empty failure is a shell-env issue, not caused by this task).
**Deviations from spec**: none
