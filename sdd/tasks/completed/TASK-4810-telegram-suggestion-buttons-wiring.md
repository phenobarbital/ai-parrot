# TASK-4810: Telegram wrapper — send chip keyboard, `sg` callback replays the prompt

**Feature**: FEAT-752 — Follow-up Suggestion Chips
**Spec**: `sdd/specs/followup-suggestion-chips.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4809
**Assigned-to**: unassigned

---

## Context

Spec rev 0.3, §3 Module 9 (wiring), G7, Q3. With `config.suggestion_buttons` on, `handle_message` follows the reply
with a "💡 Follow-ups:" message carrying the chip keyboard (TASK-4809). Pressing a button routes through the
existing `_handle_callback_query` (which already answers the query first, so a long agent turn is fine) to a new
built-in `sg` handler that validates the token and replays the prompt as a new turn for the same user and chat.

---

## Scope

- `__init__`: create `self._suggestion_buttons` store and register the `sg` prefix **before** `_register_handlers()`
  (the `callback_query` route is only installed when the registry is non-empty — `wrapper.py:364`).
- `_send_suggestion_keyboard(message, session, response)`: build + send the keyboard; no-op when the flag is off or
  there is nothing renderable. Called after `_send_parsed_response` in `handle_message` (private-chat path only).
- `_on_suggestion_press(context) -> CallbackResult`: validate token / user / chat / authorization; replay.
- Tests in `packages/ai-parrot-integrations/tests/telegram/test_suggestion_buttons_wrapper.py`.

**NOT in scope**: group/channel path (`_process_group_query`, :2721); `ParsedResponse` (read
`response.suggestions` directly — no change to the shared parser); voice replies.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py` | MODIFY | Store, registration, send, press handler |
| `packages/ai-parrot-integrations/tests/telegram/test_suggestion_buttons_wrapper.py` | CREATE | Wrapper tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# wrapper.py already imports: asyncio; InlineKeyboardMarkup/InlineKeyboardButton (aiogram.types, :23-36);
#   `from .callbacks import CallbackRegistry, CallbackContext, CallbackResult` (:41, 1 occurrence);
#   `from .context import telegram_chat_scope` (:42); `from ...models.outputs import OutputMode` (:60)
from .suggestion_buttons import SUGGESTION_PREFIX, SuggestionButtonStore, build_suggestion_keyboard   # TASK-4809
```

### Existing Signatures to Use
```python
# packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py
#   `        self._callback_registry = CallbackRegistry()` :206 (1) ; discovery `        discovered = self._callback_registry.discover_from_agent(self.agent)` :210 (1)
#   `        self._register_handlers()` :230 (1) ; `        if self._callback_registry:` :364 (1) → registers _handle_callback_query
def _is_authorized(self, chat_id: int) -> bool                                           # :1053
def _get_or_create_memory(self, chat_id: int) -> "ConversationMemory"                    # :1080
def _get_user_session(self, message: Message) -> TelegramUserSession                     # :1089 — reads only `.from_user`
async def _invoke_agent(self, session, question, *, memory=..., output_mode=..., message=..., ...)  # :1454
async def handle_message(self, message: Message) -> None                                 # :2536
#   `            with telegram_chat_scope(chat_id):` → `response = await self._invoke_agent(session, user_text,
#     memory=memory, output_mode=OutputMode.TELEGRAM, message=message)` :2624-2631
#   `            # Send parsed response (handles text, images, documents, tables, code)` :2638 (1 occurrence)
#   `            sent = await self._send_parsed_response(message, parsed)` :2639 (4 occurrences — use the comment above)
async def _handle_callback_query(self, callback_query: CallbackQuery) -> None            # :4046
#   answers "⏳ Processing…" first (:4090-4094), then `result = await handler_meta.method(context)`, then
#   `_apply_callback_result(callback_query, result, already_answered=True)` (answer_text is NOT re-shown)
async def send_interactive_message(self, chat_id, text, keyboard: dict, parse_mode="Markdown") -> int | None   # :4177
#   converts a build_inline_keyboard dict to InlineKeyboardMarkup and calls self.bot.send_message(reply_markup=...)
# callbacks.py: CallbackRegistry.register(prefix, handler, description="") (:271);
#   CallbackContext(prefix, payload, chat_id, user_id, message_id, username, first_name, raw_query) (:46-66)
# Test style: packages/ai-parrot-integrations/tests/telegram/test_tenant_binding.py — pytest.importorskip("aiogram"),
#   object.__new__(TelegramAgentWrapper), stub logger/config, SimpleNamespace agent, AsyncMock.
```

### Does NOT Exist
- ~~`_send_suggestion_keyboard`~~, ~~`_on_suggestion_press`~~, ~~`self._suggestion_buttons`~~ — created here.
- ~~`ParsedResponse.suggestions`~~ — do not add; read `getattr(response, "suggestions", None)`.
- ~~a toast after `already_answered=True`~~ — `_apply_callback_result` skips the answer; send refusals as a short
  chat message via `result.reply_text` instead.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-integrations/tests/telegram/test_suggestion_buttons_wrapper.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py#TelegramAgentWrapper.handle_message",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py#TelegramAgentWrapper._handle_callback_query"
  ]
}
```

---

## Implementation Notes

- Bind every token to the asker (`user_id`, `chat_id`): a group member or a forwarded message must not replay
  someone else's chip. Also re-check `_is_authorized(chat_id)` on press.
- The replay reuses `_invoke_agent` so auth context, tenant (`self.config.tenant`) and memory match a typed message.
  `_get_user_session(callback_query)` works because it reads only `.from_user` (the clicker); never use
  `callback_query.message.from_user` (that is the bot).
- Map the stored `output_mode` with `OutputMode(value)` in a try; fall back to `OutputMode.TELEGRAM`.
- A failure while sending chips must never break the reply: wrap `_send_suggestion_keyboard` in `try/except` +
  `self.logger.warning`.

---

## Implementation Blueprint

### Steps (in order)
1. Import + store + registration in `__init__` — *why*: `sg` must exist before `_register_handlers()`.
2. `_send_suggestion_keyboard` and its call in `handle_message` — *why*: chips follow the reply.
3. `_on_suggestion_press` — *why*: replay contract (spec Module 9).
4. Tests; run Validation Commands.

### `wrapper.py` (MODIFY — import)
```python
# occurrences: 1 (verified: grep -c '^from .callbacks import CallbackRegistry, CallbackContext, CallbackResult' wrapper.py)
# AFTER — insert below that line (wrapper.py:41)
from .suggestion_buttons import SUGGESTION_PREFIX, SuggestionButtonStore, build_suggestion_keyboard
```

### `wrapper.py` (MODIFY — init)
```python
# occurrences: 1 (verified: grep -c '        discovered = self._callback_registry.discover_from_agent(self.agent)' wrapper.py)
# BEFORE — insert above that line (wrapper.py:210)
        # FEAT-752: follow-up chips as inline buttons (opt-in). Registered before _register_handlers() so the
        # callback_query route is installed even when the agent has no @telegram_callback methods.
        self._suggestion_buttons: Optional[SuggestionButtonStore] = None
        if getattr(config, "suggestion_buttons", False):
            self._suggestion_buttons = SuggestionButtonStore(ttl_s=config.suggestion_button_ttl_s)
            self._callback_registry.register(
                SUGGESTION_PREFIX, self._on_suggestion_press, "Replay a follow-up suggestion chip"
            )
```
**Why**: `config` is the constructor argument (verify the parameter name in `__init__`; if it is `self.config` only,
use that). `Optional` must already be imported from `typing` (verify).

### `wrapper.py` (MODIFY — send after reply)
```python
# occurrences: 1 (verified: grep -c '            # Send parsed response (handles text, images, documents, tables, code)' wrapper.py)
# AFTER — insert below the `            sent = await self._send_parsed_response(message, parsed)` line that follows
#         this comment (wrapper.py:2639)
            await self._send_suggestion_keyboard(message, session, response)
```

### `wrapper.py` (MODIFY — new methods, place directly above `    async def _handle_callback_query(`)
```python
    async def _send_suggestion_keyboard(self, message: Message, session: Any, response: Any) -> None:
        """FEAT-752: send the reply's non-action chips as an inline keyboard. Never raises."""
        if self._suggestion_buttons is None:
            return
        chips = getattr(response, "suggestions", None) or []
        if not chips:
            return
        try:
            # FILL IN: kb = await build_suggestion_keyboard(chips, self._suggestion_buttons, chat_id=message.chat.id,
            #          user_id=<telegram id of the asker: session.telegram_id>); if kb: await
            #          self.send_interactive_message(message.chat.id, "💡 Follow-ups:", kb)
            pass
        except Exception as exc:  # noqa: BLE001 — chips are best-effort
            self.logger.warning("Suggestion keyboard skipped: %s", exc)

    async def _on_suggestion_press(self, context: CallbackContext) -> CallbackResult:
        """FEAT-752: replay a stored chip prompt as a new turn for the user who received it."""
        # FILL IN: token = context.payload.get("raw"); record = await self._suggestion_buttons.get(token)
        #   - None -> CallbackResult(reply_text="⌛ This suggestion has expired.")
        #   - record user_id/chat_id != context.user_id/chat_id, or not self._is_authorized(context.chat_id)
        #       -> CallbackResult(reply_text="⛔ This suggestion is not for you.")
        #   - else: query = context.raw_query; msg = query.message; session = self._get_user_session(query);
        #       memory = self._get_or_create_memory(context.chat_id); mode = OutputMode(...) or TELEGRAM;
        #       with telegram_chat_scope(context.chat_id): response = await self._invoke_agent(session,
        #           record["prompt"], memory=memory, output_mode=mode, message=msg)
        #       parsed = self._parse_response(response); await self._send_parsed_response(msg, parsed);
        #       await self._send_suggestion_keyboard(msg, session, response); return CallbackResult()
        #   Bounded by Implementation Notes; mirror handle_message :2624-2639 (no reply-context/suspend logic).
        raise NotImplementedError
```

### FILL IN checklist
- [ ] `_send_suggestion_keyboard` body; `_on_suggestion_press` body.
- [ ] Test bodies below.

---

## Acceptance Criteria

- [ ] Flag off: no store, no `sg` prefix, `handle_message` output unchanged.
- [ ] Flag on: `sg` registered even when the agent has no `@telegram_callback` methods; after a reply with chips a
      keyboard message is sent; action chips never appear.
- [ ] Press by the original user in the original chat → `_invoke_agent` called with the stored prompt and mapped
      `output_mode`; reply + new keyboard sent.
- [ ] Expired/unknown token or another user/chat → refusal message, `_invoke_agent` not called.
- [ ] `test_tenant_binding.py` stays green; `ruff check` clean on touched lines.

---

## Validation Commands

- `pytest packages/ai-parrot-integrations/tests/telegram/test_suggestion_buttons_wrapper.py -q`
- `pytest packages/ai-parrot-integrations/tests/telegram/test_tenant_binding.py -q`

---

## Test Specification

```python
# packages/ai-parrot-integrations/tests/telegram/test_suggestion_buttons_wrapper.py
import pytest

pytest.importorskip("aiogram")

# FILL IN: build the wrapper with object.__new__(TelegramAgentWrapper) as in test_tenant_binding.py; set
# _suggestion_buttons = SuggestionButtonStore(), _callback_registry, logger, config, and AsyncMock for
# _invoke_agent / _send_parsed_response / send_interactive_message; _parse_response = lambda r: r.


@pytest.mark.asyncio
async def test_press_replays_prompt_for_owner():
    ...


@pytest.mark.asyncio
async def test_press_refused_for_other_user_or_expired():
    ...


@pytest.mark.asyncio
async def test_keyboard_sent_only_when_enabled_and_chips_present():
    ...


def test_sg_prefix_registered_without_agent_callbacks():
    # FILL IN: construct through __init__ with suggestion_buttons=True if feasible (patch aiogram Bot/Router), else
    #          source-level: inspect.getsource(TelegramAgentWrapper.__init__) registers SUGGESTION_PREFIX before
    #          "self._register_handlers()"
    ...
```

---

## Agent Instructions

Follow `sdd/templates/task.md` § Agent Instructions (worktree via `ensure_worktree --slug followup-suggestion-chips
--feature-id FEAT-752`, `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-integrations/src`, commit only listed
files, `scripts/sdd/close_task.sh TASK-4810 followup-suggestion-chips verified`). `wrapper.py` is > 4000 lines: read
it in ranges.

---

## Completion Note

Implemented directly by the worker (sequential fallback). Files exactly as listed (wrapper.py is read in ranges; every anchor re-verified, including that `config` is the `__init__` parameter and `Optional` is imported).
Per the blueprint: store + `sg` registration placed before `discover_from_agent` and `_register_handlers()` (so the callback_query route exists even for agents without `@telegram_callback` methods); `_send_suggestion_keyboard` called once after `_send_parsed_response` in `handle_message` (private path only) and never raises; `_on_suggestion_press` validates token, user, chat and `_is_authorized`, maps `output_mode` with a TELEGRAM fallback, replays through `_invoke_agent` under `telegram_chat_scope`, then sends the reply and a fresh keyboard. Verified that `_resolve_agent_for_request`/`_initialize_user_context`/`_send_parsed_response` only read `message.chat.id`, so passing the callback's (bot-authored) message is safe; the session comes from `query.from_user`.
Behavioural notes: a token is not consumed on press (re-pressing replays again, as the spec describes); a refusal is sent as `reply_text` because `already_answered=True` suppresses toasts; with the feature disabled a stray `sg:` press cannot occur (prefix unregistered), and the handler still degrades to 'expired' if called.
Tests: 12 new in `test_suggestion_buttons_wrapper.py` (owner replay, mode fallback, refusals for other user/chat/expired/no message/unauthorised/disabled, new keyboard after replay, keyboard gating and action-chip exclusion, send failure swallowed, registration order, registry routing, handle_message ordering). With `test_tenant_binding.py`: 27 passed incl. TASK-4809's suite. ruff and black clean.
Not exercised: a real aiogram Bot/dispatcher round trip (the wrapper is built with `object.__new__` as in test_tenant_binding.py).
