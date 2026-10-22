---
id: F014
query_id: Q014
type: grep
intent: Does any markdown→Jira markup / ADF conversion exist that rendering must precede?
executed_at: 2026-10-07T22:57:00Z
duration_ms: 500
parent_id: null
depth: 0
---

# F014 — No markup conversion exists: toolkit sends raw strings; sdd-tojira's curl path uses ADF

## Summary

Zero matches for `markdown_to_jira|to_adf|jira_markup|wiki_markup|adf` in `parrot/interfaces`, `jiratoolkit.py` and `research.py`. The toolkit hands the description/body string to pycontribs `JIRA.create_issue/add_comment` unchanged (REST v2 wiki-markup text). Only the `/sdd-tojira` *curl fallback* posts an ADF `{"type":"doc","version":1}` document via REST v3 — a different path. Consequence: a template's output is Jira wiki markup (or plain text) and must NOT be HTML-escaped; there is no post-render conversion stage to coordinate with.

## Citations

- path: `.agent/workflows/sdd-tojira.md`
  lines: 148-160
  excerpt: |
    **Description format:**
    ## Motivation / ## Architectural Overview / ## Acceptance Criteria   (markdown headings)
- path: `.agent/workflows/sdd-tojira.md`
  lines: 214
  excerpt: |
    "description": {"type": "doc", "version": 1, "content": [...]},   (REST v3 ADF, curl fallback only)
- path: `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py`
  lines: 1872-1873
  excerpt: |
    if description:
        issue_fields["description"] = description
