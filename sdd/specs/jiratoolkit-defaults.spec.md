# Feature Specification: JiraToolkit Default Fields for Ticket Creation

**Feature ID**: FEAT-052
**Date**: 2026-03-18
**Author**: Jesus Lara
**Status**: approved
**Target version**: 1.x.x

---

## 1. Motivation & Business Requirements

### Problem Statement

When creating Jira tickets via `JiraToolkit.jira_create_issue()`, the LLM (or caller) must explicitly provide every field — project, issue type, labels, components, due date, etc. — even when most tickets in a given deployment share the same defaults. This leads to:

1. **Verbose tool calls**: The LLM must specify `project='NAV'`, `issuetype='Task'`, labels, and components on every single creation, increasing token usage and error probability.
2. **No component support**: The `jira_create_issue()` method currently has **no `components` parameter at all**, so components cannot be set at creation time without using the generic `fields` dict.
3. **Component ID resolution**: Jira's API requires components to be specified by their **internal numeric ID** (e.g., `{"id": "10042"}`), not by name. The LLM must first call `jira_get_projects()` or a component-listing method to discover the ID before creating the ticket — an extra round-trip that is error-prone and wastes tokens.
4. **No configurable defaults**: There is no way to configure default tags/labels, component, due date offset, estimated time, or issue type via `parrot.conf` or environment variables, forcing every caller to hardcode these values.

### Goals

- Add configurable default values for ticket creation fields: `project`, `issue_type`, `labels`, `components`, `due_date_offset`, and `original_estimate`.
- Add a `JIRA_DEFAULT_PROJECT` config variable (default: `NAV`) and similar config variables for other defaults.
- Add a `components` parameter to `jira_create_issue()` and `CreateIssueInput`.
- Add a `jira_get_components(project)` method that returns component `id`, `name`, and `description` so the LLM can resolve component IDs before ticket creation.
- Apply defaults at creation time: if a field is not explicitly provided, fall back to the configured default.
- Update the `jira_create_issue()` docstring to instruct the LLM to resolve component IDs via `jira_get_components()` before creating tickets with components.

### Non-Goals (explicitly out of scope)

- Changing how existing fields (assignee, priority, description) work.
- Adding defaults for `jira_update_issue()` — only creation is affected.
- Auto-resolving component names to IDs transparently (the LLM should call `jira_get_components` explicitly to learn the mapping).
- Adding a UI or interactive prompt for setting defaults.
- Modifying the Jira authentication flow.

---

## 2. Architectural Design

### Overview

The change touches three areas:

1. **Configuration layer** (`parrot/conf.py`): Add new config variables for Jira defaults.
2. **Input model** (`CreateIssueInput` in `jiratoolkit.py`): Add `components` field, update `issuetype` default to `Task`.
3. **Toolkit class** (`JiraToolkit` in `jiratoolkit.py`):
   - Read defaults from config in `__init__`.
   - Apply defaults in `jira_create_issue()` when fields are not provided.
   - Add `jira_get_components(project)` method.

### Configuration Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `JIRA_DEFAULT_PROJECT` | `NAV` | Default project key for ticket creation |
| `JIRA_DEFAULT_ISSUE_TYPE` | `Task` | Default issue type |
| `JIRA_DEFAULT_LABELS` | `""` (empty) | Comma-separated default labels, e.g. `"backend,ai-parrot"` |
| `JIRA_DEFAULT_COMPONENTS` | `""` (empty) | Comma-separated default component IDs, e.g. `"10042,10043"` |
| `JIRA_DEFAULT_DUE_DATE_OFFSET` | `""` (empty) | Days from today for default due date, e.g. `"14"` for 2 weeks |
| `JIRA_DEFAULT_ESTIMATE` | `""` (empty) | Default original estimate, e.g. `"4h"` |

All variables are read via the existing `_cfg()` helper in `JiraToolkit.__init__`.

### Flow: Creating a Ticket with Defaults

```
Caller: jira_create_issue(summary="Fix login bug")
    ↓
JiraToolkit._apply_defaults(explicit_args)
    ↓
  project  → explicit or self.default_project (from JIRA_DEFAULT_PROJECT)
  issuetype → explicit or self.default_issue_type (from JIRA_DEFAULT_ISSUE_TYPE)
  labels   → explicit or self.default_labels (from JIRA_DEFAULT_LABELS)
  components → explicit or self.default_components (from JIRA_DEFAULT_COMPONENTS)
  due_date → explicit or computed from JIRA_DEFAULT_DUE_DATE_OFFSET
  original_estimate → explicit or self.default_estimate (from JIRA_DEFAULT_ESTIMATE)
    ↓
Build issue_fields dict → JIRA API create
```

### Component Handling

Components in Jira require the internal ID format: `[{"id": "10042"}]`.

**New method**: `jira_get_components(project: str) -> List[Dict]`
- Returns: `[{"id": "10042", "name": "Backend", "description": "..."}, ...]`
- The LLM should call this **before** `jira_create_issue()` when components are needed.

**In `jira_create_issue()`**:
- New parameter: `components: Optional[List[str]]` — list of component **IDs** (strings).
- Converted to `[{"id": cid} for cid in components]` in the issue fields.

### Updated CreateIssueInput Model

```python
class CreateIssueInput(BaseModel):
    project: str = Field(default="NAV", description="Project key")
    summary: str = Field(description="Issue summary/title")
    issuetype: str = Field(default="Task", description="Issue type (default: Task)")
    description: Optional[str] = None
    assignee: Optional[str] = None
    priority: Optional[str] = None
    labels: Optional[List[str]] = None
    components: Optional[List[str]] = Field(
        default=None,
        description="List of component IDs. Use jira_get_components() to find IDs."
    )
    due_date: Optional[str] = None
    parent: Optional[str] = None
    original_estimate: Optional[str] = None
    fields: Optional[Dict[str, Any]] = None
```

### Updated JiraToolkit.__init__

```python
self.default_project = default_project or _cfg("JIRA_DEFAULT_PROJECT", "NAV")
self.default_issue_type = _cfg("JIRA_DEFAULT_ISSUE_TYPE", "Task")
self.default_labels = _parse_csv(_cfg("JIRA_DEFAULT_LABELS", ""))
self.default_components = _parse_csv(_cfg("JIRA_DEFAULT_COMPONENTS", ""))
self.default_due_date_offset = _cfg("JIRA_DEFAULT_DUE_DATE_OFFSET")
self.default_estimate = _cfg("JIRA_DEFAULT_ESTIMATE")
```

---

## 3. Acceptance Criteria

### AC-1: Default Project via Config
- **Given** `JIRA_DEFAULT_PROJECT=NAV` is set in config/env
- **When** `jira_create_issue(summary="Test")` is called without `project`
- **Then** the ticket is created in project `NAV`

### AC-2: Default Issue Type
- **Given** `JIRA_DEFAULT_ISSUE_TYPE=Task` is set
- **When** `jira_create_issue(summary="Test")` is called without `issuetype`
- **Then** the ticket is created with issue type `Task`

### AC-3: Default Labels
- **Given** `JIRA_DEFAULT_LABELS=backend,ai-parrot` is set
- **When** `jira_create_issue(summary="Test")` is called without `labels`
- **Then** the ticket is created with labels `["backend", "ai-parrot"]`
- **When** `jira_create_issue(summary="Test", labels=["frontend"])` is called
- **Then** the ticket is created with labels `["frontend"]` (explicit overrides default)

### AC-4: Components Parameter
- **Given** component ID `10042` exists in Jira
- **When** `jira_create_issue(summary="Test", components=["10042"])` is called
- **Then** the ticket is created with component `{"id": "10042"}`

### AC-5: Default Components
- **Given** `JIRA_DEFAULT_COMPONENTS=10042,10043` is set
- **When** `jira_create_issue(summary="Test")` is called without `components`
- **Then** the ticket is created with components `[{"id": "10042"}, {"id": "10043"}]`

### AC-6: Get Components Method
- **When** `jira_get_components(project="NAV")` is called
- **Then** it returns a list of dicts with keys `id`, `name`, `description`

### AC-7: Default Due Date Offset
- **Given** `JIRA_DEFAULT_DUE_DATE_OFFSET=14` is set
- **When** `jira_create_issue(summary="Test")` is called without `due_date`
- **Then** the ticket's due date is set to today + 14 days in `YYYY-MM-DD` format

### AC-8: Default Estimate
- **Given** `JIRA_DEFAULT_ESTIMATE=4h` is set
- **When** `jira_create_issue(summary="Test")` is called without `original_estimate`
- **Then** the ticket's `timetracking.originalEstimate` is set to `4h`

### AC-9: Explicit Values Override Defaults
- **Given** any defaults are configured
- **When** explicit values are passed to `jira_create_issue()`
- **Then** the explicit values are used, not the defaults

### AC-10: Backward Compatibility
- **Given** no new config variables are set
- **When** existing code calls `jira_create_issue()` as before
- **Then** behavior is identical to current behavior (no regressions)

---

## 4. Implementation Notes

### Files to Modify

| File | Changes |
|------|---------|
| `parrot/tools/jiratoolkit.py` | Add `components` to `CreateIssueInput`, update `issuetype` default to `Task`, add default fields to `__init__`, apply defaults in `jira_create_issue()`, add `jira_get_components()` method |
| `parrot/conf.py` | Add `JIRA_DEFAULT_PROJECT` (if not already there with correct default), add other `JIRA_DEFAULT_*` variables |

### Component ID Resolution Guidance for LLM

The `jira_create_issue()` docstring should include:

```
IMPORTANT: Components must be specified by their internal Jira ID, NOT by name.
To find component IDs, first call jira_get_components(project='YOUR_PROJECT')
which returns [{"id": "10042", "name": "Backend", ...}].
Then pass the id values to the components parameter.
```

### Helper Function

```python
def _parse_csv(value: str) -> List[str]:
    """Parse a comma-separated string into a list, stripping whitespace."""
    if not value:
        return []
    return [v.strip() for v in value.split(",") if v.strip()]
```

---

## 5. Testing Strategy

### Unit Tests

- Test `_parse_csv` helper with empty string, single value, multiple values, whitespace.
- Test `_apply_defaults` logic: no defaults set, all defaults set, explicit overrides.
- Test component field construction: `[{"id": cid} for cid in components]`.
- Test due date offset calculation from today.

### Integration Tests (with Jira mock)

- Create issue with only `summary` and verify all defaults applied.
- Create issue with explicit values and verify no defaults override.
- Call `jira_get_components()` and verify response structure.

---

## 6. Worktree Strategy

- **Isolation**: `per-spec` — all tasks run sequentially in one worktree.
- **Cross-feature dependencies**: None. This feature is self-contained within `jiratoolkit.py` and `conf.py`.
