# TASK-5051: AgentTalk emits `auth_required` + server-authored `retry_safe` in both response modes

**Feature**: FEAT-777 — Connections — Web + Slack
**Spec**: `sdd/specs/connections-web-slack.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-5035, TASK-5049, TASK-5050
**Assigned-to**: unassigned

---

## Context

Spec §2 "Chat (M4)", §3 Module 4 (server half), G3, AC-7. Today AgentTalk returns an `AuthRequiredEnvelope` only
when `AuthorizationRequired`/`CredentialRequired` escapes `bot.ask()` (`agent.py:1917-1923`). But
`ToolManager` converts those exceptions into a `ToolResult(status="authorization_required")`, and the client unwraps
it to `result.result` (`None`) before storing it on `AIMessage.tool_calls` (`clients/base.py:1660-1667`) — so the common
case never reaches the UI, and the streaming path has no `auth_required` frame at all.

This task wraps every AgentTalk turn in two turn-scoped collectors from TASK-5050:

- `collect_auth_requirements()` (`parrot/auth/pending.py`) — every needs-auth payload raised during the turn;
- `track_turn()` (`parrot/auth/retry_safety.py`) — whether any tool body began.

and emits:

- **non-streaming**: `AuthRequiredEnvelope(**first_payload, retry_safe=…)` JSON (HTTP 200) instead of the formatted reply;
- **streaming**: after the envelope frame, one trailer `b"\n\x00" + json({"auth_required": payload, "turn_id": …, "retry_safe": …})`
  (same NUL framing as the FEAT-752 suggestions trailer, `agent.py:2621-2644`).

**Spec deviation (record in the Completion Note)**: spec §3 M4's `_auth_required_from(ai_message)` reads
`AIMessage.tool_calls[*].result`; that cannot work on dev (see above). The payload source is the collector; the helper
keeps its name but takes the collected list.

---

## Scope

- Open both collectors once per `post()` turn with a `contextlib.ExitStack` created before the main `try`
  (`agent.py:1841`) and closed in that `try`'s `finally` — so the streaming iteration inside
  `_handle_stream_response` is covered too.
- Add module helper `_auth_required_from(pending)` and method `_retry_safe(...)`.
- Non-streaming success path: if a requirement was collected, return the envelope instead of `_format_response(...)`.
- Exception path (`except (AuthorizationRequired, CredentialRequired)`): set `retry_safe` from the tracker.
- Streaming: add `_write_auth_required_trailer(stream_resp, ai_message)` and call it right after the envelope frame.
- Tests.

**NOT in scope**: `AuthRequiredEnvelope.retry_safe` field definition (TASK-5035), the tracker/collector (TASK-5050),
the UI parser and pill (TASK-5054, TASK-5055), deleting the Jira bootstrap (TASK-5049 — already gone when this starts).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/agent.py` | MODIFY | turn collectors, envelope, streaming trailer |
| `tests/unit/integrations/oauth2/test_agenttalk_envelope.py` | MODIFY | non-streaming collector path + `retry_safe` |
| `packages/ai-parrot-server/tests/unit/test_agenttalk_auth_required_stream.py` | CREATE | streaming trailer + retry-safety matrix |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.auth.credentials import AuthRequiredPayload, CredentialRequired   # verified: credentials.py:114, :128 (CredentialRequired already imported agent.py:51)
from parrot.auth.oauth2.models import AuthRequiredEnvelope                    # verified: agent.py:53 (gains retry_safe in TASK-5035)
from parrot.auth.pending import collect_auth_requirements                     # created by TASK-5050 (FEAT-775/776 shared contract)
from parrot.auth.retry_safety import TurnExecutionTracker, current_turn_tracker, track_turn   # created by TASK-5050
import contextlib                                                             # verified: agent.py:9
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/handlers/agent.py  (line numbers BEFORE TASK-5049, which deletes ~50 lines above :1100)
async def post(self):                                     # :1548 (AgentTalk)
#   `        upload_errors = None` (:1840) then `        try:` (:1841) — the turn's main try
#   streaming dispatch `return await self._handle_stream_response(...)` (:1861-1880)
#   non-streaming `response: AIMessage = await bot.ask(...)` (:1902-1915) / bot.followup (:1883)
#   `        except (AuthorizationRequired, CredentialRequired) as exc:` (:1917) → envelope (:1921-1923)
#   `        finally:` (:2027) … last line `            reset_current_web_session(_hitl_token)` (:2056)
#   `        # Return formatted response` (:2081) → `return self._format_response(response, ...)` (:2082-2093)
async def _write_suggestions_trailer(self, stream_resp, bot, ai_message) -> None   # :2621 — framing b"\n\x00" + json_encoder(...)
async def _handle_stream_response(self, bot, query, ...) -> web.StreamResponse   # :2646
#   envelope frame write (:2773-2775); `                    await self._write_suggestions_trailer(stream_resp, bot, ai_message)` (:2778)

# packages/ai-parrot/src/parrot/models/responses.py
class AIMessage: tool_calls: List[ToolCall] (:158); turn_id: Optional[str] (:168)

# TASK-5050
class TurnExecutionTracker: def retry_safe(self, *, auth_requirements: int, reported_tool_calls: int) -> bool
def collect_auth_requirements() -> ContextManager[List[AuthRequiredPayload]]
```

### Does NOT Exist
- ~~`authorization_required` `ToolResult`s on `AIMessage.tool_calls[*].result`~~ — unwrapped to `None` by `clients/base.py:1667`.
- ~~An `auth_required` stream frame~~ today — added here.
- ~~A `retry_safe` field computed by the client~~ — server-authored only; absent means false.
- ~~`_bootstrap_jira_oauth_session`~~ — removed by TASK-5049.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-server/src/parrot/handlers/agent.py", "action": "MODIFY"},
    {"path": "tests/unit/integrations/oauth2/test_agenttalk_envelope.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/tests/unit/test_agenttalk_auth_required_stream.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/handlers/agent.py#AgentTalk.post",
    "sym:packages/ai-parrot-server/src/parrot/handlers/agent.py#AgentTalk._handle_stream_response",
    "sym:packages/ai-parrot-server/src/parrot/handlers/agent.py#AgentTalk._write_suggestions_trailer",
    "sym:packages/ai-parrot/src/parrot/auth/oauth2/models.py#AuthRequiredEnvelope",
    "sym:packages/ai-parrot/src/parrot/auth/credentials.py#AuthRequiredPayload"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- One decision function for both modes; the client never computes safety (spec §3 M4).
- Multiple collected requirements → expose the first payload, `retry_safe=False`.
- The trailer never raises (client cancellation excepted), mirroring `_write_suggestions_trailer`.
- No token material: `AuthRequiredPayload` carries none; never add tool arguments to the trailer.
- The ExitStack must be closed on every exit (`finally`), including the early `return`s inside the `try`.

---

## Implementation Blueprint

### Steps (in order)
1. Re-locate every anchor (`grep -n`) — *why*: TASK-5049 removed ~50 lines above, so all line numbers moved.
2. Add the module helper and imports — *why*: shared by both modes.
3. Open the collectors before the main `try` and close them in its `finally` — *why*: the stream is iterated inside that `try`.
4. Non-streaming: envelope instead of formatted reply when a requirement was collected; `retry_safe` in the exception path too.
5. Streaming trailer.
6. Tests.

### `packages/ai-parrot-server/src/parrot/handlers/agent.py` (MODIFY — imports + helper)
```python
# occurrences: 1 (verified: grep -c 'from parrot.auth.oauth2.models import AuthRequiredEnvelope' …agent.py)
# AFTER — insert below `from parrot.auth.oauth2.models import AuthRequiredEnvelope` (verified: agent.py:53)
from parrot.auth.credentials import AuthRequiredPayload
from parrot.auth.pending import collect_auth_requirements
from parrot.auth.retry_safety import current_turn_tracker, track_turn


def _auth_required_from(pending: List[AuthRequiredPayload]) -> Optional[AuthRequiredPayload]:
    """First needs-auth payload collected this turn (v1 exposes one pill), or ``None``."""
    return pending[0] if pending else None
```

### `packages/ai-parrot-server/src/parrot/handlers/agent.py` (MODIFY — turn scope)
```python
# occurrences: 1 (verified: grep -c '        upload_errors = None' …agent.py)
# AFTER — insert below `        upload_errors = None` (verified: agent.py:1840), before `        try:`
        turn_scope = contextlib.ExitStack()
        self._turn_auth_pending = turn_scope.enter_context(collect_auth_requirements())
        turn_scope.enter_context(track_turn())

# occurrences: 1 (verified: grep -c '            reset_current_web_session(_hitl_token)' …agent.py)
# AFTER — insert below `            reset_current_web_session(_hitl_token)` (verified: agent.py:2056), still inside `finally:`
            turn_scope.close()
```
**Why**: `ExitStack` avoids re-indenting ~190 lines; `self` is the per-request view instance, so the attribute is turn-local.
`turn_scope.close()` resets both ContextVar tokens in the same task that set them.
FILL IN: confirm `_format_response` and the HITL resume path (:1352) do not run tools after `finally` — bounded by "tracker covers the whole turn".

### `packages/ai-parrot-server/src/parrot/handlers/agent.py` (MODIFY — decision + non-streaming)
```python
# New method on AgentTalk (place directly above `    async def _write_suggestions_trailer(`; occurrences: 1, verified :2621):
    def _turn_auth_requirement(self, ai_message: Optional[AIMessage]) -> Optional[tuple]:
        """``(payload, retry_safe)`` for this turn's first needs-auth requirement, or ``None``."""
        pending = getattr(self, "_turn_auth_pending", None) or []
        payload = _auth_required_from(pending)
        if payload is None:
            return None
        tracker = current_turn_tracker()
        reported = len(getattr(ai_message, "tool_calls", None) or [])
        safe = tracker is not None and tracker.retry_safe(auth_requirements=len(pending), reported_tool_calls=reported)
        return payload, safe

# occurrences: 1 (verified: grep -c '        except (AuthorizationRequired, CredentialRequired) as exc:' …agent.py)
# In that except block (verified :1917-1923) build the envelope with the flag:
            payload = exc.to_payload() if isinstance(exc, AuthorizationRequired) else exc.to_payload(tool_name=None)
            tracker = current_turn_tracker()
            pending = getattr(self, "_turn_auth_pending", None) or []
            # FILL IN: count = len(pending) if any collected payload equals `payload` (same provider+tool_name) else len(pending) + 1;
            #          retry_safe = tracker.retry_safe(auth_requirements=count, reported_tool_calls=<dispatches the tracker saw>)
            #          — bounded by AC-7 ("multiple outstanding auth requirements force false")
            envelope = AuthRequiredEnvelope(**payload.model_dump(), retry_safe=retry_safe)
            return web.json_response(envelope.model_dump(), status=200)

# Capture the decision while the tracker is still bound (inside the try), use it after `finally`:
# 1) next to the turn-scope lines above (before `        try:`), add:
        turn_auth = None
# 2) inside the `try`, directly after the non-streaming `if followup_turn_id ...: … else: response = await bot.ask(...)`
#    if/else (verified: ends at agent.py:1915, same indentation as that `if`), add:
                turn_auth = self._turn_auth_requirement(response)
# 3) occurrences: 1 (verified: grep -c '        # Return formatted response' …agent.py)
#    BEFORE — insert above `        # Return formatted response` (verified: agent.py:2081)
        if turn_auth is not None:
            payload, retry_safe = turn_auth
            envelope = AuthRequiredEnvelope(**payload.model_dump(), retry_safe=retry_safe)
            return web.json_response(envelope.model_dump(), status=200)
```
**Why**: `# Return formatted response` runs after the `finally` that closes `turn_scope`, when `current_turn_tracker()`
is already `None`; reading it there would make every turn unsafe.

### `packages/ai-parrot-server/src/parrot/handlers/agent.py` (MODIFY — streaming trailer)
```python
# occurrences: 1 (verified: grep -c '    async def _write_suggestions_trailer(' …agent.py)
# BEFORE — insert above `    async def _write_suggestions_trailer(` (verified: agent.py:2621)
    async def _write_auth_required_trailer(self, stream_resp: web.StreamResponse, ai_message: AIMessage) -> None:
        """Write ``\\n\\x00{"auth_required", "turn_id", "retry_safe"}`` after the envelope when this turn needed auth.

        Never raises (client cancellation excepted), like :meth:`_write_suggestions_trailer`.
        """
        auth = self._turn_auth_requirement(ai_message)
        if auth is None:
            return
        payload, retry_safe = auth
        trailer = {
            "auth_required": payload.model_dump(mode="json"),
            "turn_id": str(getattr(ai_message, "turn_id", "") or ""),
            "retry_safe": bool(retry_safe),
        }
        try:
            await stream_resp.write(b"\n\x00" + json_encoder(trailer).encode("utf-8"))
            await stream_resp.drain()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — the trailer is best-effort
            self.logger.warning("auth_required trailer skipped: %s", exc)

# occurrences: 1 (verified: grep -c '                    await self._write_suggestions_trailer(stream_resp, bot, ai_message)' …agent.py)
# The envelope write is at :2773-2775 followed by `                if suggestions_trailer:` (:2777). INSERT between them:
                await self._write_auth_required_trailer(stream_resp, ai_message)
```
**Why the position**: the client must have the envelope before the pill (spec §2); putting it before the suggestions
trailer avoids waiting up to `suggestion_timeout_s` for chips.

### Tests
```python
# tests/unit/integrations/oauth2/test_agenttalk_envelope.py — ADD:
def test_envelope_carries_retry_safe_default_false() -> None:
    """AuthRequiredEnvelope(...).retry_safe defaults to False and round-trips True."""
    # FILL IN

# packages/ai-parrot-server/tests/unit/test_agenttalk_auth_required_stream.py (CREATE)
"""FEAT-777 M4: AgentTalk auth_required in both modes."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from parrot.auth.credentials import AuthRequiredPayload
from parrot.auth.pending import collect_auth_requirements, record_auth_requirement
from parrot.auth.retry_safety import track_turn
from parrot.handlers.agent import AgentTalk


@pytest.mark.asyncio
async def test_agenttalk_stream_auth_required_trailer() -> None:
    """Collected payload (incl. device-code fields) → trailer after the envelope frame; none → no trailer."""
    # FILL IN: handler = object.__new__(AgentTalk); handler.logger = Mock(); stream_resp = AsyncMock(write, drain);
    #          inside collect_auth_requirements() as p + track_turn() as t: record a payload, set handler._turn_auth_pending = p;
    #          await handler._write_auth_required_trailer(stream_resp, SimpleNamespace(turn_id="t1", tool_calls=[...]))


@pytest.mark.asyncio
async def test_agenttalk_auth_required_from_tool_result() -> None:
    """Non-streaming: a collected requirement returns AuthRequiredEnvelope JSON (status 200) instead of the reply."""
    # FILL IN


@pytest.mark.asyncio
async def test_agenttalk_retry_safety() -> None:
    """Pre-dispatch auth only → retry_safe True; body started then auth → False; two requirements → False."""
    # FILL IN: drive TurnExecutionTracker marks directly; assert the same decision in trailer and envelope
```

### FILL IN checklist
- [ ] verify no tool runs after `finally` — bounded by "tracker covers the whole turn"
- [ ] exception-path requirement count — bounded by AC-7
- [ ] four tests — bounded by spec §4 rows `test_agenttalk_auth_required_from_tool_result`, `test_agenttalk_stream_auth_required_trailer`, `test_agenttalk_retry_safety`

---

## Acceptance Criteria

- [ ] Non-streaming turn whose tool needed auth → HTTP 200 `AuthRequiredEnvelope` with `retry_safe` (AC-7).
- [ ] Streaming turn → envelope frame, then one `auth_required` trailer carrying the full payload (device-code fields included).
- [ ] `retry_safe` is `True` only for one requirement with no tool body begun; otherwise `False`/absent.
- [ ] Turns without needs-auth are byte-identical to today (no trailer, same JSON).
- [ ] `ruff check packages/ai-parrot-server/src/parrot/handlers/agent.py` clean.

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/unit/test_agenttalk_auth_required_stream.py -q`
- `pytest tests/unit/integrations/oauth2/test_agenttalk_envelope.py -q`
- `pytest tests/integration/oauth2/test_e2e_auth_envelope.py -q`

---

## Test Specification

| Test | Must assert |
|---|---|
| `test_agenttalk_auth_required_from_tool_result` | collected payload → envelope JSON; nothing collected → normal reply |
| `test_agenttalk_stream_auth_required_trailer` | trailer bytes start with `\n\x00`; JSON keys `auth_required`, `turn_id`, `retry_safe`; `user_code`/`verification_uri` preserved |
| `test_agenttalk_retry_safety` | the safe/unsafe matrix, same decision in both modes |
| `test_envelope_carries_retry_safe_default_false` | default `False` |

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug connections-web-slack --feature-id FEAT-777`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/connections-web-slack.json`
4. **Verify the Codebase Contract** — re-grep every anchor (line numbers moved after TASK-5049); read TASK-5050's merged API
5. **Update status** in the per-spec index → `"in-progress"` and commit only that index file
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:`
7. **Verify** — run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src`
8. **Commit the code** — stage only the files listed above
9. **Close the task** with `scripts/sdd/close_task.sh TASK-5051 connections-web-slack verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: Record that the payload source is the turn collector, not `AIMessage.tool_calls` (spec §3 M4 deviation).

**Deviations from spec**: `_auth_required_from` takes the collected list.
