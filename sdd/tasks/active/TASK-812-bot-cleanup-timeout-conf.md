# TASK-812: Add BOT_CLEANUP_TIMEOUT configuration constant

**Feature**: FEAT-114 — Bot Cleanup Lifecycle
**Spec**: `sdd/specs/FEAT-114-bot-cleanup-lifecycle.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

The new on-cleanup flow in `BotManager` (TASK-814) wraps every per-bot
`cleanup()` call in `asyncio.wait_for(..., timeout=BOT_CLEANUP_TIMEOUT)`
to prevent a hanging bot from blocking shutdown. This task introduces the
configuration constant that supplies that timeout.

Implements **Module 3** of the spec (§3).

---

## Scope

- Add `BOT_CLEANUP_TIMEOUT` to `packages/ai-parrot/src/parrot/conf.py`,
  defined as `config.getint('BOT_CLEANUP_TIMEOUT', fallback=20)`.
- Place it next to other `config.getint`-backed timeout-style constants
  so it is discoverable (after `MCP_SERVER_PORT` or grouped with
  `ONTOLOGY_CACHE_TTL` — pick the block that reads most naturally).
- No other changes in this task — the import in `manager/manager.py`
  is performed by TASK-814.

**NOT in scope**:
- Importing or using the constant anywhere — that is TASK-814.
- Touching `pyproject.toml` / package dependencies.
- Documentation updates — belongs to TASK-817.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/conf.py` | MODIFY | Add `BOT_CLEANUP_TIMEOUT` constant with default 20. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Already imported at packages/ai-parrot/src/parrot/conf.py:5
from navconfig import config, BASE_DIR
# No new imports required.
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/conf.py — existing pattern for int env vars
# line 120:
ONTOLOGY_CACHE_TTL = config.getint('ONTOLOGY_CACHE_TTL', fallback=86400)
# line 123:
ONTOLOGY_MAX_TRAVERSAL_DEPTH = config.getint('ONTOLOGY_MAX_TRAVERSAL_DEPTH', fallback=4)
# line 172:
MCP_SERVER_PORT = config.getint('MCP_SERVER_PORT', fallback=9090)
# line 238:
SCYLLADB_PORT = config.getint('SCYLLADB_PORT', fallback=9042)
```

### Does NOT Exist

- ~~`parrot.conf.BOT_CLEANUP_TIMEOUT`~~ — does not exist yet (this task creates it).
- ~~`config.get_int(...)`~~ — the method is `config.getint(...)` (no underscore).
- ~~`BOT_TIMEOUT`, `BOT_SHUTDOWN_TIMEOUT`, `CLEANUP_TIMEOUT`~~ — these
  names are **not** to be used. The spec-mandated name is
  `BOT_CLEANUP_TIMEOUT`.

---

## Implementation Notes

### Pattern to Follow

```python
# Match the existing ONTOLOGY_CACHE_TTL declaration style exactly.
BOT_CLEANUP_TIMEOUT = config.getint('BOT_CLEANUP_TIMEOUT', fallback=20)
```

### Key Constraints

- Default is **20 seconds** (as agreed in the spec).
- No module-level side effects beyond the assignment.
- The constant is an `int` (seconds), passed directly to
  `asyncio.wait_for(..., timeout=...)`, which accepts `float | int`.

### References in Codebase

- `packages/ai-parrot/src/parrot/conf.py:120` — existing `ONTOLOGY_CACHE_TTL` pattern.
- `packages/ai-parrot/src/parrot/conf.py:172` — existing `MCP_SERVER_PORT` pattern.

---

## Acceptance Criteria

- [ ] `BOT_CLEANUP_TIMEOUT` is defined at module level in `conf.py`.
- [ ] Default value is `20` when the env var is unset.
- [ ] `python -c "from parrot.conf import BOT_CLEANUP_TIMEOUT; print(BOT_CLEANUP_TIMEOUT)"` prints `20` with no env override.
- [ ] Setting `BOT_CLEANUP_TIMEOUT=7` in the environment causes the constant to read `7` on re-import.
- [ ] No existing tests regress: `pytest packages/ai-parrot/tests/ -x -k "not slow"` shows no new failures attributable to this change.
- [ ] `ruff check packages/ai-parrot/src/parrot/conf.py` is clean.

---

## Test Specification

No dedicated test file is required for a single constant. Validation is
performed by TASK-816 (`test_bot_cleanup_timeout_default` and
`test_bot_cleanup_timeout_env_override`), which imports
`BOT_CLEANUP_TIMEOUT` and exercises both the default and the
env-override paths.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/FEAT-114-bot-cleanup-lifecycle.spec.md` for full context.
2. **Check dependencies** — none.
3. **Verify the Codebase Contract** — confirm `config.getint` is used in `conf.py` (lines 120, 123, 172, 238) and that `BOT_CLEANUP_TIMEOUT` does not yet exist.
4. **Update status** in `sdd/tasks/.index.json` → `in-progress`.
5. **Add the one-line constant** following the exact pattern above.
6. **Verify** with the import command in Acceptance Criteria.
7. **Move this file** to `sdd/tasks/completed/TASK-812-bot-cleanup-timeout-conf.md`.
8. **Update index** → `done`.
9. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
