# TASK-2178: examples/clients/voice — dual VoiceChatHandler provider-switch demo

**Feature**: FEAT-418 — Google Gemini Live ↔ Nova 2 Sonic Homologation
**Spec**: `sdd/specs/googlelive-nova2-audiobot-homologation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L
**Depends-on**: TASK-2174, TASK-2177
**Assigned-to**: unassigned
**Parallel-safe**: no — Final integration surface — needs the migrated handler and the extracted UI asset.

---

## Context

This is the deliverable that demonstrates the feature rather than describing
it: one aiohttp server, two `VoiceChatHandler` instances on separate routes,
each backed by a `VoiceBot` differing only in `VoiceConfig.provider`. One browser
page, one push-to-talk button, one provider toggle.

If the homologation is real, flipping the toggle changes nothing the user can
perceive except the voice. That is the acceptance test a human can run.

Implements: **Spec §3 Module 12**.

---

## Scope

- Create `examples/clients/voice/` with an aiohttp app mounting two
  `VoiceChatHandler` instances at `/ws/gemini` and `/ws/nova`, each with its own
  `VoiceBot` — same name, same system prompt, same tools, different
  `VoiceConfig`.
- Serve the extracted UI (TASK-2177) with a provider toggle. Switching closes the
  current socket and starts a **fresh session** on the other route: no memory
  replay, no transcript migration (resolved decision).
- Render a capability panel populated from each client's `voice_capabilities`,
  so the differences the descriptor declares are visible side by side.
- Show per-provider token/latency counters.
- On Python 3.11 (no `aws_sdk_bedrock_runtime`), mark the Nova route unavailable
  at startup and keep the Gemini route working — do not fail startup.
- Reconcile `examples/voice/README.md`, which documents a non-existent
  `examples/voice/bot.py`, and document the new example.

**NOT in scope**: runtime hot-swap of a client inside one `VoiceBot` (rejected in
brainstorm); cross-provider conversation continuity (spec §1 Non-Goals).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `examples/clients/voice/server.py` | CREATE | aiohttp app, two handlers, two bots |
| `examples/clients/voice/static/index.html` | MODIFY | Provider toggle + capability panel |
| `examples/clients/voice/README.md` | CREATE | How to run both providers |
| `examples/voice/README.md` | MODIFY | Reconcile the phantom `bot.py` reference |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase
> (line numbers verified 2026-08-07). The implementing agent MUST use these exact
> imports, class names, and method signatures. **DO NOT** invent, guess, or assume any
> import, attribute, or method not listed here. If you need something not listed,
> VERIFY it exists first with `grep` or `read`.

### Verified Imports

```python
from parrot.bots import VoiceBot                          # bots/__init__.py:12
from parrot.voice.handler import VoiceChatHandler         # handler.py:388
from parrot.models.voice import VoiceConfig, VoiceProvider
from aiohttp import web                                   # transport
```

### Existing Signatures to Use

```python
# packages/ai-parrot-integrations/src/parrot/voice/handler.py
class VoiceChatHandler:                                        # line 388
    @staticmethod
    def resolve_provider_client(provider): ...                 # line 490
    async def _run_voice_session(self, connection) -> None:    # line 1527
        if bot._llm is None:                                   # line 1550
            config = bot._resolve_llm_config()
            bot._llm = bot._create_llm_client(config, bot.conversation_memory)
        async def send_fn(payload: dict) -> None:              # line 1553
            if not connection.ws.closed:
                await connection.ws.send_json(payload)         # line 1555

# Mounting precedent — packages/ai-parrot-server/src/parrot/manager/manager.py
    from parrot.voice.handler import VoiceChatHandler          # line 1539
    handler = VoiceChatHandler()                               # line 1548
    # registered at /ws/voice (Mode D)                         # line 1550

# packages/ai-parrot/src/parrot/models/voice.py
class VoiceProvider(str, Enum):
    GOOGLE_LIVE = "google_live"                                # line 40
    NOVA = "nova"                                              # line 46
```

### Does NOT Exist

- ~~`VoiceBotHandler`~~ — the class is `VoiceChatHandler` (`handler.py:388`).
- ~~`examples/voice/bot.py`~~ — documented by `examples/voice/README.md` (provider switch, usage report, sample CLI) but **not in the repository**. Reconcile the README; do not assume the file exists to copy from.
- ~~A documented multi-handler mounting API~~ — the only precedent is the single mount at `manager.py:1528-1550`. Verify that two `VoiceChatHandler` instances can coexist in one app before designing around it.
- ~~Cross-provider memory continuity~~ — out of scope; each provider switch is a fresh session.
- ~~A runtime `switch_provider()` on `VoiceBot`~~ — the helper of that name at `tests/bots/test_voicebot_provider_switch.py:77` is a **test helper**, not framework API.

---

## Implementation Notes

### ⚠️ `.gitignore` trap — read this first

`examples/clients/voice/server.py` is **silently ignored** by `.gitignore:21`
(`examples/**/*.py`), and any `.html` you add is ignored by `.gitignore:28`
(`examples/**/*.html`). Verified 2026-08-07 with `git check-ignore -v`.
`README.md` and `.js` files are not ignored.

A normal `git add` will appear to succeed and the example will simply not exist
for anyone else. Use `git add -f` for every new `.py`/`.html`, and verify:

```bash
git check-ignore -v examples/clients/voice/server.py   # expect a hit
git add -f examples/clients/voice/server.py
git status --porcelain                                  # must list it
```

### Key Constraints
- **Async-first, `aiohttp` only.** No `requests`, no `httpx` (CLAUDE.md).
- Nova's SDK is lazy and Python ≥3.12-only: importing `NovaClient` must not fail
  on 3.11, and the route must degrade rather than crash the server
  (`_require_voice_sdk` fires at first `stream_voice()`).
- Both bots must share the same tools so a tool call is comparable across
  providers — that is half the point of the demo.
- Provider switch = fresh session. Close the socket and let the handler tear its
  `VoiceSession` down; do not attempt to migrate state.
- The capability panel should read the descriptor, not a hardcoded table —
  otherwise it drifts the first time a flag changes.

### References in Codebase
- `packages/ai-parrot-server/src/parrot/manager/manager.py:1528-1550` — how a handler is mounted today
- `examples/clients/nova/audio.py` — aiohttp + WS + AudioWorklet example structure
- `packages/ai-parrot/tests/bots/test_voicebot_provider_switch.py` — provider-switch semantics on `VoiceConfig`

---

## Acceptance Criteria

- [ ] One aiohttp app serves `/ws/gemini` and `/ws/nova`, each with its own `VoiceChatHandler` + `VoiceBot`
- [ ] Both bots share name, system prompt and tools; only `VoiceConfig` differs
- [ ] The browser toggle switches provider, closing the old socket and starting a fresh session
- [ ] A capability panel is rendered from `voice_capabilities` (not hardcoded)
- [ ] Per-provider token/latency counters are shown
- [ ] On Python 3.11 the Nova route reports unavailable and Gemini still works
- [ ] The UI is the shared static asset from TASK-2177, not an inlined string
- [ ] `examples/clients/voice/README.md` documents how to run both
- [ ] `examples/voice/README.md` no longer references a non-existent `bot.py`
- [ ] Manually verified end to end against both providers; result recorded in the Completion Note

---

## Test Specification

> Minimal scaffold. The agent must make these pass and add more as needed.

```python
# Automated coverage at the route level; the audio path is verified manually.

async def test_both_routes_registered(aiohttp_client):
    from examples.clients.voice.server import build_app
    client = await aiohttp_client(build_app(mock_args))
    assert (await client.ws_connect("/ws/gemini")) is not None
    assert (await client.ws_connect("/ws/nova")) is not None


async def test_nova_route_unavailable_without_sdk(monkeypatch, aiohttp_client):
    """Python 3.11 / missing aws_sdk_bedrock_runtime must degrade, not crash."""
    monkeypatch.setattr("examples.clients.voice.server.NOVA_AVAILABLE", False)
    client = await aiohttp_client(build_app(mock_args))
    resp = await client.get("/")
    assert "nova" in (await resp.text()) and "unavailable" in (await resp.text())


def test_capability_panel_reads_descriptor():
    """Guard against a hardcoded table drifting from the descriptor."""
    src = Path("examples/clients/voice/server.py").read_text()
    assert "voice_capabilities" in src
```

Manual verification (record in the Completion Note):
```bash
source .venv/bin/activate
python examples/clients/voice/server.py
# open http://localhost:8080 — talk on Gemini, flip the toggle, talk on Nova.
# Confirm: same agent behavior, same tool call, only the voice differs.
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

**RESOLVED and implemented — option (c), by explicit user direction**
("Go with option (c) for TASK-2178 — reuse chat.html instead"), after the
initial STOP documented below. This note is kept in two parts: the
original blocking analysis (unedited, for the record), followed by the
resolution and what was actually built.

---

### Part 1 — the original STOP (2026-08-07, first pass)

**STOPPED — not implemented.** Status left as `in-progress`, file left in
`sdd/tasks/active/` (not moved to `completed/`), per Cardinal Rule 4
("WHEN IN DOUBT, STOP") and the STOP Conditions ("the task's
specification contradicts the spec"). No code was written for this task.

**Attempted by**: sdd-worker (Sonnet)
**Date**: 2026-08-07

**The contradiction (verified against the current codebase, not assumed):**

This task requires BOTH of the following, and they are mutually
exclusive as literally scoped:

1. **Acceptance criterion #1**: "One aiohttp app serves `/ws/gemini` and
   `/ws/nova`, each with its own `VoiceChatHandler` + `VoiceBot`" — read
   together with the Codebase Contract's reference to
   `VoiceChatHandler.handle_websocket` (`handler.py:739`) as the mounting
   precedent (`manager.py:1528-1550` mounts exactly this method at a
   route), this means the browser must speak `VoiceChatHandler`'s actual
   WebSocket wire protocol. Verified directly from
   `handle_websocket()`'s own docstring (`handler.py:743-762`) and
   `_handle_message()`'s dispatch table (`handler.py:901-913`):
   client -> server requires `start_session` before any audio, then
   `start_recording` / `audio_data` (or `audio_chunk`) / `stop_recording`
   (not a single continuous `audio_iterator`); server -> client responses
   are wrapped as `voice_response` frames whose sub-`type` vocabulary is
   `response_chunk` / `transcription` / `display_data` / `tool_call` /
   `response_complete` / `ready_to_speak` / `session_warning`
   (`_HandlerVoiceSession.build_frames()`, `handler.py:355-462` — TASK-2174
   of this same feature). Auth handshake (`connected`/`auth_success`) and
   `ping`/`pong` keepalive are also part of this protocol.

2. **Scope** ("Serve the extracted UI (TASK-2177) with a provider
   toggle") and **acceptance criterion #7** ("The UI is the shared static
   asset from TASK-2177, not an inlined string") — but TASK-2177's
   `examples/clients/voice/static/app.js` speaks a **different, simpler**
   wire protocol by design (documented in its own header comment): client
   -> server `start_turn` / `audio` / `end_turn` / `cancel_turn`; server
   -> client `ready` / `turn_started` / `text` / `audio` / `tool_call` /
   `interrupted` / `turn_complete` / `error` / `capability_notice` — this
   is the **raw-client** protocol (`VoiceSession.build_frames()`'s
   default, core, `parrot/voice/session.py:357-443`), deliberately NOT
   `VoiceChatHandler`'s protocol. TASK-2176's own "Does NOT Exist" section
   already flags the two UIs as distinct and warns against merging them:
   `packages/ai-parrot-integrations/src/parrot/voice/ui/chat.html` is "a
   *different*, shipped UI for `VoiceChatHandler` — do not confuse the two
   or merge them."

Making the reused `app.js` actually functional against `VoiceChatHandler`
requires rewriting its entire WebSocket message layer (session handshake,
turn shape, response parsing) — not a cosmetic tweak. But `app.js` is
**not listed** in this task's "Files to Create / Modify" table (only
`server.py` CREATE, `static/index.html` MODIFY, and two READMEs are). Per
Cardinal Rule 2 (File Fidelity), touching an unlisted file is a
divergence; per Cardinal Rule 1, redesigning `app.js`'s protocol to
invent a translation layer the task never specified is architecture the
task doesn't authorize. Implementing acceptance criterion #1 correctly
and acceptance criterion #7 literally are not simultaneously satisfiable
without one of:

- **(a)** Add `app.js` to this task's file list and accept a real rewrite
  of its WS message layer to speak `VoiceChatHandler`'s protocol (keeping
  its visual/DOM layer, `PROVIDER_LABEL` genericization, and AudioWorklet
  capture code intact) — the most literal reading of "reuse the UI,"
  reinterpreted as "reuse the presentation layer."
- **(b)** Have `server.py` implement a protocol-translating bridge in
  front of `VoiceChatHandler` (a custom WS route that speaks the
  raw-client protocol to the browser and drives `VoiceChatHandler`
  internals — e.g. `_run_voice_session` — underneath) so `app.js` needs
  zero changes — but this means the two example routes are no longer
  literally `app.router.add_get(path, handler.handle_websocket)` as
  acceptance criterion #1 and the mounting precedent imply, and invents
  an unspec'd adapter class.
- **(c)** Drop acceptance criterion #7 and serve the existing, protocol-
  correct `packages/ai-parrot-integrations/src/parrot/voice/ui/chat.html`
  instead (with a provider-toggle addition), since it already speaks
  `VoiceChatHandler`'s real protocol — the technically simplest path, but
  directly contradicts an explicit, numbered acceptance criterion rather
  than a soft preference.

Each of (a)/(b)/(c) is a legitimate design decision, but it IS a design
decision — not a detail this task leaves to the implementer's judgment
(the Files table and the acceptance criteria are both explicit and both
verified accurate against the current code, so neither can be dismissed
as stale). Flagging for the spec owner rather than guessing.

**What was verified before stopping (no code changes made)**:
`VoiceChatHandler` (`handler.py:500`), `resolve_provider_client`
(`handler.py:601-610`), `handle_websocket` (`handler.py:739`), `BotConfig`
(`handler.py:127-162`), `WebSocketConnection` (`handler.py:169-241`),
`_HandlerVoiceSession.build_frames()` (`handler.py:355-462`), the
`manager.py:1528-1550` mounting precedent, and
`examples/clients/voice/static/app.js`'s protocol (created in TASK-2177,
completed immediately prior to this task in this same run) were all read
directly, not assumed. Line numbers in the Codebase Contract for
`VoiceChatHandler`/`resolve_provider_client` had drifted since the
contract was written (`388`/`490` → `500`/`601`) — noted here since the
contract should be corrected before this task is picked up again, but
this drift is not itself the blocker; the protocol contradiction above is.

**Deviations from spec**: N/A — task not implemented in this pass.

---

### Part 2 — resolution and implementation (2026-08-07, second pass)

**Completed by**: sdd-worker (Sonnet)
**Date**: 2026-08-07

**Resolution chosen**: option (c) from Part 1 — dropped the literal
"reuse TASK-2177's static asset" framing of acceptance criterion #7 and
instead reused `packages/ai-parrot-integrations/src/parrot/voice/ui/
chat.html` (the shipped UI that already speaks `VoiceChatHandler`'s real
protocol), adapted with a provider toggle, capability panel, and usage
strip. This satisfies the *intent* of criterion #7 ("shared static asset,
not inlined in a .py file") without inventing an unspec'd protocol
translation layer or rewriting TASK-2177's `app.js` (which stays
untouched and still serves `examples/clients/nova/audio.py` unmodified).

**What was implemented**:
- `examples/clients/voice/server.py` (force-added, `.gitignore` trap
  confirmed and handled) — `build_app()` mounts two `VoiceChatHandler`
  instances via `setup_routes()` (`ws_route`/`health_route` set to
  `/ws/gemini`+`/health/gemini` and `/ws/nova`+`/health/nova` respectively
  — verified empirically that two instances coexist in one `web.
  Application` without route collisions, per the Codebase Contract's
  explicit "verify before designing around it" note). `make_gemini_bot()`/
  `make_nova_bot()` factories build a fresh `VoiceBot` per connection
  (`bot_factory()` is called fresh by `_handle_start_session()` for every
  new WebSocket) sharing `name`, `system_prompt`, and one `@tool`-decorated
  `get_weather` function; only `VoiceConfig.provider`/default voice differ.
  `_nova_sdk_available()` probes `aws_sdk_bedrock_runtime` once at import
  time; when absent, the Nova route stays mounted (not removed) but
  `make_nova_bot()` raises immediately with a clear message, caught by
  `handle_websocket`'s existing blanket exception handler and reported as
  a WS `error` frame — verified via `TestClient`, no crash. `build_
  capabilities()` instantiates a bare `GeminiLiveClient()`/`NovaClient()`
  (safe without credentials or the Nova SDK — both resolve lazily) purely
  to read `.voice_capabilities` and serialize it to JSON for the
  capability panel.
- `examples/clients/voice/static/dual_provider.html` (force-added) — an
  adapted copy of `chat.html` with: a provider-toggle button group in the
  header (switches `wsUrl`, clears the transcript, calls `reconnect()` —
  fresh session per switch, no memory replay, matching spec §1 Non-Goals);
  a capability-panel table in the settings drawer rendered from
  `CONFIG.capabilities[activeProvider]` (never hardcoded); a usage strip
  updated from `response_complete.usage` (new field, see below). Templated
  the same `__CONFIG__`-replace way as TASK-2177's asset.
- **`packages/ai-parrot-integrations/src/parrot/voice/handler.py`** (NOT
  in the original Files-to-Modify list — a documented, minimal deviation):
  `_HandlerVoiceSession.build_frames()`'s `response_complete` frame
  carried no usage data at all on the streaming path (unlike
  `_send_complete_voice_response()`'s non-streaming `voice_response`,
  which already had one) — there was no other place in the wire protocol
  to source real per-turn token/latency data from for acceptance criterion
  "Per-provider token/latency counters are shown". Added an optional
  `usage` key (`input_tokens`/`output_tokens`/`total_tokens`/
  `response_time_ms`/`first_token_time_ms`), sourced directly from
  `resp.usage` (`LiveCompletionUsage`, already computed by both
  providers) — omitted entirely when absent, not zeroed. 2 new regression
  tests in `test_handler_refactor.py`.
- `examples/clients/voice/README.md` (created) and `examples/voice/
  README.md` (reconciled — no longer documents the never-built,
  now-explicitly-out-of-scope `bot.py` hot-swap CLI; redirects to the real
  example).

**Two pre-existing bugs found and fixed during end-to-end verification**
(both discovered by actually running the server against a real `VoiceBot`
via `aiohttp.test_utils.TestClient`, not just unit-testing in isolation —
neither is FEAT-418-specific, both are universal `VoiceChatHandler`/
`VoiceBot` defects nothing had exercised before):
1. **`VoiceSession._run_turn()` never forwarded `stt_only` as an explicit
   kwarg** to `stream_voice()` (both real clients read it only from that
   dedicated parameter, never from `options.stt_only`) — fixed in
   `packages/ai-parrot/src/parrot/voice/session.py` with 3 regression
   tests (flagged as CRITICAL by the feature-level adversarial code
   review; fixed before this task resumed).
2. **`VoiceBot.system_prompt` (the property) was never initialized** —
   `AbstractBot.__init__()` only ever sets the separate
   `system_prompt_template` attribute; nothing in the synchronous
   construction path calls the `system_prompt` property setter that backs
   `_system_prompt_template`. Any freshly constructed `VoiceBot` —
   including via `VoiceChatHandler`'s default `bot_factory`, which never
   runs the async `configure()` flow — raised `AttributeError` the moment
   `_run_voice_session()` read `bot.system_prompt`. Reproduced against a
   plain `VoiceBot()` with zero mocks. Fixed with two lines inside
   `VoiceBot.__init__` (`packages/ai-parrot/src/parrot/bots/voice.py`,
   routing through the existing property setter) — deliberately NOT
   touching the shared `AbstractBot` foundation. 3 regression tests added.
   Without this fix, no real end-to-end `VoiceChatHandler` session could
   ever start, for any bot, on any provider — this task's own manual
   verification step is what surfaced it.

**Manual/automated verification performed** (in lieu of a literal browser
session — this sandboxed environment has no browser, no Google API key,
no AWS credentials; the same environment constraint documented in
TASK-2177's note): an `aiohttp.test_utils.TestClient` end-to-end script
confirmed (1) the index page serves and templates correctly (`__CONFIG__`
fully replaced, provider toggle and capability table scaffolding present);
(2) both `/ws/gemini` and `/ws/nova` handshake and coexist with distinct
health routes; (3) `/ws/nova` degrades gracefully to a WS `error` frame
(no crash) when the SDK is absent; (4) a **real** `/ws/gemini` session
reaches `session_started` with a genuine `GeminiLiveClient`-backed
`VoiceBot` (no mocks) and tears down cleanly — this is the path that
surfaced fix #2 above. A human with a `GOOGLE_API_KEY` and AWS Bedrock
credentials should still run the two-browser-tab manual check described
in the Test Specification before treating this as demo-ready.

**Deviations from spec** (all documented above, none silent):
- Acceptance criterion #7 satisfied in intent, not literal file identity
  (chat.html-derived asset, not TASK-2177's asset) — per explicit user
  direction (option c).
- `handler.py` touched despite not being in the original Files table (the
  `usage` field addition) — minimal, additive, necessary for the
  token/latency counters criterion; documented in its own commit message.
- `bots/voice.py` touched despite not being in the original Files table
  (the `system_prompt` property fix) — a pre-existing, universal bug this
  task's own verification requirement (manual end-to-end run) surfaced;
  without it the example cannot start any real session at all.
- `examples/voice/README.md`'s reconciliation removes the hot-swap
  CLI documentation wholesale rather than writing the never-specified
  `bot.py` script — that script's runtime `switch_provider()` design is
  explicitly out of scope per this task's own NOT-in-scope line and the
  Codebase Contract's "Does NOT Exist" section.
