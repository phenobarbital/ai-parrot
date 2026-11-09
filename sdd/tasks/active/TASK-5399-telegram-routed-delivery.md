# TASK-5399: Preserve Telegram topic and reply routing for every result type

**Feature**: FEAT-851 - Queued chat commands for the integrations
**Spec**: `sdd/specs/queued-commands-integrations.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

## Context

Implements the scoped FEAT-851 deliverable below. Read spec §§2–7 for the fixed behavior and edge cases. This task creates implementation artifacts only when picked up by sdd-start.

## Scope

- Add send_parsed_to_chat and extend _send_attachments/_send_url_photos with optional keyword-only topic/reply parameters.
- Keep destination information across text chunking, Markdown fallback, remote-image download and all media sends.

**NOT in scope**: files outside the table, new dependencies, external workers, cross-worker cancel/dedup, or changes to strict review semantics beyond the declared registration update.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py` | MODIFY | Routed send API and backward-compatible attachment parameters |
| `packages/ai-parrot-integrations/tests/integrations/telegram/test_queued_commands_telegram.py` | CREATE | Task-owned regression coverage |

## Codebase Contract (Anti-Hallucination)

Verified against the current dev source on 2026-11-09. Existing signatures below were re-read with AST and source inspection; MODIFY anchors were re-counted with `grep -cF`. Symbols provided by dependencies are explicitly future contracts, not existing imports.

### Verified Imports

```python
from typing import List, Optional
from aiogram.types import ReplyParameters
from parrot.integrations.parser import ParsedResponse
import pytest
from parrot.integrations.telegram.wrapper import TelegramAgentWrapper
```

Standard-library imports are available; pydantic/pytest and platform SDK imports reuse the declared project stack. New imports are supplied only by this task or its named prerequisites; revalidate them when prerequisites land. Existing source relocation preserves its original import block.

### Existing Signatures to Use

```python
# packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py:3304
async def _send_attachments(self, chat_id: int, parsed: ParsedResponse) -> None

# packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py:3284
async def _send_url_photos(self, chat_id: int, urls: List[str]) -> None

# packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py:4164
async def _send_long_message(self, message: Message, text: str, max_length: int=4096, parse_mode: str='Markdown') -> Optional[Message]

# packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py:4531
async def send_interactive_message(self, chat_id: int, text: str, keyboard: dict, parse_mode: str='Markdown') -> int | None

# packages/ai-parrot-integrations/src/parrot/integrations/parser.py:86
class ParsedResponse()
```

### Does NOT Exist

- send_parsed_to_chat and topic parameters on attachment helpers do not exist yet.
- ChartReply is not an integrations model; parse_response produces ParsedResponse.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-integrations/tests/integrations/telegram/test_queued_commands_telegram.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py#TelegramAgentWrapper._send_attachments",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py#TelegramAgentWrapper._send_url_photos",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py#TelegramAgentWrapper._send_long_message",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py#TelegramAgentWrapper.send_interactive_message",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/parser.py#ParsedResponse"
  ]
}
```

## Implementation Notes

- Parameterize media types and fallback sends; include deleted original message, chunking and callers that omit routing arguments. This task does not register queued commands.

**Parallelism**: Independent: owns packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py, packages/ai-parrot-integrations/tests/integrations/telegram/test_queued_commands_telegram.py; consumes only existing APIs and changes no shared external state.

## Implementation Blueprint

Planning skeletons only: complete all bounded FILL IN items; never leave placeholders in implementation files. Preserve the spec interface signatures.

### Steps (in order)

1. Verify prerequisites and the exact anchors below — dependent files may have moved since planning.
2. Apply only the declared per-file changes — this bounds ownership and preserves unrelated behavior.
3. Complete the acceptance-criteria branches and regression tests — these pin failure, ownership and compatibility boundaries.
4. Run the task validation and format/lint touched Python files — publish complete working files only.

### `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py` (MODIFY)

- Anchor `async def send_interactive_message(`; occurrences: **1** (`grep -cF`); packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py:4531.
- Anchor `async def _send_attachments(self, chat_id: int, parsed: ParsedResponse) -> None:`; occurrences: **1** (`grep -cF`); packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py:3304.
- Anchor `async def _send_url_photos(self, chat_id: int, urls: List[str]) -> None:`; occurrences: **1** (`grep -cF`); packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py:3284.

```python
# Add ReplyParameters to the existing aiogram.types imports.
async def send_parsed_to_chat(self, chat_id: int, parsed: ParsedResponse, *,
                              message_thread_id: Optional[int] = None,
                              reply_to_message_id: Optional[int] = None,
                              prefix: str = "") -> None:
    """Deliver text and all attachments to a captured chat/topic/reply target."""
    # FILL IN: AC1-AC4; reuse _send_long_message's fallback semantics without a Message.
    raise NotImplementedError

async def _send_attachments(self, chat_id: int, parsed: ParsedResponse, *,
                            message_thread_id: Optional[int] = None,
                            reply_to_message_id: Optional[int] = None) -> None:
    """Send every attachment while retaining the optional topic and reply target."""
    # FILL IN: retain existing body; forward routing at every bot.send_* call and remote helper.
    raise NotImplementedError

async def _send_url_photos(self, chat_id: int, urls: List[str], *,
                           message_thread_id: Optional[int] = None,
                           reply_to_message_id: Optional[int] = None) -> None:
    """Download allowed remote images and send with the captured destination."""
    # FILL IN: preserve bounded temp_download + allowed_media_hosts and forward routing.
    raise NotImplementedError
```

**Why**: Routed send API and backward-compatible attachment parameters. Add send_parsed_to_chat and extend _send_attachments/_send_url_photos with optional keyword-only topic/reply parameters.

### `packages/ai-parrot-integrations/tests/integrations/telegram/test_queued_commands_telegram.py` (CREATE)

```python
"""Regression coverage for Preserve Telegram topic and reply routing for every result type."""
import pytest
from parrot.integrations.telegram.wrapper import TelegramAgentWrapper

async def test_telegram_queued_attachments_keep_topic_and_reply() -> None:
    """Verify the corresponding Test Specification behavior below."""
    # FILL IN: arrange deterministic doubles and assert the named behavior; see ACs.
    raise NotImplementedError
```

**Why**: Task-owned regression coverage. Add send_parsed_to_chat and extend _send_attachments/_send_url_photos with optional keyword-only topic/reply parameters.

### FILL IN checklist

- [ ] packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py — finish the scoped behavior/test branches above, bounded by AC1–AC4.
- [ ] packages/ai-parrot-integrations/tests/integrations/telegram/test_queued_commands_telegram.py — finish the scoped behavior/test branches above, bounded by AC1–AC4.

## Acceptance Criteria

- [ ] AC1: send_parsed_to_chat signature matches M3 and sends text in <=4096 character chunks with existing Markdown-to-plain fallback.
- [ ] AC2: Every text/chart/local image/remote image/document/video/audio/fallback send uses the same topic and ReplyParameters.
- [ ] AC3: ReplyParameters sets allow_sending_without_reply=True so deleting the command does not lose the topic.
- [ ] AC4: Existing callers with no routing kwargs remain compatible; preserve URL download allowlists and resource cleanup.

## Validation Commands

- `pytest packages/ai-parrot-integrations/tests/integrations/telegram/test_queued_commands_telegram.py -q`

## Test Specification

| Test | Module | Required behavior |
|---|---|---|
| `test_telegram_queued_attachments_keep_topic_and_reply` | M3 | Chart, local/remote image, document, video, audio and fallback sends all carry forum topic and reply parameters; deleted original message and text fallback retain topic; existing callers without routing kwargs still work |

Use deterministic doubles for external systems; no live platform/GitHub/LLM credentials. Add all scoped AC cases, not only the scaffold examples. Store test logs under artifacts/logs/.

## Agent Instructions

1. Implement in the feature worktree provisioned by `$sdd-start TASK-5399`; never implement on dev.
2. Read this task/spec and verify all dependencies in `sdd/tasks/index/queued-commands-integrations.json`.
3. Revalidate source contracts and dependency-created anchors before edits.
4. Implement only declared files, complete all FILL IN items, and run Validation Commands.
5. Commit only scoped implementation files. Use `parrot sdd task finalize` with real TaskCompletionEvidence and implementation HEAD, inspect generated Completion Note/staged state, then commit that state. Do not manually move task files.

## Completion Note

Pending; generated by task finalization with validation and commit evidence.
