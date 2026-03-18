# TASK-352 — JiraToolkit Config Defaults & Init

**Feature**: FEAT-052 — jiratoolkit-defaults
**Spec**: sdd/specs/jiratoolkit-defaults.spec.md
**Status**: pending
**Priority**: high
**Effort**: S
**Depends on**: —

---

## Objective

Add configurable default values for Jira ticket creation fields and wire them into `JiraToolkit.__init__`.

## Deliverables

### 1. Add `_parse_csv` helper function (module-level in `jiratoolkit.py`)

```python
def _parse_csv(value: str) -> List[str]:
    """Parse a comma-separated string into a list, stripping whitespace."""
    if not value:
        return []
    return [v.strip() for v in value.split(",") if v.strip()]
```

### 2. Update `JiraToolkit.__init__` to read new config variables

After the existing `self.default_project` line (~line 596), add:

```python
self.default_project = default_project or _cfg("JIRA_DEFAULT_PROJECT", "NAV")
self.default_issue_type = _cfg("JIRA_DEFAULT_ISSUE_TYPE", "Task")
self.default_labels = _parse_csv(_cfg("JIRA_DEFAULT_LABELS", "") or "")
self.default_components = _parse_csv(_cfg("JIRA_DEFAULT_COMPONENTS", "") or "")
self.default_due_date_offset = _cfg("JIRA_DEFAULT_DUE_DATE_OFFSET")
self.default_estimate = _cfg("JIRA_DEFAULT_ESTIMATE")
```

Note: The existing line `self.default_project = default_project or _cfg("JIRA_DEFAULT_PROJECT")` should be updated to include the `"NAV"` default.

### 3. Update `CreateIssueInput` model

- Change `issuetype` default from `"Story"` to `"Task"`.
- Remove the `Literal` constraint on `issuetype` — make it a plain `str` to support custom issue types.
- Add `components: Optional[List[str]]` field with description referencing `jira_get_components()`.

## Acceptance Criteria

- AC-1: `JIRA_DEFAULT_PROJECT` defaults to `"NAV"`.
- AC-2: `JIRA_DEFAULT_ISSUE_TYPE` defaults to `"Task"`.
- AC-10: No regressions — omitting new config vars preserves current behavior.

## Files to Modify

- `parrot/tools/jiratoolkit.py` — `_parse_csv`, `CreateIssueInput`, `JiraToolkit.__init__`
