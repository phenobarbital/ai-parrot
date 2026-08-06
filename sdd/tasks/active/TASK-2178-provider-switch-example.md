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

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
