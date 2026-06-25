---
kind: inline
jira_key: null
fetched_at: 2026-06-24T12:00:00Z
summary_oneline: "JiraSpecialist webhook transition detection — trigger agent actions on Jira status changes"
---

# Source

Using the same approach as the GitHub Reviewer Agent, use the Jira webhooks to know
when a ticket is transitioned, useful to trigger things from the Agent.

The idea is to make the JiraSpecialist responsive to **any** Jira status transition
(not just the 3 hardcoded ones today), and allow configurable action mappings so that
when a ticket moves from one status to another, the agent can trigger appropriate
actions — notifications, workflows, other agents, etc.
