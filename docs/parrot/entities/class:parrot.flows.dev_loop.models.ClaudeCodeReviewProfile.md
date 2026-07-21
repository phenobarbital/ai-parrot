---
type: Wiki Entity
title: ClaudeCodeReviewProfile
id: class:parrot.flows.dev_loop.models.ClaudeCodeReviewProfile
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Review profile for the Claude Code review dispatcher (FEAT-270).
relates_to:
- concept: class:parrot.flows.dev_loop.models.ClaudeCodeDispatchProfile
  rel: extends
---

# ClaudeCodeReviewProfile

Defined in [`parrot.flows.dev_loop.models`](../summaries/mod:parrot.flows.dev_loop.models.md).

```python
class ClaudeCodeReviewProfile(ClaudeCodeDispatchProfile)
```

Review profile for the Claude Code review dispatcher (FEAT-270).

Inherits ``ClaudeCodeDispatchProfile`` so it carries the ``setting_sources``
and ``strict_mcp_config`` fields that ``ClaudeCodeDispatcher._resolve_run_options()``
accesses. Overrides defaults for the write-enabled review use case: the
``sdd-codereview`` subagent is allowed to fix issues it finds and commit
the fixes to the worktree branch.
