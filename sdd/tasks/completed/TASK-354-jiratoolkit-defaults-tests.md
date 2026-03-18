# TASK-354 — Unit & Integration Tests for JiraToolkit Defaults

**Feature**: FEAT-052 — jiratoolkit-defaults
**Spec**: sdd/specs/jiratoolkit-defaults.spec.md
**Status**: pending
**Priority**: high
**Effort**: M
**Depends on**: TASK-352, TASK-353

---

## Objective

Write tests to verify that all default fields are correctly applied during ticket creation, that explicit values override defaults, and that `jira_get_components()` works.

## Deliverables

### 1. Create `tests/test_jiratoolkit_defaults.py`

#### Unit tests for `_parse_csv`

- Empty string returns `[]`
- Single value: `"backend"` → `["backend"]`
- Multiple values: `"backend,frontend"` → `["backend", "frontend"]`
- Whitespace handling: `" backend , frontend "` → `["backend", "frontend"]`
- Trailing comma: `"backend,"` → `["backend"]`

#### Unit tests for default application in `jira_create_issue`

Mock the JIRA client to capture the `fields` dict passed to `create_issue()`.

- **Test: all defaults applied** — Set all `JIRA_DEFAULT_*` env vars, call `jira_create_issue(summary="Test")`, verify:
  - `project.key == "NAV"`
  - `issuetype.name == "Task"`
  - `labels == ["backend", "ai-parrot"]`
  - `components == [{"id": "10042"}]`
  - `duedate` is today + N days
  - `timetracking.originalEstimate == "4h"`

- **Test: explicit overrides** — Set defaults, call with explicit `project="OTHER"`, `issuetype="Bug"`, `labels=["custom"]`, verify explicit values used.

- **Test: no defaults set** — No env vars, call `jira_create_issue(project="X", summary="T")`, verify only explicitly passed fields are in the dict (backward compat).

#### Integration test for `jira_get_components`

Mock `self.jira.project_components()` to return a list of mock component objects with `id`, `name`, `description` attributes. Verify the method returns the expected list of dicts.

#### Test due date offset calculation

- Set `JIRA_DEFAULT_DUE_DATE_OFFSET=7`, freeze time, verify `duedate` == today + 7 days.

## Acceptance Criteria

- All AC-1 through AC-10 are covered by at least one test.
- Tests pass with `pytest tests/test_jiratoolkit_defaults.py`.

## Files to Create

- `tests/test_jiratoolkit_defaults.py`
