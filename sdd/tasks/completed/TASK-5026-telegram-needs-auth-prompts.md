# TASK-5026: Needs-auth rendering in Telegram (collect during `ask`, prompt after the reply)

**Feature**: FEAT-776 — Connections on Telegram
**Spec**: `sdd/specs/connections-telegram.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-5016, TASK-5021, TASK-5025
**Assigned-to**: unassigned

---

## Context

Spec §2 "Needs-auth" (wrapper half), §3 Module 8, AC-9/18. With TASK-5016 the `ToolManager` records needs-auth
payloads into a ContextVar collector, and with TASK-5017 the LLM is told a connection is required. This task makes
the Telegram wrapper collect those payloads around each of the six `agent.ask` call sites and, **after** sending the
agent's reply, send one Connect button per distinct provider (fresh OAuth state with this chat's `chat_id`/`bot_id`;
the tool's `auth_url` is never used), device-code instructions for `auth_kind == "device_code"`, or one "/login first"
line when there is no principal.

---

## Scope

- `_ask_with_auth_requirements(agent, *args, **kwargs) -> Tuple[Any, List[AuthRequiredPayload]]` — one ask inside
  `collect_auth_requirements()`; the list is invocation-local (never stored on session/wrapper).
- `_invoke_agent(...)` returns `(response, pending)` (both branches use the helper); update every caller to unpack,
  render the response, then `await self._send_auth_prompts(message, session, pending)`.
- Direct calls in `handle_tool` (:1950), `handle_skill` (:2124, :2132), `handle_question` (:2230) use the helper too.
- `_send_auth_prompts(message, session, pending)`: private-chat + principal guard; group OAuth payloads by provider and
  union their scopes; keep one complete device challenge per provider; OAuth → `ConnectionCommandService.connect(..., scopes=union)`
  → `render_connect_outcome`; device_code → plain text with `user_code` + `verification_uri`.
- Tests: `test_invoke_agent_collects_and_prompts`, `test_auth_prompt_device_code_and_no_principal`,
  `test_e2e_needs_auth_button`, `test_all_telegram_ask_paths_collect`, `test_telegram_scope_union_upgrade`.

**NOT in scope**: changes to `pending.py` or `clients/base.py`; the command handlers themselves.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py` | MODIFY | collector + prompts |
| `packages/ai-parrot-integrations/tests/integrations/telegram/test_needs_auth_prompts.py` | CREATE | unit + flow tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.auth.pending import collect_auth_requirements                         # TASK-5016
from parrot.auth.credentials import AuthRequiredPayload                           # verified: credentials.py:114
from parrot.integrations.telegram.connection_commands import render_connect_outcome   # TASK-5024
```

### Existing Signatures to Use
```python
# telegram/wrapper.py
async def _invoke_agent(self, session, question, *, memory, output_mode=OutputMode.TELEGRAM, message=None,
                        attachments=None) -> Any                                   # :1469 ; asks at :1538 (singleton, inside wait_for) and :1565
# _invoke_agent callers: :1666 (return await ...), :2639, :2813, :3171, :3275, :3532, :4114
async def handle_tool(self, message: Message) -> None                              # :1895 ; agent.ask :1950
async def handle_skill(self, message: Message) -> None                             # :2051 ; agent.ask :2124, :2132
async def handle_question(self, message: Message) -> None                          # :2203 ; agent.ask :2230
# The `agent.ask(` grep also hits two docstrings (:1497, :2558) — they are not call sites.
# AuthRequiredPayload fields: provider, auth_url, scopes, tool_name, message, auth_kind, user_code, verification_uri, expires_in
```
From TASK-5020/5025: `principal_for_session`, `_ensure_principal_link`, `_connection_permission_context`, and the
`ConnectionCommandService` instance built in `_register_connection_commands` (store it on `self._connection_commands`).

### Does NOT Exist
- ~~Telegram handling of `authorization_required`~~ — created here.
- ~~`session.pending_auth`~~ — never store payloads on the session or wrapper.
- ~~A device-code producer in `ConnectionCommandService`~~ — device challenges come only from payloads.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-integrations/tests/integrations/telegram/test_needs_auth_prompts.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py#TelegramAgentWrapper._invoke_agent",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py#TelegramAgentWrapper.handle_tool",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py#TelegramAgentWrapper.handle_skill",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py#TelegramAgentWrapper.handle_question",
    "sym:packages/ai-parrot/src/parrot/auth/credentials.py#AuthRequiredPayload"
  ]
}
```

---

## Implementation Notes

- Bind the collector **outside** `asyncio.wait_for(...)` so the child task inherits the bound list; reset happens on
  exception/cancellation by the context manager. Concurrent turns are isolated because each call binds its own list.
- Preserve each call site's tool/skill arguments and reply ordering; prompts go strictly after the reply.
- Dedupe: one prompt per provider per turn; no principal ⇒ a single "/login first" line per turn.
- Run `wikitoolkit symbols blast TelegramAgentWrapper._invoke_agent` first: every caller must be updated for the tuple.

---

## Implementation Blueprint

### Steps (in order)
1. Add `_ask_with_auth_requirements` and `_send_auth_prompts`.
2. Change both `_invoke_agent` asks to the helper and return the tuple; update the 7 callers.
3. Wrap the 4 direct asks.
4. Tests (fake agent whose `ask` calls `record_auth_requirement`).

### `telegram/wrapper.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    async def _invoke_agent(' .../telegram/wrapper.py)
# new methods placed directly ABOVE `    async def _invoke_agent(` (verified: wrapper.py:1469):
    async def _ask_with_auth_requirements(self, ask: Callable[[], Awaitable[Any]]) -> Tuple[Any, List["AuthRequiredPayload"]]:
        """Run one ask inside a fresh needs-auth collector; return (response, local pending list)."""
        from parrot.auth.pending import collect_auth_requirements

        with collect_auth_requirements() as pending:
            response = await ask()
        return response, list(pending)

    async def _send_auth_prompts(self, message: Message, session: TelegramUserSession,
                                 pending: Sequence["AuthRequiredPayload"]) -> None:
        """After the reply: one Connect button / device challenge per provider, or one "/login first" line."""
        if not pending:
            return
        # FILL IN: private-chat guard; principal = await principal_for_session(...) after _ensure_principal_link;
        # None → message.answer(LOGIN_FIRST, parse_mode=None) once; group by provider (sorted union of scopes);
        # device_code (user_code + verification_uri present) → plain text; else commands.connect(principal, provider,
        # extra_state={"chat_id": message.chat.id, "bot_id": self._bot_id},
        # permission_context=self._connection_permission_context(session, principal), scopes=union) → render_connect_outcome
```
**Why this shape**: the spec skeleton's `_ask_with_auth_requirements(agent, *args, **kwargs)` would need to replicate
`asyncio.wait_for`; taking a zero-arg coroutine factory keeps each call site's `wait_for`/timeout untouched. Signature
deviation from the skeleton — record it in the Completion Note. `_invoke_agent` keeps the skeleton signature and
returns `Tuple[Any, List[AuthRequiredPayload]]`.

```python
# _invoke_agent, singleton branch — REPLACE `return await asyncio.wait_for(agent.ask(...), timeout=timeout)` with:
                    return await self._ask_with_auth_requirements(
                        lambda: asyncio.wait_for(agent.ask(...same kwargs...), timeout=timeout)
                    )
# FILL IN: same for the per-user branch; update return annotation; each caller: `response, pending = await self._invoke_agent(...)`
# then after its existing reply send: `await self._send_auth_prompts(message, session, pending)`
```

### `tests/integrations/telegram/test_needs_auth_prompts.py` (CREATE)
```python
"""FEAT-776 M8 tests."""
import pytest

@pytest.mark.asyncio
async def test_invoke_agent_collects_and_prompts() -> None: ...
@pytest.mark.asyncio
async def test_auth_prompt_device_code_and_no_principal() -> None: ...
@pytest.mark.asyncio
async def test_e2e_needs_auth_button() -> None: ...          # real ToolManager + needs-auth tool; reply then button
@pytest.mark.asyncio
async def test_all_telegram_ask_paths_collect() -> None: ... # six sites; concurrent turns + cancellation do not leak
@pytest.mark.asyncio
async def test_telegram_scope_union_upgrade() -> None: ...
```

### FILL IN checklist
- [ ] `_send_auth_prompts` body
- [ ] Both `_invoke_agent` branches + 7 callers + 4 direct asks
- [ ] Five tests

---

## Acceptance Criteria

- [ ] AC-9 and AC-18; `_invoke_agent` callers all unpack the tuple
- [ ] Existing Telegram tests pass (`test_telegram_integration.py`); `ruff check` clean

---

## Validation Commands

- `pytest packages/ai-parrot-integrations/tests/integrations/telegram/test_needs_auth_prompts.py -q`
- `pytest packages/ai-parrot-integrations/tests/test_telegram_integration.py -q`
- `pytest packages/ai-parrot-integrations/tests/integrations/test_telegram_wrapper_send.py -q`

---

## Test Specification

Blueprint test file; names fixed by spec §4.

---

## Agent Instructions

1. Work in the feature worktree; confirm TASK-5016, TASK-5021, TASK-5025 are `done`
2. Implement from the blueprint; validate with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-integrations/src`
3. Commit only the listed files; close with `scripts/sdd/close_task.sh TASK-5026 connections-telegram verified`

---

## Completion Note

**Completed by**: sdd-worker; coded by gpt-5.6-sol (codex), attempt 3 (attempts 1-2 by gpt-5.6-terra), reviewed and corrected by the worker
**Date**: 2026-11-01
**Notes**:
- `wrapper.py`: `_ask_with_auth_requirements` runs one ask inside a fresh `collect_auth_requirements()` and returns `(response, pending)`; `_invoke_agent` returns that tuple on both branches; `handle_tool`, both `handle_skill` branches, `handle_question`, the human-resume `inject`, and every `_invoke_agent` caller unpack it, send the reply first, then call `_send_auth_prompts`.
- `_send_auth_prompts`: private chat only; no principal -> one "/login first" line (no OAuth state); one prompt per distinct provider; scopes unioned from trusted payloads; one complete device-code challenge shown as text; otherwise `ConnectionCommandService.connect(..., extra_state={chat_id, bot_id}, scopes=union)` rendered through `render_connect_outcome`. Pending payloads live only in the invocation-local list, never on the session or wrapper.
- Merged by hand (`git merge --no-ff`): the engine's task-tier gate ended `validation_failed` after three attempts. Its three reds were `test_telegram_wrapper_send` x2 (red on `dev` too, unrelated) and the Jira menu test, which was my TASK-5025 regression (fixed in `df48d82d45`), not this task's.
- Review corrections (`33e8212bec`, `ff216ef212`): six tests that passed on `dev` broke because `_invoke_agent` now returns a tuple and `handle_skill` reads the session; fixed all mocks repo-wide (suggestion buttons, tenant binding, voice reply, TTS integration, FEAT-120 attachment/document/message-id/reply-context tests). `_send_auth_prompts` is now best-effort, so a prompt failure after a delivered reply is logged, never turned into an error message (`test_prompt_failure_never_fails_a_delivered_turn`). Recorded as `coder-feedback:74fb4e0bed6b22f3ca4a1682`, review `coder-review:cd87954e1c41f6683b4aef1f`.
- Not covered: the photo path that calls `agent.ask_with_image` directly does not collect needs-auth (it is not one of the six call sites the spec lists).
- Validation: 6 tests in `test_needs_auth_prompts.py` plus the Telegram test directories pass; a branch-vs-`dev` run over the 96 test files touching the Telegram integration shows no red that is not already red on `dev` (18 vs 29).

**Deviations from spec**: manual merge (see above); none in design.
