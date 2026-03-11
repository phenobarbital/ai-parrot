# TASK-300 — Matrix Crew Agent Wrapper

**Feature**: FEAT-044 (Matrix Multi-Agent Crew Integration)
**Spec**: `sdd/specs/integrations-matrix-multi.spec.md`
**Status**: pending
**Priority**: high
**Effort**: L
**Depends on**: TASK-296, TASK-297, TASK-298, TASK-299
**Parallel**: false
**Parallelism notes**: Core per-agent handler. Imports config (296), mention utils (297), registry (298), and coordinator (299).

---

## Objective

Create `MatrixCrewAgentWrapper` — the per-agent handler that processes messages directed at a specific agent. Handles typing indicators, BotManager agent resolution, response sending (with optional streaming and chunking), and coordinator status notifications.

## Files to Create/Modify

- `parrot/integrations/matrix/crew/crew_wrapper.py` — new file

## Implementation Details

### MatrixCrewAgentWrapper

```python
class MatrixCrewAgentWrapper:
    def __init__(
        self,
        agent_name: str,
        config: MatrixCrewAgentEntry,
        appservice: MatrixAppService,
        registry: MatrixCrewRegistry,
        coordinator: MatrixCoordinator,
        server_name: str,
        streaming: bool = True,
        max_message_length: int = 4096,
    ) -> None: ...
```

### handle_message(room_id, sender, body, event_id)

Main message processing flow:
1. **Update status** → `registry.update_status(agent_name, "busy", task=body[:50])`.
2. **Notify coordinator** → `coordinator.on_status_change(agent_name)`.
3. **Send typing indicator** → start background task via `asyncio.create_task(_send_typing(room_id))`.
4. **Resolve agent** → `BotManager.get_bot(config.chatbot_id)`.
5. **Get response** → `response = await agent.ask(body)`.
6. **Send response** → call `_send_response(room_id, response)` as the agent's virtual MXID using `appservice.bot_intent(mxid)`.
7. **Update status** → `registry.update_status(agent_name, "ready")`.
8. **Notify coordinator** → `coordinator.on_status_change(agent_name)`.
9. **Cancel typing task**.

Wrap in try/except: on error, update status to "ready", log the error, send an error message to the room.

### _send_response(room_id, response)

If `streaming` is enabled and the agent supports it:
- Use `MatrixStreamHandler` to stream token-by-token via message edits.

Otherwise:
- If `len(response) > max_message_length`, chunk into multiple messages.
- Send each chunk via `appservice.bot_intent(mxid).send_text(room_id, chunk)`.

### _send_typing(room_id)

Background coroutine that sends typing indicator every 10 seconds:
```python
async def _send_typing(self, room_id: str) -> None:
    intent = self._appservice.bot_intent(self._mxid)
    try:
        while True:
            await intent.set_typing(room_id, timeout=15000)
            await asyncio.sleep(10)
    except asyncio.CancelledError:
        await intent.set_typing(room_id, typing=False)
```

### _chunk_text(text, max_length) -> list[str]

Static method to split long text into chunks at paragraph or sentence boundaries, respecting `max_message_length`.

Reference: `parrot/integrations/telegram/crew/crew_wrapper.py` for the pattern.

## Acceptance Criteria

- [ ] Messages directed at an agent are processed via `handle_message()`.
- [ ] Agent is resolved via `BotManager.get_bot(chatbot_id)`.
- [ ] Typing indicator is sent while processing, cancelled after response.
- [ ] Response is sent as the agent's virtual MXID (via AppService intent).
- [ ] Long responses are chunked into multiple messages.
- [ ] Registry status updates occur (busy → ready) with coordinator notification.
- [ ] Errors are caught, logged, and status is reset to "ready".
