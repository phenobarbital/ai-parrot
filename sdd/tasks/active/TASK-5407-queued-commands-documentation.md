# TASK-5407: Documentation — queued commands, GitHub reviewer and JobManager

**Feature**: FEAT-851 - Queued chat commands for the integrations
**Spec**: `sdd/specs/queued-commands-integrations.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5395, TASK-5396, TASK-5397, TASK-5398, TASK-5399, TASK-5400, TASK-5401, TASK-5402, TASK-5403, TASK-5404, TASK-5405, TASK-5406
**Assigned-to**: unassigned

## Context

Implements the scoped FEAT-851 deliverable below. Read spec §§2–7 for the fixed behavior and edge cases. This task creates implementation artifacts only when picked up by sdd-start.

## Scope

- Create/update exactly the three wiki pages listed by docs.policy using sdd/templates/techwiki-page.md.
- Document the delivered APIs, platform setup, reviewer flags/writes and realistic process/Redis limits.
- Add a Real implementation section before the aspirational JobManagerMixin content, clearly distinguishing that older conceptual material.

**NOT in scope**: files outside the table, new dependencies, external workers, cross-worker cancel/dedup, or changes to strict review semantics beyond the declared registration update.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `wiki/integrations/queued-commands.md` | CREATE | User/API documentation based on delivered symbols |
| `wiki/integrations/github-reviewer.md` | MODIFY | User/API documentation based on delivered symbols |
| `wiki/flows/jobmanager.md` | MODIFY | User/API documentation based on delivered symbols |

## Codebase Contract (Anti-Hallucination)

Verified against the current dev source on 2026-11-09. Existing signatures below were re-read with AST and source inspection; MODIFY anchors were re-counted with `grep -cF`. Symbols provided by dependencies are explicitly future contracts, not existing imports.

### Verified Imports

Documentation task; no implementation imports.

Standard-library imports are available; pydantic/pytest and platform SDK imports reuse the declared project stack. New imports are supplied only by this task or its named prerequisites; revalidate them when prerequisites land. Existing source relocation preserves its original import block.

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/bots/github_reviewer.py:3383
async def review_pr(self, target: str='', **kwargs: Any) -> str

# packages/ai-parrot-server/src/parrot/handlers/jobs/job.py:22
class JobManager()

# packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py:105
class TelegramAgentWrapper(OperatorCommandsMixin)

# packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py:118
class MSTeamsAgentWrapper(ActivityHandler, MessageHandler)

# packages/ai-parrot-integrations/src/parrot/integrations/slack/wrapper.py:76
class SlackAgentWrapper()
```

### Does NOT Exist

- No public queued-command wiki page exists yet.
- Do not describe external worker resumption, distributed cancellation or cross-worker dedup as implemented.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "wiki/integrations/queued-commands.md",
      "action": "CREATE"
    },
    {
      "path": "wiki/integrations/github-reviewer.md",
      "action": "MODIFY"
    },
    {
      "path": "wiki/flows/jobmanager.md",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/bots/github_reviewer.py#GitHubReviewer.review_pr",
    "sym:packages/ai-parrot-server/src/parrot/handlers/jobs/job.py#JobManager",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py#TelegramAgentWrapper",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py#MSTeamsAgentWrapper",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/slack/wrapper.py#SlackAgentWrapper"
  ]
}
```

## Implementation Notes

- For MODIFY pages integrate the template into the existing content; do not discard unrelated sections. Use the verified review_pr section to update the command behavior and the top JobManager heading to insert Real implementation.
- This task runs documentation validation, not pytest. The graph checker supports techwiki commands for documentation tasks.

**Parallelism**: TASK-5395 creates parrot.jobs exports/shims; TASK-5396 creates cancel_job/user index contracts; TASK-5397 creates queued_command and models; TASK-5398 creates service/progress APIs; TASK-5399 creates send_parsed_to_chat; TASK-5400 creates TelegramQueuedCommands; TASK-5401 creates TeamsQueuedCommands; TASK-5402 creates SlackQueuedCommands; TASK-5403 creates GitToolkit PR reads; TASK-5404 creates full-review models/report helpers; TASK-5405 creates isolated dispatch; TASK-5406 creates pr_review/config/prepare hooks. All are documented symbols; this is the sole final documentation task.

## Implementation Blueprint

Planning skeletons only: complete all bounded FILL IN items; never leave placeholders in implementation files. Preserve the spec interface signatures.

### Steps (in order)

1. Verify prerequisites and the exact anchors below — dependent files may have moved since planning.
2. Apply only the declared per-file changes — this bounds ownership and preserves unrelated behavior.
3. Complete the acceptance-criteria branches and regression tests — these pin failure, ownership and compatibility boundaries.
4. Run the task validation and format/lint touched Python files — publish complete working files only.

### `wiki/integrations/queued-commands.md` (CREATE)

```markdown
---
title: Queued chat commands
summary: Queued chat commands configuration, APIs and operational behavior.
---
# Queued chat commands
## Purpose
<!-- FILL IN: concrete delivered behavior; AC1-AC6. -->
## Public API
<!-- FILL IN: ref: links to implemented symbols; verify against dependency commits. -->
## Configuration & Parameters
<!-- FILL IN: signatures/defaults, platform prerequisites and flags; AC2-AC5. -->
## Usage Examples
<!-- FILL IN: complete command/config examples; no secrets or unimplemented API. -->
## Gotchas
<!-- FILL IN: lifecycle, limits, persistence and remote ownership; AC6. -->
## Related
<!-- FILL IN: relative links between these three pages. -->
```

**Why**: User/API documentation based on delivered symbols. Create/update exactly the three wiki pages listed by docs.policy using sdd/templates/techwiki-page.md.

### `wiki/integrations/github-reviewer.md` (MODIFY)

- Anchor `### `review_pr(target: str) -> str` — Telegram command `/review_pr``; occurrences: **1** (`grep -cF`); wiki/integrations/github-reviewer.md:386.

```markdown
---
title: GitHub reviewer
summary: GitHub reviewer configuration, APIs and operational behavior.
---
# GitHub reviewer
## Purpose
<!-- FILL IN: concrete delivered behavior; AC1-AC6. -->
## Public API
<!-- FILL IN: ref: links to implemented symbols; verify against dependency commits. -->
## Configuration & Parameters
<!-- FILL IN: signatures/defaults, platform prerequisites and flags; AC2-AC5. -->
## Usage Examples
<!-- FILL IN: complete command/config examples; no secrets or unimplemented API. -->
## Gotchas
<!-- FILL IN: lifecycle, limits, persistence and remote ownership; AC6. -->
## Related
<!-- FILL IN: relative links between these three pages. -->
```

**Why**: User/API documentation based on delivered symbols. Create/update exactly the three wiki pages listed by docs.policy using sdd/templates/techwiki-page.md.

### `wiki/flows/jobmanager.md` (MODIFY)

- Anchor `# JobManagerMixin Architecture Documentation`; occurrences: **1** (`grep -cF`); wiki/flows/jobmanager.md:1.

```markdown
---
title: JobManager
summary: JobManager configuration, APIs and operational behavior.
---
# JobManager
## Purpose
<!-- FILL IN: concrete delivered behavior; AC1-AC6. -->
## Public API
<!-- FILL IN: ref: links to implemented symbols; verify against dependency commits. -->
## Configuration & Parameters
<!-- FILL IN: signatures/defaults, platform prerequisites and flags; AC2-AC5. -->
## Usage Examples
<!-- FILL IN: complete command/config examples; no secrets or unimplemented API. -->
## Gotchas
<!-- FILL IN: lifecycle, limits, persistence and remote ownership; AC6. -->
## Related
<!-- FILL IN: relative links between these three pages. -->
```

**Why**: User/API documentation based on delivered symbols. Create/update exactly the three wiki pages listed by docs.policy using sdd/templates/techwiki-page.md.

### FILL IN checklist

- [ ] wiki/integrations/queued-commands.md — finish the scoped behavior/test branches above, bounded by AC1–AC7.
- [ ] wiki/integrations/github-reviewer.md — finish the scoped behavior/test branches above, bounded by AC1–AC7.
- [ ] wiki/flows/jobmanager.md — finish the scoped behavior/test branches above, bounded by AC1–AC7.

## Acceptance Criteria

- [ ] AC1: All three pages use techwiki frontmatter and Purpose/Public API/Configuration & Parameters/Usage Examples/Gotchas/Related sections where appropriate.
- [ ] AC2: Queued-command page documents declaration, prepare hooks, aliases, concurrency, progress, requester job controls and all platform setup.
- [ ] AC3: Slack manifest lists /pr_review, /review_pr, /jobs, /job_status, /job_cancel and optional /pr-review; Teams documents client_id and proactive delivery.
- [ ] AC4: GitHub reviewer page documents grammar, report headings, both config keys, default comment, optional draft, dry-run precedence, LLM failure and asynchronous strict command.
- [ ] AC5: JobManager page documents core imports/server identity shims, cancel_job, user filtering/index, local-first admission, bounded persistence and fresh remote reads.
- [ ] AC6: Explain queue versus execution deadlines, immutable total-lifetime expiry, local cancel/dedup, no resumption and missing cross-worker visibility during outages.
- [ ] AC7: parrot sdd techwiki check succeeds for the spec and root.

## Validation Commands

- `parrot sdd techwiki check --spec sdd/specs/queued-commands-integrations.spec.md --root .`

## Test Specification


Validate the declared wiki pages and API references after all documented symbols land.

## Agent Instructions

1. Implement in the feature worktree provisioned by `$sdd-start TASK-5407`; never implement on dev.
2. Read this task/spec and verify all dependencies in `sdd/tasks/index/queued-commands-integrations.json`.
3. Revalidate source contracts and dependency-created anchors before edits.
4. Implement only declared files, complete all FILL IN items, and run Validation Commands.
5. Commit only scoped implementation files. Use `parrot sdd task finalize` with real TaskCompletionEvidence and implementation HEAD, inspect generated Completion Note/staged state, then commit that state. Do not manually move task files.

## Completion Note

Pending; generated by task finalization with validation and commit evidence.
