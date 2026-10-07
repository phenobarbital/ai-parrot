---
id: F005
query_id: Q005
type: read
intent: Read the create-issue path: CreateIssueInput + jira_create_issue + description formatting.
executed_at: 2026-10-07T22:55:00Z
duration_ms: 3000
parent_id: null
depth: 0
---

# F005 — jira_create_issue: description is passed through verbatim

## Summary

`CreateIssueInput.description` is a plain `Optional[str]`. `jira_create_issue` applies JIRA_DEFAULT_* fallbacks (project, issuetype, labels, components, due_date, estimate), validates the issuetype via `_validate_issue_type`, builds `issue_fields` and, when truthy, sets `issue_fields["description"] = description` with no transformation, then calls `self.jira.create_issue(fields=issue_fields)` inside `asyncio.to_thread` + `wait_for`. The method is decorated `@requires_permission("jira.write")` + `@tool_schema(CreateIssueInput)`. There is a natural single insertion point for template composition: just before `issue_fields["description"]` is set.

## Citations

- path: `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py`
  lines: 375-379
  symbol: `CreateIssueInput`
  excerpt: |
    class CreateIssueInput(BaseModel):
        project: str = Field(default="NAV", ...)
        summary: str = Field(description="Issue summary/title")
        issuetype: str = Field(default="Task", ...)
        description: Optional[str] = Field(default=None, description="Issue description")
- path: `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py`
  lines: 1779-1795
  symbol: `JiraToolkit.jira_create_issue`
  excerpt: |
    @requires_permission("jira.write")
    @tool_schema(CreateIssueInput)
    async def jira_create_issue(self, project=None, summary="", issuetype=None,
        description=None, assignee=None, priority=None, labels=None, components=None,
        due_date=None, parent=None, original_estimate=None, fields=None) -> Dict[str, Any]:
- path: `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py`
  lines: 1836-1850
  excerpt: |
    # Apply configured defaults for omitted fields
    project = project or self.default_project or "NAV"
    issuetype = issuetype or self.default_issue_type or "Task"
    if labels is None and self.default_labels: labels = list(self.default_labels)
- path: `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py`
  lines: 1866-1874
  excerpt: |
    issue_fields: Dict[str, Any] = {"project": {"key": project}, "summary": summary,
                                    "issuetype": {"name": canonical_issuetype}}
    if description:
        issue_fields["description"] = description
- path: `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py`
  lines: 1894-1913
  excerpt: |
    def _run():
        return self.jira.create_issue(fields=issue_fields)
    obj = await asyncio.wait_for(asyncio.to_thread(_run), timeout=self.request_timeout + 5)
    data = self._issue_to_dict(obj)
    return {"ok": True, "id": data.get("id"), "key": data.get("key"), "issue": data}
