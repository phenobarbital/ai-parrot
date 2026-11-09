# TASK-5402: Add Slack queued commands with bounded ephemeral acknowledgement

**Feature**: FEAT-851 - Queued chat commands for the integrations
**Spec**: `sdd/specs/queued-commands-integrations.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5398
**Assigned-to**: unassigned

## Context

Implements the scoped FEAT-851 deliverable below. Read spec §§2–7 for the fixed behavior and edge cases. This task creates implementation artifacts only when picked up by sdd-start.

## Scope

- Register queued commands, aliases and requester controls through SlackCommandRouter for webhook and socket paths.
- Configure prepare_timeout=admission_timeout=2.0 and preserve local-first start.
- Wire start/stop/help and deliver parsed blocks to the captured channel with requester mention.

**NOT in scope**: files outside the table, new dependencies, external workers, cross-worker cancel/dedup, or changes to strict review semantics beyond the declared registration update.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/slack/commands/queued_commands.py` | CREATE | Slack admission and channel delivery |
| `packages/ai-parrot-integrations/src/parrot/integrations/slack/wrapper.py` | MODIFY | Adapter registration, lifecycle and help |
| `packages/ai-parrot-integrations/tests/integrations/slack/test_queued_commands_slack.py` | CREATE | Task-owned regression coverage |

## Codebase Contract (Anti-Hallucination)

Verified against the current dev source on 2026-11-09. Existing signatures below were re-read with AST and source inspection; MODIFY anchors were re-counted with `grep -cF`. Symbols provided by dependencies are explicitly future contracts, not existing imports.

### Verified Imports

```python
from typing import Any, List, Optional
from parrot.integrations.slack.commands import SlackCommandRouter
from parrot.integrations.core.queued import QueuedCommand, Requester, JobNotice, QueuedCommandService, discover_queued_commands
from parrot.integrations.parser import parse_response
import pytest
from .commands.queued_commands import register_queued_commands
from parrot.integrations.core.queued.messages import JOB_COMMANDS, format_ack, format_notice_header, format_job_view, format_job_list, format_cancel
```

Standard-library imports are available; pydantic/pytest and platform SDK imports reuse the declared project stack. New imports are supplied only by this task or its named prerequisites; revalidate them when prerequisites land. Existing source relocation preserves its original import block.

### Existing Signatures to Use

```python
# packages/ai-parrot-integrations/src/parrot/integrations/slack/commands/__init__.py:50
def register(self, command: str, handler: Callable) -> None

# packages/ai-parrot-integrations/src/parrot/integrations/slack/commands/__init__.py:68
async def dispatch(self, command: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]

# packages/ai-parrot-integrations/src/parrot/integrations/slack/wrapper.py:171
async def start(self) -> None

# packages/ai-parrot-integrations/src/parrot/integrations/slack/wrapper.py:183
async def stop(self) -> None

# packages/ai-parrot-integrations/src/parrot/integrations/slack/wrapper.py:608
def _help_text(self) -> str

# packages/ai-parrot-integrations/src/parrot/integrations/slack/wrapper.py:562
def _build_blocks(parsed: ParsedResponse) -> List[Dict[str, Any]]

# packages/ai-parrot-integrations/src/parrot/integrations/slack/wrapper.py:674
async def post_message(self, channel: str, text: str, blocks: Optional[List[Dict[str, Any]]]=None, thread_ts: Optional[str]=None) -> Optional[str]
```

### Does NOT Exist

- SlackQueuedCommands and agent-method slash routes do not exist yet.
- Redis health is not an admission prerequisite; no response_url-only completion path is needed.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-integrations/src/parrot/integrations/slack/commands/queued_commands.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-integrations/src/parrot/integrations/slack/wrapper.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-integrations/tests/integrations/slack/test_queued_commands_slack.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/slack/commands/__init__.py#SlackCommandRouter.register",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/slack/commands/__init__.py#SlackCommandRouter.dispatch",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/slack/wrapper.py#SlackAgentWrapper.start",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/slack/wrapper.py#SlackAgentWrapper.stop",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/slack/wrapper.py#SlackAgentWrapper._help_text",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/slack/wrapper.py#SlackAgentWrapper._build_blocks",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/slack/wrapper.py#SlackAgentWrapper.post_message"
  ]
}
```

## Implementation Notes



**Parallelism**: TASK-5398 supplies QueuedCommandService.submit/start/stop and requester-scoped controls; Slack adapter/wrapper/test files have no overlapping writers.

## Implementation Blueprint

Planning skeletons only: complete all bounded FILL IN items; never leave placeholders in implementation files. Preserve the spec interface signatures.

### Steps (in order)

1. Verify prerequisites and the exact anchors below — dependent files may have moved since planning.
2. Apply only the declared per-file changes — this bounds ownership and preserves unrelated behavior.
3. Complete the acceptance-criteria branches and regression tests — these pin failure, ownership and compatibility boundaries.
4. Run the task validation and format/lint touched Python files — publish complete working files only.

### `packages/ai-parrot-integrations/src/parrot/integrations/slack/commands/queued_commands.py` (CREATE)

```python
"""Slack queued slash commands with a bounded acknowledgement path."""
from typing import Any, List, Optional
from parrot.integrations.slack.commands import SlackCommandRouter
from parrot.integrations.core.queued import QueuedCommand, Requester, JobNotice, QueuedCommandService, discover_queued_commands
from parrot.integrations.parser import parse_response

class SlackQueuedCommands:
    """Own a Slack wrapper's background commands and registered names."""
    def __init__(self, wrapper: Any, commands: List[QueuedCommand]) -> None:
        """Set prepare_timeout and admission_timeout to 2.0 seconds."""
        # FILL IN: wrapper owner/name and local service setup; AC1.
    def register(self, router: SlackCommandRouter) -> List[str]:
        """Register async payload-to-dict handlers; return names for help/manifest."""
        # FILL IN: AC1-AC3. Requester from user_id/channel_id, args from payload.text.
        # Return {response_type: ephemeral, text: format_ack(outcome)}.
        # deliver: post_message(channel, text=mention+header+parsed.text, blocks=_build_blocks(parsed)).
        raise NotImplementedError
    async def start(self) -> None:
        """Initialize local execution without awaiting Redis health."""
        await self.service.start()
    async def shutdown(self) -> None:
        """Deliver interruptions and stop the service."""
        await self.service.stop()

def register_queued_commands(router: SlackCommandRouter, wrapper: Any) -> Optional[SlackQueuedCommands]:
    """Register discovered commands, or return None."""
    commands = discover_queued_commands(wrapper.agent)
    if not commands:
        return None
    holder = SlackQueuedCommands(wrapper, commands)
    holder.register(router)
    return holder
```

**Why**: Slack admission and channel delivery. Register queued commands, aliases and requester controls through SlackCommandRouter for webhook and socket paths.

### `packages/ai-parrot-integrations/src/parrot/integrations/slack/wrapper.py` (MODIFY)

- Anchor `self._command_router = SlackCommandRouter()`; occurrences: **1** (`grep -cF`); packages/ai-parrot-integrations/src/parrot/integrations/slack/wrapper.py:123.
- Anchor `async def stop(self) -> None:`; occurrences: **1** (`grep -cF`); packages/ai-parrot-integrations/src/parrot/integrations/slack/wrapper.py:183.
- Anchor `def _help_text(self) -> str:`; occurrences: **1** (`grep -cF`); packages/ai-parrot-integrations/src/parrot/integrations/slack/wrapper.py:608.

```python
# AFTER router construction:
self._queued_commands = register_queued_commands(self._command_router, self)
# In start(), before accepting incoming commands:
if self._queued_commands is not None:
    await self._queued_commands.start()
# In stop(), before cancelling _background_tasks:
if self._queued_commands is not None:
    await self._queued_commands.shutdown()
# FILL IN: _help_text includes registered queued/job names and descriptions; AC3.
```

**Why**: Adapter registration, lifecycle and help. Register queued commands, aliases and requester controls through SlackCommandRouter for webhook and socket paths.

### `packages/ai-parrot-integrations/tests/integrations/slack/test_queued_commands_slack.py` (CREATE)

```python
"""Regression coverage for Add Slack queued commands with bounded ephemeral acknowledgement."""
import pytest

async def test_slack_handler_returns_ephemeral_ack() -> None:
    """Verify the corresponding Test Specification behavior below."""
    # FILL IN: arrange deterministic doubles and assert the named behavior; see ACs.
    raise NotImplementedError

async def test_slack_delivery_posts_to_channel_with_mention() -> None:
    """Verify the corresponding Test Specification behavior below."""
    # FILL IN: arrange deterministic doubles and assert the named behavior; see ACs.
    raise NotImplementedError

async def test_slack_stop_shuts_down_queued() -> None:
    """Verify the corresponding Test Specification behavior below."""
    # FILL IN: arrange deterministic doubles and assert the named behavior; see ACs.
    raise NotImplementedError

async def test_slack_ack_with_slow_or_unavailable_redis() -> None:
    """Verify the corresponding Test Specification behavior below."""
    # FILL IN: arrange deterministic doubles and assert the named behavior; see ACs.
    raise NotImplementedError
```

**Why**: Task-owned regression coverage. Register queued commands, aliases and requester controls through SlackCommandRouter for webhook and socket paths.

### FILL IN checklist

- [ ] packages/ai-parrot-integrations/src/parrot/integrations/slack/commands/queued_commands.py — finish the scoped behavior/test branches above, bounded by AC1–AC4.
- [ ] packages/ai-parrot-integrations/src/parrot/integrations/slack/wrapper.py — finish the scoped behavior/test branches above, bounded by AC1–AC4.
- [ ] packages/ai-parrot-integrations/tests/integrations/slack/test_queued_commands_slack.py — finish the scoped behavior/test branches above, bounded by AC1–AC4.

## Acceptance Criteria

- [ ] AC1: First and subsequent webhook/socket dispatches acknowledge within 3 seconds when Redis stalls beyond 5 seconds or fails.
- [ ] AC2: Ack response is ephemeral; completion posts to the original channel with <@user> plus shared notice header and parsed text/blocks.
- [ ] AC3: Queued and job commands appear in help; authorization/signature checks remain before dispatch.
- [ ] AC4: stop shuts down the adapter before cancelling other background tasks; prepare timeout admits no job/reservation.

## Validation Commands

- `pytest packages/ai-parrot-integrations/tests/integrations/slack/test_queued_commands_slack.py -q`

## Test Specification

| Test | Module | Required behavior |
|---|---|---|
| `test_slack_handler_returns_ephemeral_ack` | M5 | router dispatch of `pr_review` returns `{"response_type": "ephemeral", "text": <ack>}` |
| `test_slack_delivery_posts_to_channel_with_mention` | M5 | deliver calls `post_message(channel, "<@U…> …", blocks=…)` |
| `test_slack_stop_shuts_down_queued` | M5 | `stop()` awaits the adapter shutdown |
| `test_slack_ack_with_slow_or_unavailable_redis` | M2/M5 | First and subsequent webhook/socket dispatch acknowledgements finish inside 3 s when Redis save/connect stalls beyond 5 s; accepted local jobs remain runnable; prepare timeout creates no job/reservation |

Use deterministic doubles for external systems; no live platform/GitHub/LLM credentials. Add all scoped AC cases, not only the scaffold examples. Store test logs under artifacts/logs/.

## Agent Instructions

1. Implement in the feature worktree provisioned by `$sdd-start TASK-5402`; never implement on dev.
2. Read this task/spec and verify all dependencies in `sdd/tasks/index/queued-commands-integrations.json`.
3. Revalidate source contracts and dependency-created anchors before edits.
4. Implement only declared files, complete all FILL IN items, and run Validation Commands.
5. Commit only scoped implementation files. Use `parrot sdd task finalize` with real TaskCompletionEvidence and implementation HEAD, inspect generated Completion Note/staged state, then commit that state. Do not manually move task files.

## Completion Note

Pending; generated by task finalization with validation and commit evidence.
