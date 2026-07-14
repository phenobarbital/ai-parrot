---
type: Wiki Summary
title: parrot.flows.dev_loop._subagent_defs
id: mod:parrot.flows.dev_loop._subagent_defs
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Loader for SDD subagent definitions used by the dev-loop dispatcher.
relates_to:
- concept: func:parrot.flows.dev_loop._subagent_defs.load_subagent_definition
  rel: defines
---

# `parrot.flows.dev_loop._subagent_defs`

Loader for SDD subagent definitions used by the dev-loop dispatcher.

The dev-loop flow binds one of three subagents per dispatch:

* ``sdd-research`` — bug triage, Jira ticket, ``/sdd-spec``, ``/sdd-task``,
  worktree creation.
* ``sdd-worker`` — feature implementation inside the worktree.
* ``sdd-qa`` — deterministic acceptance verification under
  ``permission_mode="plan"``.
* ``sdd-codereview`` — read-only qualitative code-review gate (FEAT-250)
  under ``permission_mode="plan"``.

The Markdown files for each subagent are dual-sourced (per spec §7
"Patterns"):

1. **Repo-level**: ``.claude/agents/<name>.md`` — loaded by Claude Code
   from the project source tree when ``setting_sources=["project"]``.
2. **Package-shipped**: ``_subagent_data/<name>.md`` — bundled with the
   ``ai-parrot`` wheel so dispatches keep working when the package is
   installed outside the repo.

This module exposes a single helper, :func:`load_subagent_definition`,
that returns the **body** of a definition (with the YAML frontmatter
stripped) suitable for use as a plain ``system_prompt`` string when
constructing a programmatic ``claude_agent_sdk.AgentDefinition``.

## Functions

- `def load_subagent_definition(name: str) -> str` — Return the system-prompt body of an SDD subagent.
