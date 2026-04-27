# TASK-876: navconfig settings for the dev-loop flow

**Feature**: FEAT-129 — Dev-Loop Orchestration with Claude Code Subagent Mirror
**Spec**: `sdd/specs/dev-loop-orchestration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements **Module 12** from spec §3. The dispatcher, multiplexer,
nodes, webhook, and BugIntake validation all read configuration from
`parrot.conf.config` (navconfig). This task introduces the six new
settings with documented defaults so downstream tasks can consume them
without runtime errors when env-vars are unset.

This task is parallel-safe with TASK-874, TASK-875, TASK-877.

---

## Scope

- Add six new settings to `packages/ai-parrot/src/parrot/conf.py`,
  using the same `config.get(..., default=...)` / module-level constant
  pattern already established in that file.
- Defaults (per spec §3 Module 12):
  - `CLAUDE_CODE_MAX_CONCURRENT_DISPATCHES = 3` (int)
  - `FLOW_MAX_CONCURRENT_RUNS = 5` (int)
  - `FLOW_BOT_JIRA_ACCOUNT_ID = ""` (str — empty, must be set per env)
  - `WORKTREE_BASE_PATH = ".claude/worktrees"` (str — relative repo path)
  - `FLOW_STREAM_TTL_SECONDS = 604800` (int — 7 days)
  - `ACCEPTANCE_CRITERION_ALLOWLIST = ["flowtask", "pytest", "ruff",
    "mypy", "pylint"]` (list[str])
- Add a unit test asserting all six resolve to the documented defaults
  when no env override is set.

**NOT in scope**:
- Any consumer of these settings (those live in TASKs 878, 879, 880,
  883, 887).
- A new env-vars `.env.example` block (project does not maintain one).
- Documentation in the README — that's TASK-890.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/conf.py` | MODIFY | Add six new module-level constants reading from `config.get(...)`. |
| `packages/ai-parrot/tests/test_conf.py` | MODIFY (or CREATE) | Unit test for the six new defaults. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# At the top of conf.py — already present
from navconfig import config            # parrot/conf.py line 5
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/conf.py
# Pattern (verbatim from existing constants):
#
#   FOO = config.get("FOO", fallback=<default>)
#   BAR = config.getint("BAR", fallback=<default>)
#   BAZ = config.getlist("BAZ", fallback=[...])  # check if helper exists
#
# Read the file first to determine which helpers are used by neighboring
# constants and follow that style.
```

### Does NOT Exist

- ~~`parrot.settings`~~ / ~~`parrot.config`~~ — settings live in
  `parrot.conf` only. Do not create a new module.
- ~~Pydantic `Settings` class~~ — this codebase uses navconfig flat
  constants, not pydantic-settings. Stay consistent.

---

## Implementation Notes

### Pattern to Follow

Open `packages/ai-parrot/src/parrot/conf.py` and pick a logical block of
related constants (look for any block that reads list/int/str values).
Match the style. Most navconfig-backed projects use:

```python
CLAUDE_CODE_MAX_CONCURRENT_DISPATCHES = config.getint(
    "CLAUDE_CODE_MAX_CONCURRENT_DISPATCHES", fallback=3
)
FLOW_MAX_CONCURRENT_RUNS = config.getint("FLOW_MAX_CONCURRENT_RUNS",
                                         fallback=5)
FLOW_BOT_JIRA_ACCOUNT_ID = config.get("FLOW_BOT_JIRA_ACCOUNT_ID",
                                      fallback="")
WORKTREE_BASE_PATH = config.get("WORKTREE_BASE_PATH",
                                fallback=".claude/worktrees")
FLOW_STREAM_TTL_SECONDS = config.getint("FLOW_STREAM_TTL_SECONDS",
                                        fallback=604800)
ACCEPTANCE_CRITERION_ALLOWLIST = config.getlist(
    "ACCEPTANCE_CRITERION_ALLOWLIST",
    fallback=["flowtask", "pytest", "ruff", "mypy", "pylint"],
)
```

If `config.getlist` does not exist in the local navconfig flavor, fall
back to a small helper that splits a comma-separated env var, e.g.:

```python
_raw = config.get("ACCEPTANCE_CRITERION_ALLOWLIST", fallback=None)
ACCEPTANCE_CRITERION_ALLOWLIST = (
    [s.strip() for s in _raw.split(",")] if _raw
    else ["flowtask", "pytest", "ruff", "mypy", "pylint"]
)
```

### Key Constraints

- Defaults are stable contract — downstream tests pin them.
- `FLOW_BOT_JIRA_ACCOUNT_ID` defaults to empty string; downstream
  toolkit construction MUST tolerate this and not error at import time.
- Constants live at module scope so `from parrot.conf import
  CLAUDE_CODE_MAX_CONCURRENT_DISPATCHES` works without instantiating
  any class.

### References in Codebase

- `packages/ai-parrot/src/parrot/conf.py` — read first to confirm
  navconfig helper names.

---

## Acceptance Criteria

- [ ] All six constants are importable:
  `from parrot.conf import (CLAUDE_CODE_MAX_CONCURRENT_DISPATCHES,
  FLOW_MAX_CONCURRENT_RUNS, FLOW_BOT_JIRA_ACCOUNT_ID, WORKTREE_BASE_PATH,
  FLOW_STREAM_TTL_SECONDS, ACCEPTANCE_CRITERION_ALLOWLIST)`.
- [ ] When no env vars are set, the constants equal the documented
  defaults (test in `tests/test_conf.py`).
- [ ] `FLOW_BOT_JIRA_ACCOUNT_ID` is type `str` and defaults to `""`.
- [ ] `ACCEPTANCE_CRITERION_ALLOWLIST` is type `list[str]` with five
  entries in the documented order.
- [ ] `ruff check packages/ai-parrot/src/parrot/conf.py`.

---

## Test Specification

```python
# packages/ai-parrot/tests/test_conf.py
from parrot import conf


class TestDevLoopSettingsDefaults:
    def test_concurrency_defaults(self):
        assert conf.CLAUDE_CODE_MAX_CONCURRENT_DISPATCHES == 3
        assert conf.FLOW_MAX_CONCURRENT_RUNS == 5

    def test_jira_account_default_empty(self):
        assert conf.FLOW_BOT_JIRA_ACCOUNT_ID == ""

    def test_worktree_base_path_default(self):
        assert conf.WORKTREE_BASE_PATH == ".claude/worktrees"

    def test_stream_ttl_default_seven_days(self):
        assert conf.FLOW_STREAM_TTL_SECONDS == 604800

    def test_acceptance_allowlist_default(self):
        assert conf.ACCEPTANCE_CRITERION_ALLOWLIST == [
            "flowtask", "pytest", "ruff", "mypy", "pylint",
        ]
```

---

## Agent Instructions

1. Read `packages/ai-parrot/src/parrot/conf.py`. Identify the navconfig
   helper style (`getint`, `getlist`, `get`).
2. Update index → `"in-progress"`.
3. Add the six constants. Run `pytest packages/ai-parrot/tests/test_conf.py -v`.
4. Move task file to completed; update index; fill Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**:
