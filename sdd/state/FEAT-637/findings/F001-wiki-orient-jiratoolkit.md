---
id: F001
query_id: Q001
type: wiki_query
intent: Orient: locate JiraToolkit, its create/comment tools and tests in the knowledge graph.
executed_at: 2026-10-07T22:55:00Z
duration_ms: 1500
parent_id: null
depth: 0
---

# F001 — Wiki orientation: JiraToolkit write tools and tests

## Summary

JiraToolkit lives in the ai-parrot-tools distribution. The wiki ranks its write tools `jira_add_comment` / `jira_add_worklog`, the `AddCommentInput` model, and three test modules (comment attachments, permissions, delegation). The read side is a separate read-only `JiraInterface` ("writes stay in JiraToolkit"). A pre-wired `mock_jira` fixture exists in the dev_loop conftest.

## Citations

- path: `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py`
  symbol: `JiraToolkit.jira_add_comment`
  excerpt: |
    wiki: sym:...#JiraToolkit.jira_add_comment — Add a comment to an issue, optionally attaching files. (score=0.40)
- path: `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py`
  symbol: `AddCommentInput`
  excerpt: |
    wiki: sym:...#AddCommentInput — Input for adding a comment to an issue.
- path: `packages/ai-parrot/tests/test_jira_comment_attachments.py`
  excerpt: |
    wiki: Tests for jira_add_comment with attachment support. (score=0.51)
- path: `packages/ai-parrot/tests/interfaces/jira/test_jira_interface.py`
  symbol: `TestReadOnlySurface.test_no_write_methods_exposed`
  excerpt: |
    This interface is read-only; writes stay in JiraToolkit.
- path: `packages/ai-parrot/tests/flows/dev_loop/conftest.py`
  symbol: `mock_jira`
  excerpt: |
    A pre-wired JiraToolkit mock for node tests.
