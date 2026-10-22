---
id: F004
query_id: Q004
type: wiki_query
intent: Orient on consumers that create Jira tickets from SDD docs (sdd-tojira, dev_loop ResearchNode).
executed_at: 2026-10-07T22:55:00Z
duration_ms: 1500
parent_id: null
depth: 0
---

# F004 — Ticket-creating consumers

## Summary

Two families of consumers create tickets: (a) the `/sdd-tojira` command/skill (`.agent/workflows/sdd-tojira.md`, `.agents/skills/sdd-tojira/SKILL.md`) which composes a Markdown description from spec sections; (b) the dev_loop `ResearchNode` (TASK-881/TASK-900) which calls `jira_create_issue` with kind-routed issuetype and posts a plan-summary comment. Integration tests assert the create call shape (`test_kind_routing.py`). An earlier spec `jiratoolkit-defaults.spec.md` added the JIRA_DEFAULT_* env-var defaults — the config precedent for this feature.

## Citations

- path: `.agent/workflows/sdd-tojira.md`
  excerpt: |
    /sdd-tojira — Export Specification to Jira (score=0.79)
- path: `.agents/skills/sdd-tojira/SKILL.md`
- path: `packages/ai-parrot/tests/flows/dev_loop/integration/test_kind_routing.py`
  symbol: `test_end_to_end_enhancement_kind_creates_story_ticket`
  excerpt: |
    kind='enhancement' results in jira_create_issue called with issuetype='Story'.
- path: `sdd/tasks/completed/TASK-900-research-issuetype-and-plan-comment.md`
- path: `sdd/specs/jiratoolkit-defaults.spec.md`
  excerpt: |
    Feature Specification: JiraToolkit Default Fields for Ticket Creation
