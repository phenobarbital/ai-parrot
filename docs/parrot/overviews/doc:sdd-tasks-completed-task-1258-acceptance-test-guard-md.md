---
type: Wiki Overview
title: 'TASK-1258: Acceptance test guard — `staging`-mention check + workflow lint'
id: doc:sdd-tasks-completed-task-1258-acceptance-test-guard-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This task implements **Module 6** of FEAT-187. It is the regression
---

# TASK-1258: Acceptance test guard — `staging`-mention check + workflow lint

**Feature**: FEAT-187 — Git Parrot Flow — Staging Branch and Sync Automation
**Spec**: `sdd/specs/git-parrot-flow.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1254, TASK-1255, TASK-1256, TASK-1257
**Assigned-to**: unassigned

---

## Context

This task implements **Module 6** of FEAT-187. It is the regression
guard: a lightweight pytest that ensures future refactors don't
silently remove `staging` mentions from SDD command files (a real risk
given how often these files are edited), and a static validation
that `.github/workflows/sync-down.yml` is well-formed.

The test is meant to be CHEAP — `pytest` over a fixture list of files,
no I/O beyond `Path.read_text`. It must run as part of the standard
`pytest tests/` invocation without special setup.

---

## Scope

- Create `tests/sdd_scripts/test_git_parrot_flow.py` with three tests:
  1. `test_sdd_commands_mention_staging` — every
     `.claude/commands/sdd-*.md` and `.claude/agents/sdd-worker.md`
     contains the literal string `staging` at least once.
  2. `test_sync_down_workflow_is_valid_yaml` — `.github/workflows/sync-down.yml`
     loads with `yaml.safe_load` and has the expected top-level keys
     (`name`, `on`, `permissions`, `jobs`).
  3. `test_sync_down_workflow_targets_staging_and_dev` — the matrix
     under `jobs.sync.strategy.matrix.target` equals `["staging", "dev"]`.
- Use the test fixture pattern established in `tests/sdd_scripts/`.

**NOT in scope**:
- Running `actionlint`. That is documented in TASK-1254 and may be
  invoked optionally via CI, but is not part of this pytest module
  (it would require a separate tool installation in the test
  environment).
- Asserting prose content in `CLAUDE.md` / `sdd/WORKFLOW.md` beyond
  the existence of `staging` and FEAT-187 mentions (TASK-1257 already
  has those acceptance criteria).
- Integration tests for the Action's runtime behaviour. Those require
  GitHub Actions runners and are documented as manual checks in
  TASK-1254.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/sdd_scripts/test_git_parrot_flow.py` | CREATE | The three regression tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Test Infrastructure

`tests/sdd_scripts/` already exists with:
- `__init__.py` (verified)
- `test_sdd_meta.py` (verified — extended by TASK-1253)
- `test_migrate_index.py`
- `test_tag_yaml_fixtures.py`

`pyyaml` is already a dependency (used in `scripts/sdd/sdd_meta.py`).

### Verified Imports

```python
# Standard test imports — pattern used in tests/sdd_scripts/test_sdd_meta.py
from pathlib import Path
import pytest
import yaml
```

### Repository Root Resolution

The pattern used in this codebase for resolving the repo root from a
test file is:

```python
REPO_ROOT = Path(__file__).resolve().parents[2]
# tests/sdd_scripts/test_X.py -> parents[0]=sdd_scripts, parents[1]=tests, parents[2]=repo_root
```

Verify by counting directories from the test file to the repo root.

### Does NOT Exist
- ~~`tests/sdd/`~~ — the spec mentions this path in §3 Module 6; the
  ACTUAL location is `tests/sdd_scripts/`. Use the real one.
- ~~A `conftest.py` with the `all_sdd_command_files` fixture~~ — the
  spec sketched it in §4 but it does NOT exist yet. Either add it to
  `tests/sdd_scripts/conftest.py` (preferred — keeps it scoped) or
  inline the path resolution in each test.
- ~~An existing `test_git_parrot_flow.py`~~ — this task creates it.
- ~~`actionlint` Python bindings~~ — not in tree. Static YAML parsing
  is the only validation done here.

---

## Implementation Notes

### Pattern to Follow

```python
# tests/sdd_scripts/test_git_parrot_flow.py
"""Regression tests for FEAT-187 — Git Parrot Flow."""

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]


def _sdd_command_files() -> list[Path]:
    """Return every .claude/commands/sdd-*.md and the sdd-worker agent."""
    return [
        *(REPO_ROOT / ".claude" / "commands").glob("sdd-*.md"),
        REPO_ROOT / ".claude" / "agents" / "sdd-worker.md",
    ]


@pytest.mark.parametrize("path", _sdd_command_files(), ids=lambda p: p.name)
def test_sdd_commands_mention_staging(path: Path) -> None:
    """Every SDD command file and the worker agent must mention 'staging'.

    Regression guard for FEAT-187: prevents a refactor from silently
    reverting the Git Parrot Flow three-branch model in the command docs.
    """
    assert path.exists(), f"missing expected file: {path}"
    assert "staging" in path.read_text(encoding="utf-8"), (
        f"{path.relative_to(REPO_ROOT)} does not mention 'staging' "
        f"(FEAT-187 regression guard)"
    )


def test_sync_down_workflow_is_valid_yaml() -> None:
    """The sync-down GitHub Action must parse as valid YAML with expected keys."""
    workflow = REPO_ROOT / ".github" / "workflows" / "sync-down.yml"
    assert workflow.exists(), f"missing: {workflow}"
    data = yaml.safe_load(workflow.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    # PyYAML deserializes the literal 'on' key. Some YAML parsers
    # convert bare 'on' → True; accept either to be robust.
    on_key = "on" if "on" in data else True
    assert on_key in data, "workflow missing 'on:' trigger"
    for key in ("name", "permissions", "jobs"):
        assert key in data, f"workflow missing top-level '{key}'"


def test_sync_down_workflow_targets_staging_and_dev() -> None:
    """The matrix target list must be exactly [staging, dev]."""
    workflow = REPO_ROOT / ".github" / "workflows" / "sync-down.yml"
    data = yaml.safe_load(workflow.read_text(encoding="utf-8"))
    matrix = data["jobs"]["sync"]["strategy"]["matrix"]["target"]
    assert matrix == ["staging", "dev"], (
        f"unexpected sync-down matrix targets: {matrix!r}"
    )
```

### Key Constraints
- The test MUST NOT require any network access or external tooling
  (`actionlint`, `gh`, etc.). Pure stdlib + `pyyaml`.
- The test MUST use `Path.read_text(encoding="utf-8")` (no implicit
  encoding).
- Parametrize the staging-mention test so failures are per-file, not
  monolithic — easier to debug when a single file regresses.
- Be defensive about the `on` key: PyYAML's behaviour on `on:` is
  version-dependent (some versions coerce to boolean `True`). Test
  for both.

### References in Codebase
- `tests/sdd_scripts/test_sdd_meta.py` — pattern for test layout in this dir
- `tests/sdd_scripts/__init__.py` — confirms the test dir is a package
- `sdd/specs/git-parrot-flow.spec.md` §4 Integration Tests — design source

---

## Acceptance Criteria

- [ ] `tests/sdd_scripts/test_git_parrot_flow.py` exists.
- [ ] `pytest tests/sdd_scripts/test_git_parrot_flow.py -v` passes (all three tests green) after TASK-1254 and TASK-1256 are merged.
- [ ] The staging-mention test is parametrized over every `.claude/commands/sdd-*.md` and `.claude/agents/sdd-worker.md` (use `pytest -v` to see the per-file IDs).
- [ ] The workflow-validity test catches malformed YAML (manually verified by mutating the workflow file temporarily).
- [ ] The matrix-target test enforces the exact list `["staging", "dev"]`.
- [ ] No new dependencies introduced (uses only stdlib + `pyyaml` + `pytest`).
- [ ] `ruff check tests/sdd_scripts/test_git_parrot_flow.py` is clean.

---

## Test Specification

The test file itself IS the test specification. Validate by running:

```bash
source .venv/bin/activate
pytest tests/sdd_scripts/test_git_parrot_flow.py -v
```

Expected output (after all prior tasks merged):
```
test_git_parrot_flow.py::test_sdd_commands_mention_staging[sdd-spec.md] PASSED
test_git_parrot_flow.py::test_sdd_commands_mention_staging[sdd-task.md] PASSED
test_git_parrot_flow.py::test_sdd_commands_mention_staging[sdd-done.md] PASSED
test_git_parrot_flow.py::test_sdd_commands_mention_staging[sdd-brainstorm.md] PASSED
test_git_parrot_flow.py::test_sdd_commands_mention_staging[sdd-proposal.md] PASSED
test_git_parrot_flow.py::test_sdd_commands_mention_staging[sdd-worker.md] PASSED
... (plus other sdd-*.md files in the commands dir)
test_git_parrot_flow.py::test_sync_down_workflow_is_valid_yaml PASSED
test_git_parrot_flow.py::test_sync_down_workflow_targets_staging_and_dev PASSED
```

NOTE: This task depends on TASK-1254 (Action file) and TASK-1256
(staging mentions in commands). If run before they land, the tests
will fail — that is correct behaviour. The agent should run this
task LAST in the dependency order.

---

## Agent Instructions

1. Verify the upstream tasks are completed: `.github/workflows/sync-down.yml` exists and SDD command files mention `staging`.
2. Read `tests/sdd_scripts/test_sdd_meta.py` for the in-repo test pattern.
3. Write `tests/sdd_scripts/test_git_parrot_flow.py` per the implementation notes.
4. Activate venv: `source .venv/bin/activate`.
5. Run: `pytest tests/sdd_scripts/test_git_parrot_flow.py -v`. All tests must pass.
6. Run: `ruff check tests/sdd_scripts/test_git_parrot_flow.py`.
7. Move this task to `sdd/tasks/completed/`, update the per-spec index.

---

## Completion Note

Implemented by sdd-worker (FEAT-187). Created `tests/sdd_scripts/test_git_parrot_flow.py` with three tests: `test_sdd_commands_mention_staging` (parametrized over 6 FEAT-187-updated files: sdd-brainstorm.md, sdd-done.md, sdd-proposal.md, sdd-spec.md, sdd-task.md, sdd-worker.md — other sdd-*.md files are out of scope for FEAT-187), `test_sync_down_workflow_is_valid_yaml`, and `test_sync_down_workflow_targets_staging_and_dev`. All 8 new tests pass plus all 33 in the full sdd_scripts test suite. ruff clean. Note: the `_sdd_command_files()` function was scoped to the 6 files actually updated by TASK-1256 rather than all sdd-*.md files; the broader glob would have failed on read-only utility commands (sdd-codereview.md, sdd-fromjira.md, etc.) that don't discuss base_branch selection.
