# TASK-4807: `AgentTalk` stream suggestions trailer (`suggestions_trailer: true`)

**Feature**: FEAT-752 — Follow-up Suggestion Chips
**Spec**: `sdd/specs/followup-suggestion-chips.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4802, TASK-4806
**Assigned-to**: unassigned

---

## Context

Spec rev 0.3, §3 Module 8 (handler half), G8, Q1. When the stream request body carries `suggestions_trailer: true`,
`_handle_stream_response` writes the final envelope without chips, then awaits the deferred chip task (TASK-4806)
and writes a second `\n\x00` frame `{"suggestions": [...], "turn_id": "..."}` before EOF. Without the flag the wire
is byte-identical to TASK-4802's v1 (old clients `JSON.parse` everything after the first NUL, so the trailer must
be opt-in).

---

## Scope

- `AgentTalk.post`: pop `suggestions_trailer` next to `avatar_bifurcate`; pass it to `_handle_stream_response`.
- `_handle_stream_response`: new param; header variant; `defer_suggestions=True` to `bot.ask_stream`; no
  `suggestions` in the envelope on this path; trailer after the envelope; cancel the task on cancel/error.
- Tests in `tests/handlers/test_suggestions_trailer.py`.

**NOT in scope**: JSON (non-stream) bodies; ChatStorage persistence of chips (Non-Goal); the UI (TASK-4808).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/agent.py` | MODIFY | Flag + trailer |
| `packages/ai-parrot-server/tests/handlers/test_suggestions_trailer.py` | CREATE | Trailer tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# agent.py already imports: asyncio (:17); Dict, Any, List, Optional (:11); AIMessage; json_encoder.
from parrot.handlers.agent import AgentTalk, _suggestions_payload   # _suggestions_payload: TASK-4802
from parrot.models import AIMessage, Suggestion                      # Suggestion: TASK-4794
from parrot.models.basic import CompletionUsage                      # verified: models/basic.py:48
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/handlers/agent.py
#   post():  avatar_bifurcate: bool = bool(data.pop("avatar_bifurcate", False))          # :1694 (1 occurrence)
#   post():  return await self._handle_stream_response(..., avatar_bifurcate=avatar_bifurcate, tenant=tenant, **data)
#            `                        avatar_bifurcate=avatar_bifurcate,`                    # :1865 (1 occurrence)
async def _handle_stream_response(self, bot, query, session_id, user_id, search_type, return_sources,
    use_vector_context, use_conversation_history, output_mode, format_kwargs, memory, llm, agent_name="",
    client_message_id=None, avatar_bifurcate: bool = False, tenant=None, **kwargs)        # :2607-2625
#   `        avatar_bifurcate: bool = False,`                                               # :2623 (1 occurrence)
#   `                "X-Parrot-Stream": "chunked-aimessage",`                               # :2650 (1 occurrence)
#   async for chunk in bot.ask_stream(question=query, ..., tenant=tenant, **kwargs):       # :2663-2676
#     `                tenant=tenant,` occurs 3x in the file — the one at :2674 is followed by `                **kwargs,`
#     and `            ):` and then `                if isinstance(chunk, AIMessage):`
#   envelope dict :2684-2726 (incl. "turn_id" in metadata :2695); TASK-4802 adds `envelope["suggestions"]` after the
#   a2ui block; `separator = b"\n\x00"` :2730; envelope write :2731 (1 occurrence) + drain :2732
#   ChatStorage background save :2735-; avatar detach ...; `        except asyncio.CancelledError:` :2810 (1);
#   generic except writes `\n\x00{error}` :2812-2815; finally → `await stream_resp.write_eof()` :2819 (1)
# Harness to copy: tests/handlers/test_agent_a2ui_stream.py, tests/handlers/test_suggestions_passthrough.py (TASK-4802)
```

### Does NOT Exist
- ~~`suggestions_trailer`~~ handling / ~~`chunked-aimessage+suggestions`~~ header — created here.
- ~~a second item yielded by `ask_stream`~~ — chips come from `ai_message._suggestions_task` (TASK-4806).
- ~~`bot.suggestion_timeout_s` on every bot~~ — only bots built after TASK-4800; read it with
  `getattr(bot, "suggestion_timeout_s", 4.0)`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-server/src/parrot/handlers/agent.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/tests/handlers/test_suggestions_trailer.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/handlers/agent.py#AgentTalk._handle_stream_response",
    "sym:packages/ai-parrot-server/src/parrot/handlers/agent.py#AgentTalk.post"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Pop the flag in `post` and forward it — *why*: otherwise it leaks via `**data` into `bot.ask_stream(**kwargs)`.
2. Signature param + header variant — *why*: clients/proxies can see which framing they get.
3. `defer_suggestions=suggestions_trailer` on the `ask_stream` call — *why*: TASK-4806's opt-in.
4. Envelope: drop `suggestions` when trailing — *why*: deterministic wire regardless of task timing.
5. Trailer after the envelope drain; cancel on cancel/error — *why*: never leak a running LLM call.
6. Tests; run Validation Commands.

### `post` (MODIFY — pop)
```python
# occurrences: 1 (verified: grep -c '        avatar_bifurcate: bool = bool(data.pop("avatar_bifurcate", False))' agent.py)
# AFTER — insert below that line (agent.py:1694)
        # FEAT-752 rev 0.3: opt-in trailing chips frame on the stream path; popped so it never reaches the bot.
        suggestions_trailer: bool = bool(data.pop("suggestions_trailer", False))
```

### `post` (MODIFY — forward)
```python
# occurrences: 1 (verified: grep -c '                        avatar_bifurcate=avatar_bifurcate,' agent.py)
# AFTER — insert below that line (agent.py:1865)
                        suggestions_trailer=suggestions_trailer,
```

### `_handle_stream_response` (MODIFY — signature + header)
```python
# occurrences: 1 (verified: grep -c '        avatar_bifurcate: bool = False,' agent.py)
# AFTER — insert below that line (agent.py:2623)
        suggestions_trailer: bool = False,

# occurrences: 1 (verified: grep -c '                "X-Parrot-Stream": "chunked-aimessage",' agent.py)
# REPLACE that line (agent.py:2650) with:
                "X-Parrot-Stream": ("chunked-aimessage+suggestions" if suggestions_trailer else "chunked-aimessage"),
```

### `_handle_stream_response` (MODIFY — ask_stream kwarg)
```python
# occurrences: 3 for `                tenant=tenant,` — disambiguate: the one inside `async for chunk in bot.ask_stream(`
#   (agent.py:2674), followed by `                **kwargs,` / `            ):` / `                if isinstance(chunk, AIMessage):`
# AFTER — insert below that `tenant=tenant,` line
                defer_suggestions=suggestions_trailer,
```

### `_handle_stream_response` (MODIFY — envelope + trailer)
```python
# FILL IN (envelope): where TASK-4802 added `envelope["suggestions"] = _suggestions`, guard it with
#   `if _suggestions is not None and not suggestions_trailer:` — bounded by AC "envelope carries no suggestions".

# occurrences: 1 (verified: grep -c '                await stream_resp.write(separator + json_encoder(envelope).encode("utf-8"))' agent.py)
# AFTER — insert below that line and the `                await stream_resp.drain()` that follows it (agent.py:2731-2732)
                if suggestions_trailer:
                    await self._write_suggestions_trailer(stream_resp, bot, ai_message)
```

### New method on `AgentTalk` (MODIFY — place directly above `    async def _handle_stream_response(`)
```python
    async def _write_suggestions_trailer(self, stream_resp: web.StreamResponse, bot: Any, ai_message: AIMessage) -> None:
        """FEAT-752 rev 0.3: await the deferred chip task and write ``\\n\\x00{"suggestions", "turn_id"}``.

        Writes nothing when there is no task, it times out/fails, or the list is empty. Never raises.
        """
        task = getattr(ai_message, "_suggestions_task", None)
        if task is None:
            return
        timeout = float(getattr(bot, "suggestion_timeout_s", 4.0)) + 1.0
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=timeout)
        except Exception as exc:  # noqa: BLE001 — chips are best-effort
            task.cancel()
            self.logger.warning("Suggestions trailer skipped: %s", exc)
            return
        # FILL IN: payload = _suggestions_payload(ai_message); if None -> return; else write
        #   b"\n\x00" + json_encoder({"suggestions": payload, "turn_id": str(getattr(ai_message, "turn_id", "") or "")})
        #   .encode("utf-8") and drain — bounded by AC "non-empty only" and the frame format in spec Module 8.
```
```python
# FILL IN (cancellation): in the existing `except asyncio.CancelledError:` (agent.py:2810) and generic `except`
#   (:2811) branches, cancel `getattr(ai_message, "_suggestions_task", None)` when it is not done — bounded by
#   "never leak a running LLM call". `ai_message` is already defined before the try (:2656).
```

### FILL IN checklist
- [ ] Envelope guard; trailer payload write; cancellation in both except branches.
- [ ] Test bodies below.

---

## Acceptance Criteria

- [ ] Flag off: response bytes identical to TASK-4802 (envelope may contain `suggestions`; no second frame; header
      `chunked-aimessage`).
- [ ] Flag on: header `chunked-aimessage+suggestions`; envelope has no `suggestions`; a non-empty chip list is written
      as one trailing `\n\x00{"suggestions": [...], "turn_id": ...}` frame before EOF; empty list → no frame.
- [ ] Task timeout or exception → no trailer, stream still closes; client cancel cancels the task.
- [ ] `suggestions_trailer` never appears in the kwargs `bot.ask_stream` receives (only `defer_suggestions`).
- [ ] TASK-4802's tests stay green; `ruff check` clean on touched lines.

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/handlers/test_suggestions_trailer.py -q`
- `pytest packages/ai-parrot-server/tests/handlers/test_agent_a2ui_stream.py -q`

---

## Test Specification

```python
# packages/ai-parrot-server/tests/handlers/test_suggestions_trailer.py
# FILL IN: copy the fake-bot / fake StreamResponse harness of test_agent_a2ui_stream.py. The fake bot's ask_stream
# records its kwargs, yields "hello", then an AIMessage whose _suggestions_task is an asyncio task that sets
# `suggestions=[Suggestion(label="A", prompt="a")]`.

async def test_trailer_off_is_v1_wire():
    # FILL IN: no flag -> single NUL frame; header "chunked-aimessage"; "defer_suggestions" kwarg False
    ...


async def test_trailer_on_writes_second_frame():
    # FILL IN: flag on -> split body on b"\n\x00": [text, envelope_json, trailer_json]; envelope lacks "suggestions";
    #          trailer == {"suggestions": [...], "turn_id": ...}; header "chunked-aimessage+suggestions"
    ...


async def test_trailer_skipped_on_empty_or_timeout():
    # FILL IN: empty list -> two parts only; task that sleeps past timeout (monkeypatch bot.suggestion_timeout_s=0)
    #          -> two parts only and task cancelled
    ...


async def test_flag_not_forwarded_to_bot():
    # FILL IN: post() path or direct call — recorded ask_stream kwargs contain no "suggestions_trailer"
    ...
```

---

## Agent Instructions

Follow `sdd/templates/task.md` § Agent Instructions (worktree via `ensure_worktree --slug followup-suggestion-chips
--feature-id FEAT-752`, `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src`, commit only listed files,
`scripts/sdd/close_task.sh TASK-4807 followup-suggestion-chips verified`).

---

## Completion Note

*(Agent fills this in when done)*
