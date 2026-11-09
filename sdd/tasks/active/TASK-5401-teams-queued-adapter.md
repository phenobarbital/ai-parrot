# TASK-5401: Add Teams queued commands, proactive delivery and shutdown

**Feature**: FEAT-851 - Queued chat commands for the integrations
**Spec**: `sdd/specs/queued-commands-integrations.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5398, TASK-5400
**Assigned-to**: unassigned

## Context

Implements the scoped FEAT-851 deliverable below. Read spec §§2–7 for the fixed behavior and edge cases. This task creates implementation artifacts only when picked up by sdd-start.

## Scope

- Create TeamsQueuedCommands and register_queued_commands; wire wrapper registration and close_queued_commands.
- Capture conversation references at admission, refuse missing client_id, and guard generic method invocation.
- Extend only the Teams branch of IntegrationBotManager.shutdown, preserving the preceding Telegram task changes.

**NOT in scope**: files outside the table, new dependencies, external workers, cross-worker cancel/dedup, or changes to strict review semantics beyond the declared registration update.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/commands/queued_commands.py` | CREATE | Teams routes with proactive completion |
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py` | MODIFY | Register independently of uploads and expose shutdown |
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/commands/agent_commands.py` | MODIFY | Guard both generic invocation routes |
| `packages/ai-parrot-integrations/src/parrot/integrations/manager.py` | MODIFY | Close Teams jobs with isolated error handling |
| `packages/ai-parrot-integrations/tests/integrations/msteams/test_queued_commands_msteams.py` | CREATE | Task-owned regression coverage |

## Codebase Contract (Anti-Hallucination)

Verified against the current dev source on 2026-11-09. Existing signatures below were re-read with AST and source inspection; MODIFY anchors were re-counted with `grep -cF`. Symbols provided by dependencies are explicitly future contracts, not existing imports.

### Verified Imports

```python
from typing import Any, List, Optional
from botbuilder.core import TurnContext
from parrot.integrations.msteams.commands import MSTeamsCommandRouter, command_args
from parrot.integrations.core.queued import QueuedCommand, Requester, JobNotice, QueuedCommandService, discover_queued_commands, queued_spec_of
from parrot.integrations.parser import parse_response
import pytest
from .commands.queued_commands import register_queued_commands
from parrot.integrations.core.queued import QueuedCommand, Requester, JobNotice, QueuedCommandService, discover_queued_commands
from parrot.integrations.core.queued.messages import JOB_COMMANDS, format_ack, format_notice_header, format_job_view, format_job_list, format_cancel
```

Standard-library imports are available; pydantic/pytest and platform SDK imports reuse the declared project stack. New imports are supplied only by this task or its named prerequisites; revalidate them when prerequisites land. Existing source relocation preserves its original import block.

### Existing Signatures to Use

```python
# packages/ai-parrot-integrations/src/parrot/integrations/msteams/commands/__init__.py:81
def register(self, command: str, handler: Callable) -> None

# packages/ai-parrot-integrations/src/parrot/integrations/msteams/commands/__init__.py:32
def command_args(turn_context: 'TurnContext') -> str

# packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py:150
def __init__(self, agent: Any, config: MSTeamsAgentConfig, app: web.Application, forms_directory: Optional[str]=None, voice_config: Optional[VoiceTranscriberConfig]=None, oauth_manager: Optional['JiraOAuthManager']=None, connection_service_factory: Optional[Callable[[], Any]]=None)

# packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py:1720
async def _send_parsed_response(self, parsed: Union[ParsedResponse, Dict[str, Any]], turn_context: TurnContext) -> None

# packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py:1419
async def close_voice_transcriber(self) -> None

# packages/ai-parrot-integrations/src/parrot/integrations/msteams/commands/agent_commands.py:156
async def handle_function(self, turn_context) -> None

# packages/ai-parrot-integrations/src/parrot/integrations/msteams/commands/agent_commands.py:200
async def handle_call(self, turn_context) -> None

# packages/ai-parrot-integrations/src/parrot/integrations/manager.py:1150
async def shutdown(self) -> None
```

### Does NOT Exist

- Teams wrappers have no close()/stop(); add close_queued_commands only.
- No per-request Teams ContextVar or group-capable stored reference is assumed.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-integrations/src/parrot/integrations/msteams/commands/queued_commands.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-integrations/src/parrot/integrations/msteams/commands/agent_commands.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-integrations/src/parrot/integrations/manager.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-integrations/tests/integrations/msteams/test_queued_commands_msteams.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/msteams/commands/__init__.py#MSTeamsCommandRouter.register",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/msteams/commands/__init__.py#command_args",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py#MSTeamsAgentWrapper.__init__",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py#MSTeamsAgentWrapper._send_parsed_response",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py#MSTeamsAgentWrapper.close_voice_transcriber",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/msteams/commands/agent_commands.py#AgentCommandHandler.handle_function",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/msteams/commands/agent_commands.py#AgentCommandHandler.handle_call",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/manager.py#IntegrationBotManager.shutdown"
  ]
}
```

## Implementation Notes



**Parallelism**: TASK-5398 supplies QueuedCommandService; TASK-5400 also modifies integrations/manager.py, so its Telegram shutdown changes must land before this task edits the Teams shutdown branch.

## Implementation Blueprint

Planning skeletons only: complete all bounded FILL IN items; never leave placeholders in implementation files. Preserve the spec interface signatures.

### Steps (in order)

1. Verify prerequisites and the exact anchors below — dependent files may have moved since planning.
2. Apply only the declared per-file changes — this bounds ownership and preserves unrelated behavior.
3. Complete the acceptance-criteria branches and regression tests — these pin failure, ownership and compatibility boundaries.
4. Run the task validation and format/lint touched Python files — publish complete working files only.

### `packages/ai-parrot-integrations/src/parrot/integrations/msteams/commands/queued_commands.py` (CREATE)

```python
"""MS Teams queued-command routing and proactive result delivery."""
from typing import Any, List, Optional
from botbuilder.core import TurnContext
from parrot.integrations.msteams.commands import MSTeamsCommandRouter, command_args
from parrot.integrations.core.queued import QueuedCommand, Requester, JobNotice, QueuedCommandService, discover_queued_commands
from parrot.integrations.parser import parse_response

class TeamsQueuedCommands:
    """Own one Teams wrapper's service and captured conversation callbacks."""
    def __init__(self, wrapper: Any, commands: List[QueuedCommand]) -> None:
        """Capture local dependencies without contacting Redis."""
        # FILL IN: initialize wrapper/commands/service; AC1-AC3.
    def register(self, router: MSTeamsCommandRouter) -> None:
        """Register async turn-context handlers and owner-scoped controls."""
        # FILL IN: AC1-AC3; refuse absent client_id before submit.
        # conv_ref = TurnContext.get_conversation_reference(turn_context.activity)
        # deliver awaits wrapper.adapter.continue_conversation(conv_ref, callback, client_id)
        # callback uses wrapper._send_parsed_response(parsed, context).
        raise NotImplementedError
    async def shutdown(self) -> None:
        """Stop the service before platform resources close."""
        await self.service.stop()

def register_queued_commands(router: MSTeamsCommandRouter, wrapper: Any) -> Optional[TeamsQueuedCommands]:
    """Discover and register, returning None when no queued command exists."""
    commands = discover_queued_commands(wrapper.agent)
    if not commands:
        return None
    holder = TeamsQueuedCommands(wrapper, commands)
    holder.register(router)
    return holder
```

**Why**: Teams routes with proactive completion. Create TeamsQueuedCommands and register_queued_commands; wire wrapper registration and close_queued_commands.

### `packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py` (MODIFY)

- Anchor `self._knowledge_upload = register_knowledge_upload_commands(self._command_router, self)`; occurrences: **1** (`grep -cF`); packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py:218.
- Anchor `async def close_voice_transcriber(self) -> None:`; occurrences: **1** (`grep -cF`); packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py:1419.

```python
# AFTER the knowledge-upload registration block, OUTSIDE its try/condition:
self._queued_commands = register_queued_commands(self._command_router, self)
# BEFORE close_voice_transcriber:
async def close_queued_commands(self) -> None:
    """Stop queued commands if this wrapper registered any."""
    if self._queued_commands is not None:
        await self._queued_commands.shutdown()
```

**Why**: Register independently of uploads and expose shutdown. Create TeamsQueuedCommands and register_queued_commands; wire wrapper registration and close_queued_commands.

### `packages/ai-parrot-integrations/src/parrot/integrations/msteams/commands/agent_commands.py` (MODIFY)

- Anchor `if method_name.startswith("_") or method_name in self._BLOCKED_METHODS:`; occurrences: **2** (`grep -cF`); packages/ai-parrot-integrations/src/parrot/integrations/msteams/commands/agent_commands.py:178,218.
  Context in AgentCommandHandler.handle_function at line 178:
```python
            return

        if method_name.startswith("_") or method_name in self._BLOCKED_METHODS:
            await self._send_text(
                turn_context, f"Method '{method_name}' cannot be invoked directly."
```
  Context in AgentCommandHandler.handle_call at line 218:
```python
            return

        if method_name.startswith("_") or method_name in self._BLOCKED_METHODS:
            await self._send_text(
                turn_context, f"Method '{method_name}' cannot be invoked directly."
```

```python
# In BOTH handle_function and handle_call, after blocked-name validation and
# resolving the public method, but before invoking it:
spec = queued_spec_of(method)
if spec is not None:
    await self.wrapper.send_text(f"Use /{spec.command} — it runs in the background.", turn_context)
    return
# Both handlers own self.agent/self.wrapper; preserve _send_text and existing error handling.
```

**Why**: Guard both generic invocation routes. Create TeamsQueuedCommands and register_queued_commands; wire wrapper registration and close_queued_commands.

### `packages/ai-parrot-integrations/src/parrot/integrations/manager.py` (MODIFY)

- Anchor `for name, wrapper in self.msteams_bots.items():`; occurrences: **1** (`grep -cF`); packages/ai-parrot-integrations/src/parrot/integrations/manager.py:1196.

```python
# Inside the msteams_bots shutdown loop, before other wrapper resources close:
try:
    await wrapper.close_queued_commands()
except Exception as exc:
    self.logger.error("Error closing queued commands for MS Teams bot '%s': %s", name, exc)
```

**Why**: Close Teams jobs with isolated error handling. Create TeamsQueuedCommands and register_queued_commands; wire wrapper registration and close_queued_commands.

### `packages/ai-parrot-integrations/tests/integrations/msteams/test_queued_commands_msteams.py` (CREATE)

```python
"""Regression coverage for Add Teams queued commands, proactive delivery and shutdown."""
import pytest

async def test_teams_submit_and_proactive_delivery() -> None:
    """Verify the corresponding Test Specification behavior below."""
    # FILL IN: arrange deterministic doubles and assert the named behavior; see ACs.
    raise NotImplementedError

async def test_teams_without_client_id_does_not_submit() -> None:
    """Verify the corresponding Test Specification behavior below."""
    # FILL IN: arrange deterministic doubles and assert the named behavior; see ACs.
    raise NotImplementedError

async def test_teams_function_and_call_refuse_queued_method() -> None:
    """Verify the corresponding Test Specification behavior below."""
    # FILL IN: arrange deterministic doubles and assert the named behavior; see ACs.
    raise NotImplementedError

async def test_teams_manager_shutdown_closes_queued() -> None:
    """Verify the corresponding Test Specification behavior below."""
    # FILL IN: arrange deterministic doubles and assert the named behavior; see ACs.
    raise NotImplementedError
```

**Why**: Task-owned regression coverage. Create TeamsQueuedCommands and register_queued_commands; wire wrapper registration and close_queued_commands.

### FILL IN checklist

- [ ] packages/ai-parrot-integrations/src/parrot/integrations/msteams/commands/queued_commands.py — finish the scoped behavior/test branches above, bounded by AC1–AC5.
- [ ] packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py — finish the scoped behavior/test branches above, bounded by AC1–AC5.
- [ ] packages/ai-parrot-integrations/src/parrot/integrations/msteams/commands/agent_commands.py — finish the scoped behavior/test branches above, bounded by AC1–AC5.
- [ ] packages/ai-parrot-integrations/src/parrot/integrations/manager.py — finish the scoped behavior/test branches above, bounded by AC1–AC5.
- [ ] packages/ai-parrot-integrations/tests/integrations/msteams/test_queued_commands_msteams.py — finish the scoped behavior/test branches above, bounded by AC1–AC5.

## Acceptance Criteria

- [ ] AC1: Canonical, aliases and job controls route through MSTeamsCommandRouter; existing auth gate remains before dispatch.
- [ ] AC2: Empty client_id rejects before submission; valid handler acks via send_text then delivers parsed result through continue_conversation to the captured conversation.
- [ ] AC3: Requester actor scopes job controls; never rely on the personal-only convref store for channel/group delivery.
- [ ] AC4: handle_function and handle_call reject queued methods without invoking them.
- [ ] AC5: Shutdown invokes close_queued_commands in an isolated try/except; missing adapter is a no-op.

## Validation Commands

- `pytest packages/ai-parrot-integrations/tests/integrations/msteams/test_queued_commands_msteams.py -q`

## Test Specification

| Test | Module | Required behavior |
|---|---|---|
| `test_teams_submit_and_proactive_delivery` | M4 | handler acks via `send_text`; deliver calls `adapter.continue_conversation` with the captured reference and sends the parsed result |
| `test_teams_without_client_id_does_not_submit` | M4 | empty `client_id` → explanatory reply, no job |
| `test_teams_function_and_call_refuse_queued_method` | M4 | `/function` and `/call` on a queued method are refused |
| `test_teams_manager_shutdown_closes_queued` | M4 | `IntegrationBotManager.shutdown` awaits `close_queued_commands()` per Teams wrapper |

Use deterministic doubles for external systems; no live platform/GitHub/LLM credentials. Add all scoped AC cases, not only the scaffold examples. Store test logs under artifacts/logs/.

## Agent Instructions

1. Implement in the feature worktree provisioned by `$sdd-start TASK-5401`; never implement on dev.
2. Read this task/spec and verify all dependencies in `sdd/tasks/index/queued-commands-integrations.json`.
3. Revalidate source contracts and dependency-created anchors before edits.
4. Implement only declared files, complete all FILL IN items, and run Validation Commands.
5. Commit only scoped implementation files. Use `parrot sdd task finalize` with real TaskCompletionEvidence and implementation HEAD, inspect generated Completion Note/staged state, then commit that state. Do not manually move task files.

## Completion Note

Pending; generated by task finalization with validation and commit evidence.
