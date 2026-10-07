# Jira text templates (JiraToolkit)

Compose Jira issue descriptions and comment bodies from Jinja2 templates (FEAT-637).

## Configure

The template engine is configured on the `JiraToolkit` instance using the following parameters:

- `templates_dir` (str, optional): The directory path containing Jinja2 templates.
- `templates` (dict[str, str], optional): Inline templates mapping template names to their string content.

### Precedence and Environment Variables

1. **`templates_dir` parameter**: Explicitly passed to `JiraToolkit(templates_dir=...)`.
2. **`JIRA_TEMPLATES_DIR` environment variable**: If `templates_dir` is not provided, the toolkit checks the `JIRA_TEMPLATES_DIR` environment variable.
3. **Inline `templates` parameter**: Explicitly passed to `JiraToolkit(templates=...)`. Inline templates shadow file-based templates of the same name.

If a configured `templates_dir` (either via parameter or environment variable) does not exist on disk, a warning is logged, and the toolkit falls back to using only inline templates (if any).

## Layout and selection

Templates are resolved relative to the configured `templates_dir` or from the inline `templates` dictionary.

### Directory Layout Example

```
templates/
├── _default.j2
├── comment.j2
├── update.j2
└── nav/
    ├── _default.j2
    ├── comment.j2
    └── bug.j2
```

### Selection Precedence

When a write operation (create, update, comment) is performed, the template is selected using the following precedence:

1. **Explicit `template` parameter**: If `template` is explicitly passed (e.g., `template="bug"` or `template="bug.j2"`), it is used directly. The `.j2` suffix is optional and resolved automatically.
2. **Convention-based lookup**: If no explicit template is provided, the toolkit looks up a template based on the operation kind and context:
   - **Create Issue**: Looks for `<project>/<issuetype>.j2`, then `<project>/_default.j2`, then `_default.j2`.
   - **Update Issue**: Looks for `<project>/update.j2`, then `update.j2`.
   - **Add Comment**: Looks for `<project>/comment.j2`, then `comment.j2`.

> **Warning:** once an `update.j2` (or `<project>/update.j2`) exists, *every* `jira_update_issue` call renders it and overwrites the description. It fails if the template's variables are missing (even for a summary-only update) and if `fields['description']` is also passed.

All lookups are case-insensitive; project keys and issue types are lower-cased during resolution (e.g., `NAV` and `Bug` resolve to `nav/bug.j2`).

## Template context

Templates are rendered with a context dictionary containing relevant fields.

### Context Variables by Operation Kind

Every variable is the value passed to the tool call (``None`` when omitted).

| Operation Kind | Context Variables |
|---|---|
| **Create Issue** | `project`, `summary`, `issuetype` (canonical name), `description`, `assignee`, `priority`, `labels`, `components`, `due_date`, `parent`, `original_estimate` |
| **Update Issue** | `issue`, `project` (derived from the key), `summary`, `description`, `labels`, `due_date`, `priority`, `issuetype` |
| **Add Comment** | `issue`, `project` (derived from the key), `body`, `is_internal` |

### Overrides

- **`template_params`**: entries override same-named call variables and may add new ones.
- The call's `fields` dict is **not** exposed to templates.
- Omitted arguments are present in the context with the value `None`, so `{{ assignee }}` prints `None` and `| default('x')` does not fire; use `| default('x', true)` for optional values.
- Templates render with `StrictUndefined`: every variable a template uses must be in the context (use `| default(...)` for optional ones, or pass it in `template_params`).

## Errors and limits

- **Missing Variables**: If a template references variables that are not present in the context, a `JiraTemplateError` is raised listing all missing variables in sorted order. No write call is made to Jira (on create, the issue-type validation read happens first, because the canonical issue type is part of the template context).
- **Empty Render**: If the rendered template output is empty or contains only whitespace, a `JiraTemplateError` is raised.
- **No templates configured**: passing `template=` when neither `templates_dir` nor `templates` is configured raises `JiraTemplateError`.
- **Unknown Template**: If an explicit template is requested but cannot be found, a `JiraTemplateNotFound` error is raised.
- **`fields['description']` Conflict**: If a template is used for issue creation or update, and `fields` also contains a `description` key, a `JiraTemplateError` is raised to prevent silent overwrites.
- **Comment Body Requirement**: A comment requires either a non-empty `body` or a template that renders to a non-empty body; otherwise, a `ValueError` is raised.
- **Truncation**: Rendered text is capped at 32,767 characters (Jira's limit). If truncated, a warning is logged, and the text ends with the marker `... (truncated)`, and the total stays within the limit.

## Discovering templates

The `jira_list_templates` tool allows agents and operators to discover available templates.

### Signature

```python
await toolkit.jira_list_templates(project: str | None = None) -> dict
```

`project` keeps only templates under that (lower-cased) project folder.

### Return Shape

Names are logical (relative to the template root), sorted, and never include file paths or template source:

```json
{
  "ok": true,
  "templates": ["_default.j2", "comment.j2", "nav/_default.j2", "nav/bug.j2"],
  "templates_dir": "/etc/parrot/jira-templates"
}
```

`templates_dir` is `null` when only inline templates are configured. The tool needs no `jira.write` permission.

## Example: nav/bug.j2

### Template Definition (`nav/bug.j2`)

```jinja2
h2. Bug Report: {{ summary }}

*Description:*
{{ description }}

*Environment:*
- OS: {{ os | default('Unknown') }}
- Browser: {{ browser | default('Unknown') }}
```

### Tool Call

```python
await toolkit.jira_create_issue(
    project="NAV",
    summary="Login button is unresponsive",
    issuetype="Bug",
    description="Clicking the login button does nothing on the landing page.",
    template_params={"os": "macOS", "browser": "Safari"}
)
```

### Rendered Result (Jira Wiki Markup)

```
h2. Bug Report: Login button is unresponsive

*Description:*
Clicking the login button does nothing on the landing page.

*Environment:*
- OS: macOS
- Browser: Safari
```

## Not in v1

- **Agent Studio Field**: Configuration of `templates_dir` via Agent Studio is not supported in v1.
- **Issue Metadata in Update/Comment Context**: Fetching existing issue metadata from Jira to populate the context of update or comment templates is a planned follow-up.
