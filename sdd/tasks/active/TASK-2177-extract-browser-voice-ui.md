# TASK-2177: Extract the browser voice UI asset + migrate the Nova example to VoiceSession

**Feature**: FEAT-418 — Google Gemini Live ↔ Nova 2 Sonic Homologation
**Spec**: `sdd/specs/googlelive-nova2-audiobot-homologation.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M
**Depends-on**: TASK-2171
**Assigned-to**: unassigned
**Parallel-safe**: yes — Touches only examples/; shares no source files with the core or integrations tasks.

---

## Context

`examples/clients/nova/audio.py` is 1073 lines, of which ~560 are an
`INDEX_HTML` string (line 459) holding the AudioWorklet push-to-talk UI. It also
still carries its own `NovaVoiceSession` (line 116) — the very class FEAT-416
promoted into `parrot.voice.session.VoiceSession`, left behind when the
promotion landed.

The provider-switch example (TASK-2178) needs that UI, and copying 560 lines of
HTML into a second Python file is not an option.

Implements: **Spec §3 Module 11**.

---

## Scope

- Extract `INDEX_HTML` into a standalone static asset under
  `examples/clients/voice/static/` (HTML + any JS/AudioWorklet split that makes
  it readable), served from disk rather than embedded in Python.
- Migrate `examples/clients/nova/audio.py` off its local `NovaVoiceSession`
  (`:116-338`) onto the core `VoiceSession`, and have it serve the shared asset.
- Keep the example runnable and keep its stated purpose intact: it demonstrates
  the **raw client** contract end to end (its docstring says "No `VoiceBot`, no
  `VoiceChatHandler`"), so it must keep talking to `NovaClient` directly.
- Verify manually that push-to-talk still works against a real Nova session, and
  record the result in the Completion Note.

**NOT in scope**: the dual-handler example itself (TASK-2178); deleting the Nova
example (explicitly rejected — it survives, spec §8).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `examples/clients/voice/static/index.html` | CREATE | Extracted UI |
| `examples/clients/voice/static/` (JS/worklet) | CREATE | Split-out scripts if warranted |
| `examples/clients/nova/audio.py` | MODIFY | Use core `VoiceSession`; serve the shared asset |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase
> (line numbers verified 2026-08-07). The implementing agent MUST use these exact
> imports, class names, and method signatures. **DO NOT** invent, guess, or assume any
> import, attribute, or method not listed here. If you need something not listed,
> VERIFY it exists first with `grep` or `read`.

### Verified Imports

```python
from parrot.voice.session import VoiceSession      # voice/session.py:36 (core)
from parrot.clients.nova import NovaClient         # clients/nova/client.py
from aiohttp import web                            # transport — never requests/httpx
```

### Existing Signatures to Use

```python
# examples/clients/nova/audio.py (current state)
class NovaVoiceSession:                                       # line 116 — DELETE, use core class
async def index(request):                                     # line ~350
    html = INDEX_HTML.replace("__CONFIG__", json.dumps(cfg))  # line 354
    return web.Response(text=html, content_type="text/html")  # line 355
async def websocket_handler(request):                         # line ~358
    """Bridge one browser WebSocket to a NovaVoiceSession."""   # line 359
    session = NovaVoiceSession(                               # line 363
def build_app(args) -> web.Application:                       # line 418
INDEX_HTML = r"""<!DOCTYPE html>                              # line 459 — ~560 lines
def parse_args() -> argparse.Namespace:                       # line 1020
def main() -> None:                                           # line 1061

# packages/ai-parrot/src/parrot/voice/session.py — the replacement
class VoiceSession:                                           # line 36
    def __init__(self, client, send_fn, system_prompt,        # line 53
                 voice_config=None, session_id=None)
    async def start_turn(self) -> None:                       # line 77
    async def push_audio(self, pcm: bytes) -> None:           # line 91
    async def end_turn(self) -> None:                         # line 99
    async def close(self) -> None:                            # line 136
```

### Does NOT Exist

- ~~`examples/clients/voice/`~~ — does not exist; this task creates it.
- ~~Any shared browser voice UI asset~~ — the only UI is the inlined `INDEX_HTML` at `examples/clients/nova/audio.py:459`. (`packages/ai-parrot-integrations/src/parrot/voice/ui/chat.html` is a *different*, shipped UI for `VoiceChatHandler` — do not confuse the two or merge them.)
- ~~`examples/voice/bot.py`~~ — documented by `examples/voice/README.md` but absent from the repo. Do not "restore" it here; TASK-2178 reconciles that README.
- ~~`NovaVoiceSession` in the framework~~ — the promoted class is `VoiceSession` (`parrot/voice/session.py:36`); the example's copy is stale.

---

## Implementation Notes

### ⚠️ `.gitignore` trap — read this first

`.gitignore` silently swallows the files this task creates:

```
.gitignore:21  examples/**/*.py     → examples/clients/voice/*.py     IGNORED
.gitignore:28  examples/**/*.html   → examples/clients/voice/static/index.html  IGNORED
```

Verified 2026-08-07 with `git check-ignore -v`. `README.md` and `.js` files under
`examples/` are **not** ignored. If you `git add` normally, the extracted UI will
appear to commit fine and simply not exist for anyone else — the same class of
failure as the `sdd/templates/` note in `CLAUDE.md`.

**Every new `.py` and `.html` under `examples/` in this task must be added with
`git add -f`.** Verify before committing:

```bash
git check-ignore -v examples/clients/voice/static/index.html   # expect a hit
git add -f examples/clients/voice/static/index.html
git status --porcelain                                          # must list it
```

Putting the AudioWorklet/JS in a separate `.js` file (not ignored) reduces how
much has to be force-added — and is better structure anyway.

### Key Constraints
- `VoiceSession` takes an injected `send_fn`, not a WebSocket — wrap
  `ws.send_json` in a small adapter, exactly as `_run_voice_session()` does at
  `handler.py:1553-1555`.
- The example's `end_turn()` silence pacing is already in the core class
  (`voice/session.py:99-134`) — do not re-implement it in the example.
- Keep the example single-purpose: raw `NovaClient`, no `VoiceBot`, no
  `VoiceChatHandler`. That contrast with TASK-2178's example is the point.
- Serve the static asset with `aiohttp`'s static/file response; keep
  `__CONFIG__` templating working (`audio.py:354`) or replace it with a
  documented equivalent.

---

## Acceptance Criteria

- [ ] The browser UI lives in a static asset, not a Python string
- [ ] `examples/clients/nova/audio.py` no longer defines `NovaVoiceSession`
- [ ] It uses `parrot.voice.session.VoiceSession` with a `send_fn` adapter
- [ ] It still drives `NovaClient` directly (no `VoiceBot`, no `VoiceChatHandler`)
- [ ] The example runs and push-to-talk works end to end (verified manually, recorded in the Completion Note)
- [ ] The extracted asset is reusable by TASK-2178 without modification
- [ ] `ruff check examples/clients/nova/audio.py`

---

## Test Specification

> Minimal scaffold. The agent must make these pass and add more as needed.

```python
# examples/ has no automated test suite; verification is manual + import-level.

def test_example_imports_core_voice_session():
    """Guard against the example drifting back to a local session class."""
    src = Path("examples/clients/nova/audio.py").read_text()
    assert "from parrot.voice.session import VoiceSession" in src
    assert "class NovaVoiceSession" not in src


def test_static_asset_exists_and_is_served():
    assert Path("examples/clients/voice/static/index.html").exists()
```

Manual verification (record in the Completion Note):
```bash
source .venv/bin/activate
python examples/clients/nova/audio.py --voice tiffany
# open http://localhost:8080 — hold the button, confirm audio in + audio out
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
