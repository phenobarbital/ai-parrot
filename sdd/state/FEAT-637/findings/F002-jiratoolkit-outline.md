---
id: F002
query_id: Q002
type: wiki_page
intent: Outline jiratoolkit.py symbols to find create-issue / add-comment entrypoints, input models and description handling.
executed_at: 2026-10-07T22:55:00Z
duration_ms: 2000
parent_id: null
depth: 0
---

# F002 — jiratoolkit.py symbol outline (3473 lines)

## Summary

The module defines ~40 Pydantic input models (L126–565), then `class JiraToolkit(AbstractToolkit)` at L596. Write entrypoints: `jira_create_issue` (L1781), `jira_update_issue` (L1916), `jira_add_comment` (L2027). Input models: `CreateIssueInput` L375-405, `UpdateIssueInput` L408-437, `AddCommentInput` L455-467. There is NO existing symbol containing "template", "jinja" or "render" anywhere in the file (grep for `jinja|template` returned only unrelated hits: none).

## Citations

- path: `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py`
  lines: 596
  symbol: `JiraToolkit`
  excerpt: |
    class JiraToolkit(AbstractToolkit):
- path: `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py`
  lines: 698-853
  symbol: `JiraToolkit.__init__`
- path: `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py`
  lines: 1781-1914
  symbol: `JiraToolkit.jira_create_issue`
- path: `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py`
  lines: 1916-2000
  symbol: `JiraToolkit.jira_update_issue`
- path: `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py`
  lines: 2027-2092
  symbol: `JiraToolkit.jira_add_comment`
- path: `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py`
  lines: 375-405
  symbol: `CreateIssueInput`
- path: `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py`
  lines: 408-437
  symbol: `UpdateIssueInput`
- path: `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py`
  lines: 455-467
  symbol: `AddCommentInput`
- path: `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py`
  lines: 2133
  symbol: `JiraToolkit._validate_issue_type`

## Notes

No template/render helper exists in the toolkit today — the feature is greenfield inside this file.
