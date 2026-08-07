# TASK-2168: Gemini: GoAway → reconnect_required + session resumption handle

**Feature**: FEAT-418 — Google Gemini Live ↔ Nova 2 Sonic Homologation
**Spec**: `sdd/specs/googlelive-nova2-audiobot-homologation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L
**Depends-on**: TASK-2167
**Assigned-to**: unassigned
**Parallel-safe**: yes — Gemini lane — same file as TASK-2166/2167; disjoint from the Nova lane.

---

## Context

Nova signals its 465-second connection limit with
`metadata["reconnect_required"]` (`nova/audio.py:271`, `:860`), which drives
`VoiceSession`'s reconnection loop (`voice/session.py:196-228`). Gemini emits
only `metadata["go_away"]` (`live.py:1077`, `:1107`), which that loop ignores —
so Gemini sessions simply end where Nova sessions transparently continue.

`google-genai` 2.17.0 (installed) additionally supports session resumption
handles (`LiveServerSessionResumptionUpdate`, verified at
`google/genai/types.py:20484-20598`), so Gemini can do better than a cold
reconnect: it can resume with context.

Implements: **Spec §3 Module 5**.

---

## Scope

- Enable session resumption on connect via `types.SessionResumptionConfig` and
  retain the handle delivered in `session_resumption_update`.
- On `GoAway` (both paths: `live.py:1072-1077` and the 1008 server-close at
  `:1107`), set `metadata["reconnect_required"]=True` **in addition to** keeping
  `go_away` as an informational flag, so `VoiceSession` reconnects.
- On reconnect, pass the stored handle so the session resumes with context.
- If the handle is rejected or expired, fall back to a cold reconnect and mark
  the emitted frame `resumed: false`.
- Flip `emits_reconnect_signal=True` and `supports_session_resumption=True` in
  Gemini's descriptor; set `max_session_seconds` to the documented Live limit
  (or `None` if the provider documents none under context-window compression).
- Tests per spec §4.

**NOT in scope**: changing `VoiceSession`'s reconnection loop — it already
handles `reconnect_required` correctly (TASK-2171 only adds option threading).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/live.py` | MODIFY | Resumption config, handle retention, GoAway mapping |
| `packages/ai-parrot/tests/clients/test_live_resumption.py` | CREATE | Resumption + reconnect-signal tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase
> (line numbers verified 2026-08-07). The implementing agent MUST use these exact
> imports, class names, and method signatures. **DO NOT** invent, guess, or assume any
> import, attribute, or method not listed here. If you need something not listed,
> VERIFY it exists first with `grep` or `read`.

### Verified Imports

```python
from parrot.clients.live import GeminiLiveClient, LiveVoiceResponse   # clients/live.py
from google.genai import types                                       # google-genai 2.17.0
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/clients/live.py
# GoAway handling (session ending):
if hasattr(response, 'go_away') and response.go_away:         # line 1072
    self.logger.info("Received GoAway from server")           # line 1073
    ...
    metadata={"go_away": True, "reason": str(response.go_away)},   # line 1077
...
metadata={"go_away": True, "reason": "Server closed session (1008)"},  # line 1107

# The connection call to extend with SessionResumptionConfig:
async with self.client.aio.live.connect(                      # line ~793
    model=self.model, config=live_config
) as session:

# packages/ai-parrot/src/parrot/voice/session.py — the loop this must feed
if not (resp.metadata.get("reconnect_required")               # line 196-199
        and self.voice_config.reconnect_on_limit):
    continue
if self._reconnect_count >= self.voice_config.max_reconnects: # line 202
```

### Does NOT Exist

- ~~Gemini emitting `metadata["reconnect_required"]` today~~ — it emits only `go_away` (`live.py:1077`, `:1107`).
- ~~A resumption handle attribute on `GeminiLiveClient`~~ — no such state exists; this task introduces it.
- ~~`VoiceSession` reacting to `go_away`~~ — it does not; only `reconnect_required` drives the loop (`voice/session.py:196-199`). Do NOT add `go_away` handling to the session — map it in the client instead.
- ~~A documented Gemini session-length constant in this repo~~ — `_CONNECTION_LIMIT_SECONDS` (`nova/audio.py:271`) is Nova-only. Verify Gemini's limit against Google's docs; if context-window compression removes it, use `None`.

---

## Implementation Notes

### Key Constraints
- **Verify the SDK surface before coding.** `grep` `session_resumption` in
  `.venv/lib/python3.11/site-packages/google/genai/types.py` (hits confirmed at
  lines 20484-20598) to get the exact config class and update-message field
  names. Do not guess them.
- Keep `go_away` in the metadata. The integrations handler already reacts to it
  (`handler.py:298`) and TASK-2174 depends on that behavior staying intact.
- Emit the frame **before** the reconnect decision — spec §7 and
  `voice/session.py:188-200` require any pending tool calls in that response to
  be relayed first.
- The handle is per-session state: reset it when a session ends for a reason
  other than reconnection, so a stale handle is never replayed into a new
  conversation.

---

## Acceptance Criteria

- [ ] `GoAway` produces `metadata["reconnect_required"]=True` on both paths (`live.py:1072-1077`, `:1107`)
- [ ] `metadata["go_away"]` is still emitted alongside it
- [ ] Session resumption is enabled on connect and the handle is retained
- [ ] Reconnect reuses the handle; a rejected/expired handle falls back to a cold reconnect with `resumed: false`
- [ ] Gemini descriptor: `emits_reconnect_signal=True`, `supports_session_resumption=True`, `max_session_seconds` set or explicitly `None`
- [ ] `VoiceSession`'s existing reconnection tests still pass: `pytest packages/ai-parrot/tests/voice/test_voice_reconnection.py -v`
- [ ] Tests pass: `pytest packages/ai-parrot/tests/clients/test_live_resumption.py -v`

---

## Test Specification

> Minimal scaffold. The agent must make these pass and add more as needed.

```python
# packages/ai-parrot/tests/clients/test_live_resumption.py
import pytest


class TestReconnectSignal:
    async def test_goaway_sets_reconnect_required(self, mocked_goaway_session):
        responses = [r async for r in mocked_goaway_session.stream_voice(...)]
        assert any(r.metadata.get("reconnect_required") for r in responses)

    async def test_goaway_flag_preserved(self, mocked_goaway_session):
        """handler.py:298 still reacts to go_away — do not drop it."""
        responses = [r async for r in mocked_goaway_session.stream_voice(...)]
        assert any(r.metadata.get("go_away") for r in responses)

    async def test_server_close_1008_also_signals(self, mocked_1008_session):
        responses = [r async for r in mocked_1008_session.stream_voice(...)]
        assert any(r.metadata.get("reconnect_required") for r in responses)


class TestResumption:
    async def test_handle_retained(self, mocked_resumption_session):
        [r async for r in mocked_resumption_session.stream_voice(...)]
        assert mocked_resumption_session._resumption_handle is not None

    async def test_expired_handle_falls_back_cold(self, mocked_expired_handle):
        responses = [r async for r in mocked_expired_handle.stream_voice(...)]
        assert any(r.metadata.get("resumed") is False for r in responses)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `sdd/tasks/index/googlelive-nova2-audiobot-homologation.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-08-07
**Notes**: Verified the exact `google-genai` 2.17.0 SDK surface before coding
(per the task's explicit instruction): `LiveConnectConfig.session_resumption:
Optional[SessionResumptionConfig]` (`types.py:21532`),
`SessionResumptionConfig(handle: Optional[str], transparent: Optional[bool])`
(`types.py:20719`), and `LiveServerMessage.session_resumption_update:
Optional[LiveServerSessionResumptionUpdate]` (`types.py:20598`) with fields
`new_handle`/`resumable`/`last_consumed_client_message_index`
(`types.py:20481`). Added `self._resumption_handle` instance state
(`None` initially); `_build_live_config()` now always requests session
resumption (`session_resumption=types.SessionResumptionConfig(handle=
self._resumption_handle)`), so the first connect starts fresh and a
resumable session's handle rides into the next `stream_voice()` call
unmodified. The receive loop retains `new_handle` whenever
`resumable=True`. Both `GoAway` (`live.py` ~1246) and the 1008
server-close path now additionally set
`metadata["reconnect_required"]=True` while keeping `metadata["go_away"]`
(handler.py:298 still reacts to it, per the task's explicit constraint).
A rejected/expired handle is detected heuristically (the SDK exposes no
typed exception for this) in the outer `except Exception` handler: only
triggered when `self._resumption_handle` was actually set for the
attempt AND the error text mentions "resumption"/"handle"/"expired" —
clears the handle and yields `metadata={"resumed": False,
"reconnect_required": True}`, relying on `VoiceSession`'s existing
reconnect loop (unmodified, per scope) to call `stream_voice()` again,
which then connects cold. Flipped `emits_reconnect_signal=True` and
`supports_session_resumption=True`; set `max_session_seconds=None` with
an inline comment explaining why: `_build_live_config()` already
requests `context_window_compression` unconditionally (pre-existing,
sliding window), which is documented as removing the Live API's fixed
session-length ceiling — so `None` reflects "no documented limit under
this configuration" rather than an unverified guess. 13 new tests in
`tests/clients/test_live_resumption.py`, including coverage for the
non-resumable-update and generic-error-not-misclassified edge cases.
`tests/voice/test_voice_reconnection.py` (5 tests, unmodified) still
green — confirms the existing `VoiceSession` loop needed no changes.
Full voice-domain regression (117 tests) green except the one
already-documented pre-existing `test_no_aiohttp_import` failure.

**Deviations from spec**: none.
