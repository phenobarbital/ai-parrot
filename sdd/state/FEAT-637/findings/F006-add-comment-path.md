---
id: F006
query_id: Q006
type: read
intent: Read the add-comment path: AddCommentInput + jira_add_comment.
executed_at: 2026-10-07T22:55:00Z
duration_ms: 2000
parent_id: null
depth: 0
---

# F006 — jira_add_comment / jira_update_issue: body & description pass-through

## Summary

`AddCommentInput.body` is a required `str`; `jira_add_comment(issue, body, is_internal=False, attachments=None)` calls `self.jira.add_comment(issue, body, is_internal=...)` verbatim, then uploads attachments at issue level. `jira_update_issue` similarly passes `description` straight into `update_fields["description"]`. Both are `@requires_permission("jira.write")`. Same single insertion point pattern as create: compose the body before the client call. Note the `fix(jiratoolkit): forward is_internal` commit from 2026-09-29 — the most recent touch to this method.

## Citations

- path: `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py`
  lines: 455-459
  symbol: `AddCommentInput`
  excerpt: |
    class AddCommentInput(BaseModel):
        issue: str = Field(description="Issue key or id")
        body: str = Field(description="Comment body text")
        is_internal: bool = Field(default=False, ...)
- path: `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py`
  lines: 2025-2032
  symbol: `JiraToolkit.jira_add_comment`
  excerpt: |
    @requires_permission("jira.write")
    @tool_schema(AddCommentInput)
    async def jira_add_comment(self, issue: str, body: str, is_internal: bool = False,
                               attachments: Optional[List[str]] = None) -> Dict[str, Any]:
- path: `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py`
  lines: 2049-2053
  excerpt: |
    def _run():
        return self.jira.add_comment(issue, body, is_internal=is_internal)
    comment = await asyncio.to_thread(_run)
    result = self._issue_to_dict(comment)
- path: `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py`
  lines: 1916-1931
  symbol: `JiraToolkit.jira_update_issue`
  excerpt: |
    async def jira_update_issue(self, issue: str, summary=None, description=None, ...):
- path: `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py`
  lines: 1955-1958
  excerpt: |
    if description is not None:
        update_fields["description"] = description
