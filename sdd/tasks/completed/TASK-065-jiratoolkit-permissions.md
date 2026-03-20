# TASK-065: JiraToolkit Permission Annotations

**Feature**: Granular Permissions System for Tools & Toolkits
**Spec**: `sdd/specs/granular-permission-system.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-061
**Assigned-to**: claude-opus-session

---

## Context

> This task implements Module 8 from the spec: JiraToolkit Permission Annotations.

Annotate JiraToolkit methods with `@requires_permission` to demonstrate the permission system. This serves as a reference implementation for other toolkits.

---

## Scope

- Annotate JiraToolkit methods with appropriate permissions
- Define Jira role hierarchy constant
- Leave read-only methods unrestricted (backward compatible)
- Document permission requirements in docstrings

**NOT in scope**:
- Annotating other toolkits (can be done separately)
- Implementing actual permission enforcement (handled by other tasks)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/jiratoolkit.py` | MODIFY | Add @requires_permission decorators |

---

## Implementation Notes

### Permission Hierarchy
```python
# Define at module level or in a constants file
JIRA_ROLE_HIERARCHY = {
    'jira.admin':  {'jira.manage', 'jira.write', 'jira.read'},
    'jira.manage': {'jira.write', 'jira.read'},
    'jira.write':  {'jira.read'},
    'jira.read':   set(),
}
```

### Annotation Pattern
```python
from parrot.tools.decorators import requires_permission


class JiraToolkit(AbstractToolkit):

    # ── No decorator — available to all users ──────────────────────────────
    async def search_issues(self, query: str, project: str) -> ToolResult:
        """Search for Jira issues by JQL query."""
        ...

    async def get_issue(self, issue_key: str) -> ToolResult:
        """Retrieve a single Jira issue by key."""
        ...

    # ── jira.write — developers and above ─────────────────────────────────
    @requires_permission('jira.write')
    async def create_issue(self, project: str, summary: str,
                           description: str = '') -> ToolResult:
        """Create a new Jira issue. Requires jira.write permission."""
        ...

    @requires_permission('jira.write')
    async def add_comment(self, issue_key: str, body: str) -> ToolResult:
        """Add a comment to an existing issue. Requires jira.write permission."""
        ...

    # ── jira.manage — team leads and PMs ──────────────────────────────────
    @requires_permission('jira.manage')
    async def delete_sprint(self, sprint_id: str) -> ToolResult:
        """Delete a sprint. Requires jira.manage permission."""
        ...

    # ── jira.admin — admins only ───────────────────────────────────────────
    @requires_permission('jira.admin')
    async def delete_project(self, project_key: str) -> ToolResult:
        """Permanently delete a project. Requires jira.admin permission."""
        ...
```

### Key Constraints
- Read-only methods remain unrestricted
- Update docstrings to mention permission requirements
- Use consistent naming: `jira.read`, `jira.write`, `jira.manage`, `jira.admin`

### References in Codebase
- `parrot/tools/jiratoolkit.py` — current implementation
- Spec Section 8.3 — JiraToolkit example

---

## Acceptance Criteria

- [x] Read-only methods have no decorator (unrestricted)
- [x] Write methods decorated with `@requires_permission('jira.write')`
- [x] Management methods decorated with `@requires_permission('jira.manage')` — N/A (no manage-level methods in current JiraToolkit)
- [x] Admin methods decorated with `@requires_permission('jira.admin')`
- [x] Docstrings updated to mention permission requirements
- [x] No linting errors: `ruff check parrot/tools/jiratoolkit.py`
- [x] Existing JiraToolkit tests still pass

---

## Test Specification

```python
# Add to existing JiraToolkit tests or create new file
import pytest
from parrot.tools.jiratoolkit import JiraToolkit


class TestJiraToolkitPermissions:
    def test_search_issues_unrestricted(self):
        """search_issues has no permission requirement."""
        toolkit = JiraToolkit()
        # Get the method
        method = getattr(toolkit, 'search_issues', None)
        if method:
            perms = getattr(method, '_required_permissions', None)
            assert perms is None or perms == frozenset()

    def test_create_issue_requires_write(self):
        """create_issue requires jira.write."""
        toolkit = JiraToolkit()
        method = getattr(toolkit, 'create_issue', None)
        if method:
            perms = getattr(method, '_required_permissions', frozenset())
            assert 'jira.write' in perms

    def test_delete_project_requires_admin(self):
        """delete_project requires jira.admin."""
        toolkit = JiraToolkit()
        method = getattr(toolkit, 'delete_project', None)
        if method:
            perms = getattr(method, '_required_permissions', frozenset())
            assert 'jira.admin' in perms
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-065-jiratoolkit-permissions.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-opus-session
**Date**: 2026-03-01
**Notes**:
- Added `requires_permission` import to jiratoolkit.py
- Annotated 11 write methods with `@requires_permission('jira.write')`:
  - `jira_create_issue`, `jira_update_issue`, `jira_transition_issue`
  - `jira_add_comment`, `jira_add_worklog`, `jira_add_attachment`
  - `jira_assign_issue`, `jira_update_ticket`, `jira_change_assignee`
  - `jira_add_tag`, `jira_remove_tag`
- Annotated 1 admin method with `@requires_permission('jira.admin')`:
  - `jira_configure_client`
- Left 13 read-only methods unrestricted (backward compatible):
  - `jira_get_issue`, `jira_search_issues`, `jira_get_transitions`
  - `jira_get_issue_types`, `jira_get_projects`, `jira_search_users`
  - `jira_find_issues_by_assignee`, `jira_count_issues`, `jira_aggregate_data`
  - `jira_list_transitions`, `jira_list_assignees`, `jira_list_tags`, `jira_find_user`
- Updated all modified method docstrings to mention permission requirements
- Created comprehensive test file: `tests/test_jiratoolkit_permissions.py` (27 tests)
- All tests pass, no linting errors

**Deviations from spec**:
- No `jira.manage` level methods exist in the current JiraToolkit (no delete_sprint or similar management operations)
- The spec example showed hypothetical methods; actual implementation annotates existing methods appropriately
