# TASK-353 — Apply Defaults in jira_create_issue & Add jira_get_components

**Feature**: FEAT-052 — jiratoolkit-defaults
**Spec**: sdd/specs/jiratoolkit-defaults.spec.md
**Status**: pending
**Priority**: high
**Effort**: M
**Depends on**: TASK-352

---

## Objective

Wire default values into `jira_create_issue()` so omitted fields fall back to configured defaults. Add the `jira_get_components()` method for component ID discovery.

## Deliverables

### 1. Update `jira_create_issue()` to apply defaults

In the method body (after parameter unpacking, before building `issue_fields`), apply defaults from `self.*`:

```python
# Apply configured defaults for omitted fields
project = project or self.default_project or "NAV"
issuetype = issuetype or self.default_issue_type or "Task"
if labels is None and self.default_labels:
    labels = self.default_labels
if components is None and self.default_components:
    components = self.default_components
if due_date is None and self.default_due_date_offset:
    from datetime import datetime, timedelta
    offset_days = int(self.default_due_date_offset)
    due_date = (datetime.now() + timedelta(days=offset_days)).strftime("%Y-%m-%d")
if original_estimate is None and self.default_estimate:
    original_estimate = self.default_estimate
```

### 2. Add `components` parameter to `jira_create_issue()`

Add `components: Optional[List[str]] = None` to the method signature.

In the `issue_fields` construction, add:

```python
if components:
    issue_fields["components"] = [{"id": cid} for cid in components]
```

### 3. Update `jira_create_issue()` docstring

Add component ID resolution guidance:

```
IMPORTANT: Components must be specified by their internal Jira ID, NOT by name.
To find component IDs, first call jira_get_components(project='YOUR_PROJECT')
which returns [{"id": "10042", "name": "Backend", ...}].
Then pass the id values to the components parameter.
```

### 4. Add `jira_get_components()` method

Add near the other metadata methods (`jira_get_issue_types`, `jira_get_projects`):

```python
async def jira_get_components(self, project: Optional[str] = None) -> List[Dict[str, Any]]:
    """List all components for a project. Use this to find component IDs before creating issues.

    Example: jira.jira_get_components(project='NAV')
    Returns: [{"id": "10042", "name": "Backend", "description": "..."}, ...]
    """
    proj = project or self.default_project
    if not proj:
        raise ValueError("Project key is required for listing components")

    def _run():
        return self.jira.project_components(proj)

    components = await asyncio.to_thread(_run)
    return [
        {
            "id": c.id,
            "name": c.name,
            "description": getattr(c, "description", ""),
        }
        for c in components
    ]
```

### 5. Add `GetComponentsInput` model (optional, for tool_schema)

```python
class GetComponentsInput(BaseModel):
    """Input for listing project components."""
    project: Optional[str] = Field(default=None, description="Project key. Falls back to default project.")
```

## Acceptance Criteria

- AC-3: Default labels applied when `labels` is omitted.
- AC-4: Components parameter works with component IDs.
- AC-5: Default components applied when `components` is omitted.
- AC-6: `jira_get_components()` returns `id`, `name`, `description`.
- AC-7: Default due date offset applied correctly.
- AC-8: Default estimate applied.
- AC-9: Explicit values override all defaults.
- AC-10: No regressions when no defaults are configured.

## Files to Modify

- `parrot/tools/jiratoolkit.py` — `jira_create_issue()`, new `jira_get_components()`, `GetComponentsInput`
