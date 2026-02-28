# TASK-065: JiraToolkit Permission Annotations

**Feature**: Granular Permissions System for Tools & Toolkits
**Spec**: `sdd/specs/granular-permission-system.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-061
**Assigned-to**: unassigned

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

- [ ] Read-only methods have no decorator (unrestricted)
- [ ] Write methods decorated with `@requires_permission('jira.write')`
- [ ] Management methods decorated with `@requires_permission('jira.manage')`
- [ ] Admin methods decorated with `@requires_permission('jira.admin')`
- [ ] Docstrings updated to mention permission requirements
- [ ] No linting errors: `ruff check parrot/tools/jiratoolkit.py`
- [ ] Existing JiraToolkit tests still pass

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

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
