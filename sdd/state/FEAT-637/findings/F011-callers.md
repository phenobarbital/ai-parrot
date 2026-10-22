---
id: F011
query_id: Q011
type: grep
intent: Find all callers of jira_create_issue / jira_add_comment outside the toolkit (blast radius).
executed_at: 2026-10-07T22:57:00Z
duration_ms: 900
parent_id: null
depth: 0
---

# F011 — 1 programmatic create caller, 9 comment callers, all keyword-arg based

## Summary

`jira_create_issue` is called programmatically only by dev_loop `ResearchNode` (research.py L363, kwargs: summary/issuetype/description/assignee/fields). `jira_add_comment` has 9 call sites: jira_specialist.py L1746, and dev_loop nodes feature_handoff (L346, L504), deployment_handoff (L273, L499), failure_handler (L97), close (L96), research (L1117, L1240) — every one passes `issue=…, body=…` keywords. The `/sdd-tojira` command documents `jira_create_issue(...)` usage for agents (markdown, not Python). Adding new OPTIONAL keyword parameters (e.g. `template`, `template_params`) is backward compatible with every caller.

## Citations

- path: `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/research.py`
  lines: 363-369
  symbol: `ResearchNode`
  excerpt: |
    jira_resp = await self._jira.jira_create_issue(
        summary=brief.summary, issuetype=issuetype, description=description,
        assignee=conf.FLOW_BOT_JIRA_ACCOUNT_ID or None, fields=reporter_fields)
- path: `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/research.py`
  lines: 1117
  excerpt: |
    await self._jira.jira_add_comment(issue=issue_key, body=body)
- path: `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/failure_handler.py`
  lines: 97
  excerpt: |
    await self._jira.jira_add_comment(issue=issue_key, body=body)
- path: `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/close.py`
  lines: 96
- path: `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/feature_handoff.py`
  lines: 346, 504
- path: `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/deployment_handoff.py`
  lines: 273, 499
- path: `packages/ai-parrot/src/parrot/bots/jira_specialist.py`
  lines: 1746
- path: `.claude/commands/sdd-tojira.md`
  lines: 194, 302, 443
  excerpt: |
    - Jira tool: `JiraToolkit.jira_create_issue()`
