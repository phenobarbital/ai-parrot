---
type: Wiki Summary
title: parrot.flows.dev_loop.nodes.deployment_handoff
id: mod:parrot.flows.dev_loop.nodes.deployment_handoff
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: DeploymentHandoffNode — push, open PR, transition Jira.
relates_to:
- concept: class:parrot.flows.dev_loop.nodes.deployment_handoff.DeploymentHandoffNode
  rel: defines
- concept: mod:parrot
  rel: references
- concept: mod:parrot.bots.flows.core.context
  rel: references
- concept: mod:parrot.bots.flows.core.types
  rel: references
- concept: mod:parrot.conf
  rel: references
- concept: mod:parrot.flows.dev_loop.models
  rel: references
- concept: mod:parrot.flows.dev_loop.nodes.base
  rel: references
---

# `parrot.flows.dev_loop.nodes.deployment_handoff`

DeploymentHandoffNode — push, open PR, transition Jira.

Implements **Module 8** of the dev-loop spec. Pure AI-Parrot — does NOT
call the dispatcher. After QA passes, this node:

1. Pushes the branch (``git push -u origin <branch_name>``).
2. Opens a PR. Primary path: ``gh pr create`` (when the CLI is on
   ``$PATH``). Fallback: a direct ``POST /repos/{owner}/{repo}/pulls``
   call via :mod:`aiohttp`. The fallback uses a personal access token
   from the environment (``GITHUB_TOKEN``).
3. Transitions the Jira ticket to *Ready to Deploy* via
   ``jira_transition_issue``.
4. Posts the PR URL as a Jira comment via ``jira_add_comment``.
5. Retries the PR step **once** with a 2 s backoff before falling back
   to the *Deployment Blocked* status.

The node does NOT raise on the *blocked* path — it returns a structured
``dict`` so the orchestrator can record the outcome cleanly.

## Classes

- **`DeploymentHandoffNode(DevLoopNode)`** — Fifth (success-path) node — handles PR creation and Jira handoff.
