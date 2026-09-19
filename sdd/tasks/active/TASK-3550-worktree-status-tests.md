# TASK-3550: Unit Tests for worktree_status.py

**Feature**: FEAT-582 — SDD Status — Worktree-Aware Task State
**Spec**: `sdd/specs/sdd-status-worktrees.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3549
**Assigned-to**: unassigned

---

## Context

> Comprehensive unit tests for the `scripts.sdd.worktree_status` module
> created in TASK-3549. Tests mock git output and filesystem to validate
> branch parsing, index reading, health checks, discovery, and the CLI
> `--json` output. Implements spec §3 Module 5 and §4 Test Specification.

---

## Scope

- Test `_parse_branch` with feature, hotfix, legacy, non-SDD, and task-sub-worktree branches.
- Test `_read_worktree_index` with valid, missing, and malformed JSON.
- Test `_check_health` with clean and dirty worktrees (mocked git).
- Test `_live_process_count` with mocked `/proc` (skip on non-Linux).
- Test `ready_for_done` logic: all-done+clean+pushed=True, dirty=False, unpushed=False.
- Test `discover_worktree_reports` end-to-end with mocked git + mock filesystem.
- Test CLI `--json` output schema validation.

**NOT in scope**: testing the commands/skills that call this module (TASK-3551/3552/3553).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/sdd_scripts/test_worktree_status.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Module under test (created by TASK-3549):
from scripts.sdd.worktree_status import (  # will exist after TASK-3549
    WorktreeTaskStatus,
    WorktreeHealth,
    WorktreeReport,
    _parse_branch,
    _read_worktree_index,
    _check_health,
    _live_process_count,
    _parse_porcelain,
    discover_worktree_reports,
    main,
)

import pytest  # verified: pyproject.toml dev dependency
from unittest.mock import patch, MagicMock  # stdlib
from pathlib import Path  # stdlib
import json  # stdlib
import subprocess  # stdlib
```

### Existing Test Patterns
```python
# tests/sdd_scripts/test_ensure_worktree.py — existing test file in the same directory
# Uses pytest fixtures, tmp_path, monkeypatch, subprocess mocking.
# Follow this pattern for test structure and naming.
```

### Does NOT Exist
- ~~`tests/sdd_scripts/test_worktree_status.py`~~ — this task creates it
- ~~`scripts.sdd.worktree_status`~~ — created by TASK-3549 (dependency)

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "tests/sdd_scripts/test_worktree_status.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Create `tests/sdd_scripts/test_worktree_status.py` with fixtures — *why*: reusable test data for all test classes.
2. Implement `TestParseBranch` — *why*: validates the regex patterns that map branches to features.
3. Implement `TestParsePortcelain` — *why*: validates git output parsing.
4. Implement `TestReadWorktreeIndex` — *why*: validates JSON reading with failure modes.
5. Implement `TestHealth` — *why*: validates dirty/unpushed/live-process detection.
6. Implement `TestReadyForDone` — *why*: validates the critical flag that drives `/sdd-done` suggestions.
7. Implement `TestDiscover` — *why*: end-to-end with mocked subprocess + tmp_path.
8. Implement `TestCli` — *why*: validates `--json` output schema.

### `tests/sdd_scripts/test_worktree_status.py` (CREATE)
```python
"""Unit tests for scripts.sdd.worktree_status — FEAT-582."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from scripts.sdd.worktree_status import (
    WorktreeTaskStatus,
    WorktreeHealth,
    WorktreeReport,
    _parse_branch,
    _parse_porcelain,
    _read_worktree_index,
    _check_health,
    _live_process_count,
    discover_worktree_reports,
    main,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_porcelain_output():
    return (
        "worktree /repo\n"
        "HEAD abc123\n"
        "branch refs/heads/dev\n"
        "\n"
        "worktree /repo/.claude/worktrees/feat-FEAT-550-token-budget-bedrock\n"
        "HEAD def456\n"
        "branch refs/heads/feat-FEAT-550-token-budget-bedrock\n"
        "\n"
        "worktree /repo/.claude/worktrees/hotfix-PAR-123-fix-foo\n"
        "HEAD ghi789\n"
        "branch refs/heads/hotfix-PAR-123-fix-foo\n"
        "\n"
    )


@pytest.fixture
def sample_index():
    return {
        "feature": "token-budget-bedrock",
        "feature_id": "FEAT-550",
        "base_branch": "dev",
        "tasks": [
            {"id": "TASK-3132", "status": "done", "completed_at": "2026-09-10T23:54:36+00:00"},
            {"id": "TASK-3133", "status": "in-progress", "completed_at": None},
        ],
    }


@pytest.fixture
def all_done_index():
    return {
        "feature": "token-budget-bedrock",
        "feature_id": "FEAT-550",
        "base_branch": "dev",
        "tasks": [
            {"id": "TASK-3132", "status": "done", "completed_at": "2026-09-10"},
            {"id": "TASK-3133", "status": "done", "completed_at": "2026-09-11"},
        ],
    }


# ---------------------------------------------------------------------------
# TestParseBranch
# ---------------------------------------------------------------------------

class TestParseBranch:
    def test_feature_branch(self):
        result = _parse_branch("feat-FEAT-550-token-budget-bedrock")
        assert result == ("token-budget-bedrock", "FEAT-550", "feature")

    def test_hotfix_branch(self):
        result = _parse_branch("hotfix-PAR-123-fix-foo")
        assert result == ("fix-foo", "PAR-123", "hotfix")

    def test_legacy_feature_branch(self):
        """Legacy format: feat-<NNN>-<slug> without FEAT- prefix."""
        result = _parse_branch("feat-465-fix-weak-sha1")
        assert result == ("fix-weak-sha1", "FEAT-465", "feature")

    def test_non_sdd_branch(self):
        assert _parse_branch("chore-ruff-config") is None

    def test_dev_branch(self):
        assert _parse_branch("dev") is None

    def test_main_branch(self):
        assert _parse_branch("main") is None

    def test_task_sub_worktree(self):
        """sdd-coder sub-worktrees must NOT be parsed as features."""
        assert _parse_branch("TASK-3351-a1-some-slug") is None


# ---------------------------------------------------------------------------
# TestParsePortcelain
# ---------------------------------------------------------------------------

class TestParsePorcelain:
    def test_parses_worktrees(self, sample_porcelain_output):
        result = _parse_porcelain(sample_porcelain_output)
        assert len(result) == 3
        paths = [str(p) for p, _ in result]
        assert "/repo" in paths

    def test_detached_head(self):
        output = "worktree /repo/.claude/worktrees/detached\nHEAD abc123\ndetached\n\n"
        result = _parse_porcelain(output)
        assert len(result) == 1
        assert result[0][1] is None  # no branch


# ---------------------------------------------------------------------------
# TestReadWorktreeIndex
# ---------------------------------------------------------------------------

class TestReadWorktreeIndex:
    def test_valid_index(self, tmp_path, sample_index):
        idx_dir = tmp_path / "sdd" / "tasks" / "index"
        idx_dir.mkdir(parents=True)
        (idx_dir / "token-budget-bedrock.json").write_text(json.dumps(sample_index))
        tasks, base = _read_worktree_index(tmp_path, "token-budget-bedrock")
        assert len(tasks) == 2
        assert tasks[0].id == "TASK-3132"
        assert base == "dev"

    def test_missing_index(self, tmp_path):
        tasks, base = _read_worktree_index(tmp_path, "nonexistent")
        assert tasks == []
        assert base == "dev"

    def test_malformed_json(self, tmp_path):
        idx_dir = tmp_path / "sdd" / "tasks" / "index"
        idx_dir.mkdir(parents=True)
        (idx_dir / "bad.json").write_text("{invalid json")
        tasks, base = _read_worktree_index(tmp_path, "bad")
        assert tasks == []


# ---------------------------------------------------------------------------
# TestHealth
# ---------------------------------------------------------------------------

class TestHealth:
    # FILL IN: mock _git() calls to test _check_health
    #   - clean worktree: all counts 0
    #   - dirty worktree: dirty_count > 0
    #   - unpushed: unpushed_count > 0
    #   — bounded by AC7

    def test_health_clean(self):
        """Clean worktree returns all zeros."""
        # FILL IN: mock subprocess returns for git status + git log
        # — bounded by AC7
        ...

    def test_health_dirty(self):
        """Dirty worktree returns non-zero dirty_count."""
        # FILL IN: mock subprocess returns for git status with output
        # — bounded by AC7
        ...


# ---------------------------------------------------------------------------
# TestReadyForDone
# ---------------------------------------------------------------------------

class TestReadyForDone:
    def test_ready_when_all_done_and_clean(self):
        """All tasks done + clean + pushed = ready_for_done=True."""
        # FILL IN: construct WorktreeReport with all-done tasks, 0 health counts
        # — bounded by AC7
        ...

    def test_not_ready_when_dirty(self):
        """All done but dirty = not ready."""
        # FILL IN: WorktreeReport with dirty_count > 0
        # — bounded by AC7
        ...

    def test_not_ready_when_unpushed(self):
        """All done but unpushed = not ready."""
        # FILL IN: WorktreeReport with unpushed_count > 0
        # — bounded by AC7
        ...

    def test_not_ready_when_tasks_pending(self):
        """Some tasks pending = not ready."""
        # FILL IN: WorktreeReport with mixed statuses
        # — bounded by AC7
        ...


# ---------------------------------------------------------------------------
# TestDiscover
# ---------------------------------------------------------------------------

class TestDiscover:
    def test_end_to_end(self, tmp_path, sample_index, sample_porcelain_output):
        """Mocked git + filesystem produces correct reports."""
        # FILL IN: create tmp worktree dirs with indexes, mock git calls,
        #   call discover_worktree_reports, verify report count and fields
        # — bounded by AC2
        ...


# ---------------------------------------------------------------------------
# TestCli
# ---------------------------------------------------------------------------

class TestCli:
    def test_json_output(self, capsys):
        """--json emits valid JSON matching WorktreeReport schema."""
        # FILL IN: mock discover_worktree_reports, call main() with --json,
        #   verify output is valid JSON and each item has required fields
        # — bounded by AC2
        ...
```
**Why this shape**: Fixtures match the spec's §4 Test Data. Test classes map 1:1 to the module's functions. `FILL IN` stubs are for test bodies that require mocking subprocess/filesystem — the test structure and assertions are bounded by the spec's unit test table.

### FILL IN checklist
- [ ] `TestHealth.test_health_clean` — mock git subprocess; bounded by AC7
- [ ] `TestHealth.test_health_dirty` — mock dirty git status output; bounded by AC7
- [ ] `TestReadyForDone.test_ready_when_all_done_and_clean` — construct WorktreeReport; bounded by AC7
- [ ] `TestReadyForDone.test_not_ready_when_dirty` — dirty health; bounded by AC7
- [ ] `TestReadyForDone.test_not_ready_when_unpushed` — unpushed health; bounded by AC7
- [ ] `TestReadyForDone.test_not_ready_when_tasks_pending` — pending tasks; bounded by AC7
- [ ] `TestDiscover.test_end_to_end` — full mock discovery; bounded by AC2
- [ ] `TestCli.test_json_output` — mock + capsys; bounded by AC2

---

## Acceptance Criteria

- [ ] `tests/sdd_scripts/test_worktree_status.py` exists with all test classes
- [ ] All tests pass: `pytest tests/sdd_scripts/test_worktree_status.py -v` (AC8)
- [ ] Tests cover: _parse_branch, _parse_porcelain, _read_worktree_index, _check_health, ready_for_done, discover, CLI
- [ ] No linting errors: `ruff check tests/sdd_scripts/test_worktree_status.py`

---

## Validation Commands

- `pytest tests/sdd_scripts/test_worktree_status.py -q`

---

## Test Specification

> This task IS the test specification. All tests from spec §4 are implemented here.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/sdd-status-worktrees.spec.md` §4 Test Specification
2. **Check dependencies** — TASK-3549 must be in `tasks/completed/`
3. **Read the module** — `scripts/sdd/worktree_status.py` to understand the exact API
4. **Implement** — start from the blueprint, complete every `FILL IN` marker
5. **Verify**: `pytest tests/sdd_scripts/test_worktree_status.py -v`
6. **Move this file** to `sdd/tasks/completed/`
7. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: 
**Date**: 
**Notes**: 

**Deviations from spec**: none | describe if any
