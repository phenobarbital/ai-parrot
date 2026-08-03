# TASK-2108: Render role in the example and document the protocol contract

**Feature**: FEAT-408 — Nova Sonic Protocol Fidelity
**Spec**: `sdd/specs/nova-sonic-protocol-fidelity.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2102, TASK-2103, TASK-2105, TASK-2106
**Assigned-to**: unassigned

---

## Context

Implements spec Module 9. `examples/clients/nova/audio.py` carries a documented
"Known limitation" saying the user's transcription and the assistant's reply
cannot be told apart. TASK-2102 removes that limitation by plumbing
`LiveVoiceResponse.role`, so the note is now **wrong** and must go — a stale
"this can't be done" note is worse than none.

This task closes the loop: the example renders speakers separately, and the Nova
voice documentation records the protocol contract this feature established so the
next person does not have to re-derive it from AWS samples.

---

## Scope

- Remove the "Known limitation" section from
  `examples/clients/nova/audio.py`'s module docstring.
- Relay `role` over the example's WebSocket protocol and render user vs assistant
  bubbles from it (the UI already has `.bubble.you` / `.bubble.assistant` styles —
  the placeholder `🎙 speaking…` bubble can become the real transcription).
- Surface real token usage in the example's `turn_complete` note (TASK-2106 makes
  it non-zero).
- Document the Nova Sonic protocol contract in `docs/`: the frame sequence, role
  and generation-stage semantics, the tool three-frame envelope, barge-in
  detection, and the AWS sample references.
- Record the two SDK facts that cost the most time: `BedrockAgentRuntimeClient`
  does not exist, and `Config.aws_credentials_identity_resolver` must be set
  explicitly.

**NOT in scope**: any change to `parrot/clients/nova/audio.py` (all protocol work
is done by TASK-2101…2107); adding `role` to `VoiceBot` or `VoiceChatHandler`
public protocols (spec §8 open question 3, deliberately deferred).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `examples/clients/nova/audio.py` | MODIFY | Drop stale note; relay + render `role`; show usage |
| `docs/nova_voice_protocol.md` | CREATE | Protocol contract reference |
| `docs/voice_chat.md` | MODIFY | Cross-link the new Nova protocol doc |

> ⚠️ **`examples/**/*.py` is gitignored** (`.gitignore:21`). `examples/clients/nova/audio.py`
> is currently untracked. To commit changes to it you must `git add -f`. Decide
> with the feature owner whether this example should be force-added or whether
> the ignore rule should be narrowed; record the decision in the Completion Note.

---

## Codebase Contract (Anti-Hallucination)

> Line numbers verified on branch `fix/nova-sonic-bidirectional-sdk` @ `89204b9f0`.

### Verified Imports

```python
# examples/clients/nova/audio.py — existing, verified working
from aiohttp import WSMsgType, web
from parrot.clients.live import LiveVoiceResponse   # verified: clients/live.py:156
from parrot.clients.nova import NovaClient          # verified: clients/nova/__init__.py:10
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/clients/live.py
@dataclass
class LiveVoiceResponse:                              # line 156
    text: str = ""                                    # line 164
    role: Optional[str] = None                        # ADDED BY TASK-2100
    usage: Optional[LiveCompletionUsage] = None       # line 176
    is_complete: bool = False                         # line 169
    is_interrupted: bool = False                      # line 170
    metadata: Dict[str, Any] = field(default_factory=dict)   # line 187

# examples/clients/nova/audio.py — the relay method to extend
class NovaVoiceSession:
    async def _relay(self, resp: LiveVoiceResponse, turn_no: int) -> None: ...
    # sends frames: {"type": "text"|"audio"|"tool_call"|"interrupted"|
    #                "turn_complete"|"error", ...}
```

Existing browser-side hooks in that file, verified present:

```javascript
function addBubble(kind, text, who)   // kind: "assistant" | "you" | "system" | "error"
function appendStream(chunk)          // appends into the current assistant bubble
case "text":  appendStream(msg.text); break;
```

### Does NOT Exist

- ~~`LiveVoiceResponse.role`~~ before TASK-2100 — **verify that task is completed**
  before relying on it.
- ~~a `role` key in the example's WebSocket protocol~~ — this task adds it.
- ~~`docs/nova_voice_protocol.md`~~ — this task creates it.
- ~~`.bubble.user` CSS class~~ — the class is `.bubble.you`.
- ~~`examples/clients/nova/audio.py` being tracked by git~~ — it is **ignored**;
  see the warning above.

---

## Implementation Notes

### Pattern to Follow

Server relay — pass the role straight through:

```python
        if resp.text:
            await self._send({
                "type": "text",
                "turn": turn_no,
                "text": resp.text,
                "role": resp.role,
            })
```

Browser — route by role instead of always appending to the assistant bubble:

```javascript
      case "text":
        appendStream(msg.text, msg.role);   // start a new bubble when role changes
        break;
```

`appendStream` needs a `role` parameter and must close the current bubble when the
role changes, so consecutive same-role chunks still stream into one bubble:

```javascript
let streamRole = null;
function appendStream(chunk, role) {
  if (streamBubble && role !== streamRole) closeStream();
  if (!streamBubble) {
    streamBubble = addBubble(role === "USER" ? "you" : "assistant", "",
                             role === "USER" ? "You" : "Nova");
    streamText = "";
    streamRole = role;
  }
  ...
}
```

Remove the placeholder `addBubble("you", "🎙 speaking…", "You")` from
`startTalking()` — the real USER transcription now arrives from Nova.

### Key Constraints

- The example must still work when `role` is `null` (e.g. if pointed at a
  provider that does not report one) — fall back to the assistant bubble.
- Do not change the example's public WS message `type` values; only add the `role`
  key. The frontend guides in `docs/frontend/` describe this protocol shape.
- The docs page is a **reference**, not a tutorial: state the frame sequence and
  cite the AWS sample file + line for each claim, so it stays auditable.
- Do not restate the transport-layer fix as if it were part of this feature;
  reference commit `89204b9f0` instead.

### References in Codebase

- `docs/voice_chat.md` — existing voice doc, and the WebSocket protocol table to
  mirror in style.
- `docs/frontend/voicebot-realtime-frontend-guide.md` — the frontend contract
  consumers rely on.
- `sdd/specs/nova-sonic-protocol-fidelity.spec.md` §6 — the "Does NOT Exist" list
  worth carrying into the docs page.

---

## Acceptance Criteria

- [ ] The "Known limitation" section is gone from the example's module docstring.
- [ ] The example relays `role` and renders USER text in a `you` bubble and
      ASSISTANT text in an `assistant` bubble.
- [ ] Consecutive same-role chunks stream into a single bubble; a role change
      starts a new one.
- [ ] `role: null` falls back to the assistant bubble without error.
- [ ] The placeholder `🎙 speaking…` bubble is removed.
- [ ] `turn_complete` shows real token counts.
- [ ] `docs/nova_voice_protocol.md` documents: the full frame sequence, role +
      `generationStage` semantics, the tool three-frame envelope, barge-in
      detection, graceful shutdown, and the two SDK gotchas — each with an AWS
      sample citation.
- [ ] `docs/voice_chat.md` links to the new page.
- [ ] The example's embedded JS still parses: `node --check` on the extracted
      `<script>` block.
- [ ] The example still starts and serves its page (smoke test as in
      `sdd/specs/nova-sonic-protocol-fidelity.spec.md` §4 integration tests).
- [ ] Completion Note records the decision about the `examples/**/*.py` ignore rule.

---

## Test Specification

```python
# Verification is by smoke test + JS syntax check, not unit tests — this task
# changes an example and documentation, neither of which is imported by the suite.

# 1. JS syntax check (extract the <script> block from INDEX_HTML, then):
#    node --check /tmp/page.js

# 2. Server smoke test — page serves and a turn relays role:
import asyncio, json, types, aiohttp, importlib.util

def _load_example():
    spec = importlib.util.spec_from_file_location(
        "nova_audio_example", "examples/clients/nova/audio.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

async def test_page_serves_and_relays_role():
    mod = _load_example()
    args = types.SimpleNamespace(
        host="localhost", port=8097, model="nova-2-sonic", voice="matthew",
        region="us-east-1", aws_id=None, system_prompt="be brief")
    app = mod.build_app(args)
    runner = aiohttp.web.AppRunner(app)
    await runner.setup()
    await aiohttp.web.TCPSite(runner, "localhost", 8097).start()
    async with aiohttp.ClientSession() as s:
        async with s.get("http://localhost:8097/") as r:
            html = await r.text()
        assert r.status == 200
        assert "streamRole" in html          # role-aware rendering present
        assert "speaking…" not in html       # placeholder bubble removed
    await runner.cleanup()

asyncio.run(test_page_serves_and_relays_role())
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-2102, TASK-2103, TASK-2105 and TASK-2106
   are all in `sdd/tasks/completed/`. This task documents their behaviour; writing
   it early would document intentions rather than reality.
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm `LiveVoiceResponse.role` exists (TASK-2100)
   - Confirm the example's `_relay()` and browser `appendStream()` still match
     what is quoted
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `sdd/tasks/index/nova-sonic-protocol-fidelity.json` → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2108-docs-and-example-role-rendering.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.
**`examples/**/*.py` ignore-rule decision**: force-added | rule narrowed | left untracked

**Deviations from spec**: none | describe if any
