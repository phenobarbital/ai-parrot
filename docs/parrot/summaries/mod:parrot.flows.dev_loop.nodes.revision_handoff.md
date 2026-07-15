---
type: Wiki Summary
title: parrot.flows.dev_loop.nodes.revision_handoff
id: mod:parrot.flows.dev_loop.nodes.revision_handoff
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: RevisionHandoffNode — push to the existing branch + comment the same PR.
relates_to:
- concept: class:parrot.flows.dev_loop.nodes.revision_handoff.RevisionHandoffNode
  rel: defines
- concept: mod:parrot.bots.flows.core.context
  rel: references
- concept: mod:parrot.bots.flows.core.types
  rel: references
- concept: mod:parrot.flows.dev_loop.nodes.base
  rel: references
---

# `parrot.flows.dev_loop.nodes.revision_handoff`

RevisionHandoffNode — push to the existing branch + comment the same PR.

Implements the handoff half of **Module 9** (FEAT-250 G6). On the revision
path (a reviewer asked for changes on a draft PR), this terminal-ish node:

1. ``git push`` to the **existing** feature branch (subprocess, mirroring
   ``DeploymentHandoffNode._push_branch``), and
2. ``git_toolkit.add_pr_comment(pr_number, …)`` on the **same** PR.

It MUST NOT call ``create_pull_request`` — the revision loop updates the
existing draft PR, it never opens a new one. Like the other terminal nodes it
never raises: failures degrade to a structured status dict.

## Classes

- **`RevisionHandoffNode(DevLoopNode)`** — Revision-path handoff — push existing branch + comment existing PR.
