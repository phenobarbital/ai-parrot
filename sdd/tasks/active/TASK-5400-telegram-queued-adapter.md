# TASK-5400: Register Telegram queued commands and close services before sessions

**Feature**: FEAT-851 - Queued chat commands for the integrations
**Spec**: `sdd/specs/queued-commands-integrations.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5398, TASK-5399
**Assigned-to**: unassigned

## Context

Implements the scoped FEAT-851 deliverable below. Read spec §§2–7 for the fixed behavior and edge cases. This task creates implementation artifacts only when picked up by sdd-start.

## Scope

- Implement TelegramQueuedCommands following TelegramKnowledgeUpload; discover/register canonical commands, routing aliases and job controls.
- Skip queued methods in legacy discovery; guard handle_function and _execute_agent_method.
- Shut down queued jobs from wrapper.close and invoke close before session closure in both managers.

**NOT in scope**: files outside the table, new dependencies, external workers, cross-worker cancel/dedup, or changes to strict review semantics beyond the declared registration update.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/queued_commands.py` | CREATE | Telegram adapter and captured delivery closures |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py` | MODIFY | Registration, lifecycle and generic-call guards |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/decorators.py` | MODIFY | Avoid duplicate inline registration |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/manager.py` | MODIFY | Close wrapper before session, isolating both failures |
| `packages/ai-parrot-integrations/src/parrot/integrations/manager.py` | MODIFY | Close wrapper before session, isolating both failures |
| `packages/ai-parrot-integrations/tests/integrations/telegram/test_queued_commands_telegram.py` | MODIFY | Task-owned regression coverage |

## Codebase Contract (Anti-Hallucination)

Verified against the current dev source on 2026-11-09. Existing signatures below were re-read with AST and source inspection; MODIFY anchors were re-counted with `grep -cF`. Symbols provided by dependencies are explicitly future contracts, not existing imports.

### Verified Imports

```python
from typing import List, Tuple
from aiogram import Router
from aiogram.filters import Command
from parrot.integrations.telegram.context import telegram_chat_scope
from parrot.integrations.parser import parse_response
from parrot.integrations.core.queued import QueuedCommand, Requester, JobNotice, QueuedCommandService, discover_queued_commands, queued_spec_of
from parrot.integrations.core.queued.messages import JOB_COMMANDS, format_ack, format_notice_header, format_job_view, format_job_list, format_cancel
import pytest
from .queued_commands import TelegramQueuedCommands
from parrot.integrations.core.queued import QueuedCommand, Requester, JobNotice, QueuedCommandService
```

Standard-library imports are available; pydantic/pytest and platform SDK imports reuse the declared project stack. New imports are supplied only by this task or its named prerequisites; revalidate them when prerequisites land. Existing source relocation preserves its original import block.

### Existing Signatures to Use

```python
# packages/ai-parrot-integrations/src/parrot/integrations/telegram/knowledge_upload.py:68
class TelegramKnowledgeUpload()

# packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py:282
def _register_handlers(self) -> None

# packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py:426
def _add_platform_commands(self, entries: list[tuple[str, str]]) -> None

# packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py:1206
def _is_authorized(self, chat_id: int) -> bool

# packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py:2379
async def handle_function(self, message: Message) -> None

# packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py:2747
async def _execute_agent_method(self, message: Message, method_name: str, args_text: str) -> None

# packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py:3615
async def close(self) -> None

# packages/ai-parrot-integrations/src/parrot/integrations/telegram/decorators.py:35
def discover_telegram_commands(agent: Any) -> List[Dict[str, Any]]

# packages/ai-parrot-integrations/src/parrot/integrations/telegram/context.py:20
def telegram_chat_scope(chat_id: int | str | None) -> Iterator[None]

# packages/ai-parrot-integrations/src/parrot/integrations/telegram/manager.py:336
async def shutdown(self) -> None

# packages/ai-parrot-integrations/src/parrot/integrations/manager.py:1150
async def shutdown(self) -> None
```

### Does NOT Exist

- TelegramQueuedCommands is new; service is supplied by TASK-5398, delivery by TASK-5399.
- Managers currently close only bot.session, not the wrapper.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-integrations/src/parrot/integrations/telegram/queued_commands.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-integrations/src/parrot/integrations/telegram/decorators.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-integrations/src/parrot/integrations/telegram/manager.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-integrations/src/parrot/integrations/manager.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-integrations/tests/integrations/telegram/test_queued_commands_telegram.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/telegram/knowledge_upload.py#TelegramKnowledgeUpload",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py#TelegramAgentWrapper._register_handlers",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py#TelegramAgentWrapper._add_platform_commands",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py#TelegramAgentWrapper._is_authorized",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py#TelegramAgentWrapper.handle_function",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py#TelegramAgentWrapper._execute_agent_method",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py#TelegramAgentWrapper.close",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/telegram/decorators.py#discover_telegram_commands",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/telegram/context.py#telegram_chat_scope",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/telegram/manager.py#TelegramBotManager.shutdown",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/manager.py#IntegrationBotManager.shutdown"
  ]
}
```

## Implementation Notes

- Also implement spec tests for acknowledgement/topic delivery, discovery exclusion and both generic invocation guards. Capture the reply destination before returning from the handler.

**Parallelism**: TASK-5398 supplies QueuedCommandService and progress APIs; TASK-5399 supplies send_parsed_to_chat and serializes overlapping telegram/wrapper.py and test_queued_commands_telegram.py edits.

## Implementation Blueprint

Planning skeletons only: complete all bounded FILL IN items; never leave placeholders in implementation files. Preserve the spec interface signatures.

### Steps (in order)

1. Verify prerequisites and the exact anchors below — dependent files may have moved since planning.
2. Apply only the declared per-file changes — this bounds ownership and preserves unrelated behavior.
3. Complete the acceptance-criteria branches and regression tests — these pin failure, ownership and compatibility boundaries.
4. Run the task validation and format/lint touched Python files — publish complete working files only.

### `packages/ai-parrot-integrations/src/parrot/integrations/telegram/queued_commands.py` (CREATE)

```python
"""Telegram routing for queued commands and requester job controls."""
from typing import List, Tuple
from aiogram import Router
from aiogram.filters import Command
from parrot.integrations.core.queued import QueuedCommand, Requester, JobNotice, QueuedCommandService
from parrot.integrations.core.queued.messages import (
    JOB_COMMANDS, format_ack, format_notice_header, format_job_view, format_job_list, format_cancel,
)
from parrot.integrations.parser import parse_response
from parrot.integrations.telegram.context import telegram_chat_scope

class TelegramQueuedCommands:
    """Own one Telegram wrapper's queued-command service and handlers."""
    def __init__(self, wrapper: "TelegramAgentWrapper", commands: List[QueuedCommand]) -> None:
        """Capture the wrapper and create a service owned by telegram:<bot name>."""
        # FILL IN: bind wrapper/commands/service without network I/O; AC2.
    def register(self, router: Router) -> List[Tuple[str, str]]:
        """Register canonical/alias routes and requester-scoped job controls."""
        # FILL IN: AC1-AC3. Each closure must bind its own command, not the final loop value.
        # Convert IDs to str for Requester; keep forum topic only for is_topic_message.
        # Completed notice -> parse_response(result) -> send_parsed_to_chat(header prefix).
        raise NotImplementedError
    async def shutdown(self) -> None:
        """Stop jobs while the Telegram session remains available for notices."""
        await self.service.stop()
```

**Why**: Telegram adapter and captured delivery closures. Implement TelegramQueuedCommands following TelegramKnowledgeUpload; discover/register canonical commands, routing aliases and job controls.

### `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py` (MODIFY)

- Anchor `self._register_agent_commands()`; occurrences: **1** (`grep -cF`); packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py:337.
- Anchor `async def close(self) -> None:`; occurrences: **1** (`grep -cF`); packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py:3615.
- Anchor `method = getattr(self.agent, method_name)`; occurrences: **2** (`grep -cF`); packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py:2410,2756.
  Context in TelegramAgentWrapper.handle_function at line 2410:
```python
            return

        method = getattr(self.agent, method_name)
        if not callable(method):
            await message.answer(f"❌ `{method_name}` is not callable.")
```
  Context in TelegramAgentWrapper._execute_agent_method at line 2756:
```python
            return

        method = getattr(self.agent, method_name)
        if not callable(method):
            await message.answer(f"❌ '{method_name}' is not callable.")
```

```python
# AFTER self._register_agent_commands(), outside knowledge-upload conditionals:
commands = discover_queued_commands(self.agent)
self._queued_commands = TelegramQueuedCommands(self, commands) if commands else None
if self._queued_commands:
    self._add_platform_commands(self._queued_commands.register(self.router))
# FILL IN: close() awaits holder.shutdown while bot session is open; preserve other cleanup.
# At BOTH getattr sites (handle_function and _execute_agent_method):
spec = queued_spec_of(method)
if spec is not None:
    await message.answer(f"Use /{spec.command} — it runs in the background.")
    return
```

**Why**: Registration, lifecycle and generic-call guards. Implement TelegramQueuedCommands following TelegramKnowledgeUpload; discover/register canonical commands, routing aliases and job controls.

### `packages/ai-parrot-integrations/src/parrot/integrations/telegram/decorators.py` (MODIFY)

- Anchor `meta = getattr(attr, "_telegram_command", None)`; occurrences: **1** (`grep -cF`); packages/ai-parrot-integrations/src/parrot/integrations/telegram/decorators.py:54.

```python
# BEFORE reading _telegram_command metadata in discover_telegram_commands:
if getattr(attr, "_queued_command", None) is not None:
    continue
```

**Why**: Avoid duplicate inline registration. Implement TelegramQueuedCommands following TelegramKnowledgeUpload; discover/register canonical commands, routing aliases and job controls.

### `packages/ai-parrot-integrations/src/parrot/integrations/telegram/manager.py` (MODIFY)

- Anchor `for name, (bot, _dp, _wrapper) in self.bots.items():`; occurrences: **1** (`grep -cF`); packages/ai-parrot-integrations/src/parrot/integrations/telegram/manager.py:372.

```python
# REPLACE the loop header to retain wrapper, then insert before existing session try:
for name, (bot, _dp, wrapper) in self.bots.items():
    try:
        await wrapper.close()
    except Exception as exc:
        self.logger.error("Error closing Telegram wrapper '%s': %s", name, exc)
    # Preserve the existing independent bot.session.close() try/except here.
```

**Why**: Close wrapper before session, isolating both failures. Implement TelegramQueuedCommands following TelegramKnowledgeUpload; discover/register canonical commands, routing aliases and job controls.

### `packages/ai-parrot-integrations/src/parrot/integrations/manager.py` (MODIFY)

- Anchor `for name, (bot, _dp, _) in self.telegram_bots.items():`; occurrences: **1** (`grep -cF`); packages/ai-parrot-integrations/src/parrot/integrations/manager.py:1170.

```python
# REPLACE the loop header to retain wrapper, then insert before existing session try:
for name, (bot, _dp, wrapper) in self.telegram_bots.items():
    try:
        await wrapper.close()
    except Exception as exc:
        self.logger.error("Error closing Telegram wrapper '%s': %s", name, exc)
    # Preserve the existing independent bot.session.close() try/except here.
```

**Why**: Close wrapper before session, isolating both failures. Implement TelegramQueuedCommands following TelegramKnowledgeUpload; discover/register canonical commands, routing aliases and job controls.

### `packages/ai-parrot-integrations/tests/integrations/telegram/test_queued_commands_telegram.py` (MODIFY)

Created by TASK-5399; planned anchor `async def test_telegram_queued_attachments_keep_topic_and_reply() -> None:` occurs 1 time(s) in its blueprint. File does not exist on dev yet: verify actual count/line after the dependency lands before editing; this is dependency evidence, not a claimed current-source grep.

```python
# Preserve existing fixtures and tests; append the cases below.
"""Regression coverage for Register Telegram queued commands and close services before sessions."""
import pytest

async def test_telegram_registers_queued_and_job_commands() -> None:
    """Verify the corresponding Test Specification behavior below."""
    # FILL IN: arrange deterministic doubles and assert the named behavior; see ACs.
    raise NotImplementedError

async def test_managers_call_wrapper_close_before_session_close() -> None:
    """Verify the corresponding Test Specification behavior below."""
    # FILL IN: arrange deterministic doubles and assert the named behavior; see ACs.
    raise NotImplementedError

async def test_queued_command_end_to_end_memory_store() -> None:
    """Verify the corresponding Test Specification behavior below."""
    # FILL IN: arrange deterministic doubles and assert the named behavior; see ACs.
    raise NotImplementedError
```

**Why**: Task-owned regression coverage. Implement TelegramQueuedCommands following TelegramKnowledgeUpload; discover/register canonical commands, routing aliases and job controls.

### FILL IN checklist

- [ ] packages/ai-parrot-integrations/src/parrot/integrations/telegram/queued_commands.py — finish the scoped behavior/test branches above, bounded by AC1–AC6.
- [ ] packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py — finish the scoped behavior/test branches above, bounded by AC1–AC6.
- [ ] packages/ai-parrot-integrations/src/parrot/integrations/telegram/decorators.py — finish the scoped behavior/test branches above, bounded by AC1–AC6.
- [ ] packages/ai-parrot-integrations/src/parrot/integrations/telegram/manager.py — finish the scoped behavior/test branches above, bounded by AC1–AC6.
- [ ] packages/ai-parrot-integrations/src/parrot/integrations/manager.py — finish the scoped behavior/test branches above, bounded by AC1–AC6.
- [ ] packages/ai-parrot-integrations/tests/integrations/telegram/test_queued_commands_telegram.py — finish the scoped behavior/test branches above, bounded by AC1–AC6.

## Acceptance Criteria

- [ ] AC1: Canonical names and job controls appear in menus; aliases are routed but excluded from menu entries.
- [ ] AC2: Apply existing authorization/authentication gates, capture requester strings and submit under telegram_chat_scope(chat_id).
- [ ] AC3: Handler acknowledges before completion; delivery parses output and uses send_parsed_to_chat with captured topic and reply ID.
- [ ] AC4: Both generic invocation paths refuse queued methods with Use /<command> — it runs in the background.
- [ ] AC5: Managers call wrapper.close before bot.session.close; each close failure is isolated/logged and does not skip session closure.
- [ ] AC6: Memory-store integration test covers command → ack → result → jobs → completed status, with no conversation-history write.

## Validation Commands

- `pytest packages/ai-parrot-integrations/tests/integrations/telegram/test_queued_commands_telegram.py -q`

## Test Specification

| Test | Module | Required behavior |
|---|---|---|
| `test_telegram_registers_queued_and_job_commands` | M3 | menu entries include `pr_review`, `jobs`, `job_status`, `job_cancel`; alias `pr-review` routed but not in the menu |
| `test_telegram_ack_then_reply_in_topic` | M3 | handler answers the ack; deliver calls `send_message` with `message_thread_id` and `reply_parameters` of the command message |
| `test_telegram_discovery_skips_queued_methods` | M3 | `discover_telegram_commands` does not return a `@queued_command` method |
| `test_telegram_function_refuses_queued_method` | M3 | `/function pr_review` and `/call review_pr` answer "runs in the background" without calling the method |
| `test_managers_call_wrapper_close_before_session_close` | M3 | `IntegrationBotManager.shutdown` and `TelegramBotManager.shutdown` await `wrapper.close()` before `bot.session.close()`; a raising `close()` is logged, not propagated |
| `test_queued_command_end_to_end_memory_store` | M2 + M3: a stub agent with one `@queued_command` behind a `TelegramAgentWrapper` with a mocked `Bot`: `/cmd` → ack → result reply → `/jobs` lists it → `/job_status` shows `completed` |

Use deterministic doubles for external systems; no live platform/GitHub/LLM credentials. Add all scoped AC cases, not only the scaffold examples. Store test logs under artifacts/logs/.

## Agent Instructions

1. Implement in the feature worktree provisioned by `$sdd-start TASK-5400`; never implement on dev.
2. Read this task/spec and verify all dependencies in `sdd/tasks/index/queued-commands-integrations.json`.
3. Revalidate source contracts and dependency-created anchors before edits.
4. Implement only declared files, complete all FILL IN items, and run Validation Commands.
5. Commit only scoped implementation files. Use `parrot sdd task finalize` with real TaskCompletionEvidence and implementation HEAD, inspect generated Completion Note/staged state, then commit that state. Do not manually move task files.

## Completion Note

Pending; generated by task finalization with validation and commit evidence.
