# TASK-3151: `_formdesigner` branch in `MSTeamsAgentWrapper._handle_card_submission` + shared aiohttp session lifecycle

**Feature**: FEAT-551 — MS Teams FormDesigner Renderer (Adaptive Card + submit envelope via the Teams bot)
**Spec**: `sdd/specs/msteams-formdesigner-renderer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3150
**Assigned-to**: unassigned
**Parallel**: false — edits `wrapper.py`, which imports the TASK-3150 helpers.

---

## Context

Spec §3 Module 4 (second half). The Bot Framework bot is the receptor of every Adaptive Card
`Action.Submit` in Teams (user decision). `_handle_card_submission` (`wrapper.py:359-491`) already
branches on `a2ui_token`, `a2ui_action`, `command`, `_action`; a standalone FormDesigner card today
falls to `dialog_context.continue_dialog()` and gets *"wasn't expecting it"* (`:489-491`). This task
inserts the `_formdesigner` branch right after the `a2ui_action` branch (mirroring TASK-2545) and
adds the shared HTTP session the helpers need.

---

## Scope

- `wrapper.py`: import helpers; `__init__` attrs `_formdesigner_session = None`, `_formdesigner_recent = RecentActivityCache()`; new methods `_handle_formdesigner_submit`, `_get_formdesigner_session`, `close_formdesigner_client`; branch insertion.
- Tests (skip cleanly without `botbuilder`, like `test_a2ui_submit.py`): routes, disabled-without-allowlist, returns-before-command-router, never continues dialog, malformed envelope → text.

**NOT in scope**: helpers' logic (TASK-3150); docs (TASK-3152); Redis-backed dedupe.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py` | MODIFY | branch + session + close |
| `packages/ai-parrot-integrations/tests/msteams/test_formdesigner_wrapper.py` | CREATE | routing tests (importorskip botbuilder) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# wrapper.py already has:
from aiohttp import web                                     # wrapper.py:15
from .models import MSTeamsAgentConfig                      # wrapper.py:26
# add:
import aiohttp
from .formdesigner_submit import (EnvelopeRejected, RecentActivityCache, build_reply_card, extract_answers,
                                  parse_envelope, post_submission, verify_envelope)   # TASK-3150
from parrot_formdesigner.renderers.teams import ENVELOPE_KEY                          # TASK-3147
# tests:
pytest.importorskip("botbuilder")                           # test_a2ui_submit.py:30
from parrot.integrations.msteams.wrapper import MSTeamsAgentWrapper
```

### Existing Signatures to Use
```python
# msteams/wrapper.py
class MSTeamsAgentWrapper(ActivityHandler, MessageHandler):                            # 79
    def __init__(self, agent, config, app, ...)                                        # 106 ; self.config = config :117 ; self.logger :119 ; self._voice_transcriber :125 ; self.form_orchestrator :148 ; self.adapter :155
    def _is_authorized(self, conversation_id, user_id) -> bool                         # 285
    async def _handle_card_submission(self, turn_context, dialog_context)              # 359
        # submitted_data = turn_context.activity.value :365 ; auth check :370-381
        # a2ui_action branch :413-443 ends with `return` (:443)
        # comment "# Slash-style commands embedded in Adaptive Card Submit actions — e.g." :445 (occurrences: 1)
        # command = submitted_data.get("command") :451 ; action = submitted_data.get("_action", "submit") :458
        # results = await dialog_context.continue_dialog() :470 ; DialogTurnStatus.Empty -> send_text("I received your submission but wasn't expecting it...") :489-491
    async def close_voice_transcriber(self) -> None                                    # 976-980 (lifecycle precedent)
# msteams/handler.py (mixin)
async def send_text(self, text: str, turn_context)                                     # 35
async def send_card(self, card_data: Dict[str, Any], turn_context) -> None             # 60
# msteams/graph.py (session pattern)
self._session: Optional[aiohttp.ClientSession] = None :116 ; _get_session :120-128 ; close :130-136
# tests/msteams/test_a2ui_submit.py (harness to copy)
def _wrapper(*, process_message_result=None) -> MSTeamsAgentWrapper   # 36-53: MSTeamsAgentWrapper.__new__ + SimpleNamespace config + MagicMock logger + AsyncMock send_text/_send_parsed_response
def _turn_context(value: dict) -> MagicMock                             # 56-62: ctx.activity.value / conversation.id / from_property.id
# TASK-3150 helpers
parse_envelope(data) -> TeamsSubmitEnvelope ; verify_envelope(env, *, allowed_hosts, secret, api_base_path="/api/v1") ; extract_answers(data) ;
post_submission(session, env, answers, *, bearer_token, timeout) -> SubmitOutcome ; build_reply_card(outcome, env) -> dict ; RecentActivityCache().seen(id) -> bool
# config (TASK-3150)
config.formdesigner_allowed_hosts / formdesigner_submit_token / formdesigner_submit_secret / formdesigner_submit_timeout
```

### Does NOT Exist
- ~~`MSTeamsAgentWrapper.close()`~~ — no generic close; add `close_formdesigner_client()` alongside `close_voice_transcriber` (:976).
- ~~`turn_context.activity.id` handling anywhere in wrapper.py~~ — first use is THIS task (dedupe key; may be `None` in tests → skip dedupe when falsy).
- ~~`self.form_orchestrator` involvement~~ — the FormDesigner branch does NOT go through the orchestrator/dialogs (unlike `a2ui_action`).
- ~~`api_base_path` on `MSTeamsAgentConfig`~~ — not a field; derive the expected path check's base from the envelope's own `submit_url` is NOT allowed either (S3). Pass `api_base_path="/api/v1"` (the FormDesigner default, `routes.py:198`); make it a module constant `FORMDESIGNER_API_BASE_PATH = "/api/v1"` in wrapper.py.
- ~~`botbuilder` in the dev venv~~ — tests must `pytest.importorskip("botbuilder")`.

---

## Implementation Notes

### Pattern to Follow
```python
# wrapper.py:413-443 — the a2ui_action branch: read key, act, reply, `return` (never fall through)
a2ui_action = submitted_data.get("a2ui_action")
if a2ui_action:
    ...
    return
```

### Key Constraints
- Branch placement: AFTER the `a2ui_action` branch's `return` (:443) and BEFORE the "# Slash-style commands…" comment (:445) so `command` never sees `_formdesigner` payloads.
- Empty/None `formdesigner_allowed_hosts` ⇒ `send_text("Form submissions are not enabled for this bot.")` and return — the branch is still "handled".
- Wrap the whole branch body in `try/except Exception` → log + `send_text("Could not process your submission.")`; never raise into the adapter.

---

## Implementation Blueprint

### Steps (in order)
1. Add imports and `FORMDESIGNER_API_BASE_PATH` constant — *why*: helpers are imported at module level (they are botbuilder-free).
2. Initialise `_formdesigner_session`/`_formdesigner_recent` in `__init__` — *why*: S10 (one session), S9 (dedupe).
3. Insert the branch — *why*: spec §3 M4 insertion point (TASK-2545 pattern).
4. Add the three methods next to `close_voice_transcriber` — *why*: lifecycle symmetry.
5. Tests; run `pytest packages/ai-parrot-integrations/tests/msteams/test_formdesigner_wrapper.py -q` (skips locally; runs in CI).

### `packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py` (MODIFY — imports + init)
```python
# occurrences: 1 (verified: grep -c 'from .models import MSTeamsAgentConfig' msteams/wrapper.py)
# AFTER — insert below `from .models import MSTeamsAgentConfig` (verified: wrapper.py:26)
import aiohttp
from .formdesigner_submit import (
    EnvelopeRejected, RecentActivityCache, build_reply_card, extract_answers,
    parse_envelope, post_submission, verify_envelope,
)
from parrot_formdesigner.renderers.teams import ENVELOPE_KEY

FORMDESIGNER_API_BASE_PATH: str = "/api/v1"   # FormDesigner setup_form_api default (routes.py:198)

# occurrences: 1 (verified: grep -c 'self.form_orchestrator = FormOrchestrator(' msteams/wrapper.py)
# BEFORE — insert above `        self.form_orchestrator = FormOrchestrator(` (verified: wrapper.py:148)
        # FormDesigner card submissions (FEAT-551)
        self._formdesigner_session: Optional[aiohttp.ClientSession] = None
        self._formdesigner_recent = RecentActivityCache()
```
**Why**: `Optional` is already imported (`wrapper.py:14`).

### `packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py` (MODIFY — branch)
```python
# occurrences: 1 (verified: grep -c '# Slash-style commands embedded in Adaptive Card Submit actions' msteams/wrapper.py)
# BEFORE — insert above `        # Slash-style commands embedded in Adaptive Card Submit actions — e.g.` (verified: wrapper.py:445)
        # FormDesigner standalone card (FEAT-551): card Submit carries {"_formdesigner": <envelope>, "_action": "submit",
        # **{field_id: value}}. Verified and forwarded to POST .../forms/{uid}/data — never routed to dialogs.
        if ENVELOPE_KEY in submitted_data:
            await self._handle_formdesigner_submit(turn_context, submitted_data)
            return

```
**Why**: keyed on the envelope's presence so `_action: "submit"` from dialog presets (no envelope) keeps its dialog semantics.

### `packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py` (MODIFY — methods)
```python
# occurrences: 1 (verified: grep -c 'async def close_voice_transcriber(self) -> None:' msteams/wrapper.py)
# BEFORE — insert above `    async def close_voice_transcriber(self) -> None:` (verified: wrapper.py:976)
    async def _handle_formdesigner_submit(self, turn_context: TurnContext, submitted_data: Dict[str, Any]) -> None:
        """Forward a FormDesigner Teams-card submission (spec §3 M4). Never raises; never continues the dialog."""
        allowed = list(self.config.formdesigner_allowed_hosts or [])
        if not allowed:
            await self.send_text("Form submissions are not enabled for this bot.", turn_context)
            return
        try:
            env = parse_envelope(submitted_data)
            verify_envelope(env, allowed_hosts=allowed, secret=self.config.formdesigner_submit_secret,
                            api_base_path=FORMDESIGNER_API_BASE_PATH)
            activity_id = getattr(turn_context.activity, "id", None)
            if activity_id and self._formdesigner_recent.seen(activity_id):
                self.logger.info("formdesigner submit: duplicate activity %s ignored", activity_id)
                return
            answers = extract_answers(submitted_data)
            outcome = await post_submission(await self._get_formdesigner_session(), env, answers,
                                            bearer_token=self.config.formdesigner_submit_token,
                                            timeout=self.config.formdesigner_submit_timeout)
            self.logger.info("formdesigner submit: form=%s status=%s", env.form_uid, outcome.status)
            await self.send_card(build_reply_card(outcome, env), turn_context)
        except EnvelopeRejected as exc:
            await self.send_text(str(exc), turn_context)
        except Exception:  # noqa: BLE001 — adapter must never see an exception from a card submit
            self.logger.exception("formdesigner submit failed")
            await self.send_text("Could not process your submission. Please try again later.", turn_context)

    async def _get_formdesigner_session(self) -> aiohttp.ClientSession:
        """Lazily create the shared outbound session (pattern: graph.py:120-128)."""
        if self._formdesigner_session is None or getattr(self._formdesigner_session, "closed", False):
            self._formdesigner_session = aiohttp.ClientSession()
        return self._formdesigner_session

    async def close_formdesigner_client(self) -> None:
        """Close the shared outbound session (pattern: close_voice_transcriber)."""
        if self._formdesigner_session is not None and not getattr(self._formdesigner_session, "closed", False):
            await self._formdesigner_session.close()
        self._formdesigner_session = None
```
**Why**: the method is the only place config is read; helpers stay pure. `TurnContext`/`Dict`/`Any` are already imported in wrapper.py (`:14`, `:16-22`).

### `packages/ai-parrot-integrations/tests/msteams/test_formdesigner_wrapper.py` (CREATE)
```python
"""Routing tests for the FEAT-551 `_formdesigner` branch (skips without botbuilder, like test_a2ui_submit.py)."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

pytest.importorskip("botbuilder")
from parrot.integrations.msteams import wrapper as wrapper_mod
from parrot.integrations.msteams.wrapper import MSTeamsAgentWrapper

pytestmark = pytest.mark.asyncio


def _wrapper(allowed_hosts=("forms.test",)) -> MSTeamsAgentWrapper:
    w = MSTeamsAgentWrapper.__new__(MSTeamsAgentWrapper)
    w.config = SimpleNamespace(allowed_conversation_ids=None, allowed_user_ids=None,
                               formdesigner_allowed_hosts=list(allowed_hosts), formdesigner_submit_token=None,
                               formdesigner_submit_secret=None, formdesigner_submit_timeout=5.0)
    w.logger = MagicMock(); w._command_router = MagicMock(); w._command_router.try_dispatch = AsyncMock(return_value=True)
    w.form_orchestrator = MagicMock(); w.send_text = AsyncMock(); w.send_card = AsyncMock()
    w._formdesigner_session = None; w._formdesigner_recent = wrapper_mod.RecentActivityCache()
    return w


def _ctx(value: dict) -> MagicMock:
    ctx = MagicMock(); ctx.activity.value = value; ctx.activity.id = "act-1"
    ctx.activity.conversation.id = "conv-1"; ctx.activity.from_property.id = "user-1"
    return ctx


async def test_teams_wrapper_routes_formdesigner_submit():
    # FILL IN: valid envelope dict (see test_formdesigner_submit._env) + {"_action": "submit", "name": "x"};
    #   patch wrapper_mod.post_submission (AsyncMock -> SubmitOutcome(status=200, body={"submission_id": "s1"}));
    #   dialog_context = MagicMock(continue_dialog=AsyncMock()); await w._handle_card_submission(_ctx(value), dialog_context);
    #   assert post_submission awaited once with answers == {"name": "x"}; send_card awaited; continue_dialog NOT awaited;
    #   _command_router.try_dispatch NOT awaited even if value also has "command" — bounded by AC "returns before command routing"
    raise NotImplementedError


async def test_teams_wrapper_formdesigner_disabled_without_allowlist():
    # FILL IN: _wrapper(allowed_hosts=()) -> send_text called with "not enabled"; post_submission not called — bounded by S3
    raise NotImplementedError


async def test_teams_wrapper_malformed_envelope_is_text_reply():
    # FILL IN: value {"_formdesigner": {"bad": 1}, "_action": "submit"} -> send_text awaited once; continue_dialog not awaited
    raise NotImplementedError
```
**Why**: same stubbing approach as `test_a2ui_submit.py:36-62`, so CI (with the `msteams` extra) exercises the real branch while local runs skip.

### FILL IN checklist
- [ ] test bodies (3) — bounded by spec §5 AC bullets "returns before command routing", "never continue_dialog", S3 disabled message.
- [ ] Confirm `Optional`, `Dict`, `Any`, `TurnContext` imports exist in wrapper.py before relying on them (`:14`, `:16-22`).

---

## Acceptance Criteria

- [ ] Implementation complete per scope
- [ ] Tests pass (or skip cleanly without botbuilder): `pytest packages/ai-parrot-integrations/tests/msteams/test_formdesigner_wrapper.py -v`; existing `test_a2ui_submit.py` unchanged and green in CI
- [ ] No linting errors: `ruff check packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py`
- [ ] Branch sits after the `a2ui_action` branch and before the `command` branch; `grep -n "ENVELOPE_KEY in submitted_data" wrapper.py` line < `grep -n 'command = submitted_data.get("command")'` line
- [ ] A card with `_formdesigner` never reaches `dialog_context.continue_dialog()` nor the command router
- [ ] Empty allowlist → "not enabled" message, no HTTP call
- [ ] One `aiohttp.ClientSession` per wrapper, closed by `close_formdesigner_client()`

---

## Test Specification

See blueprint.

---

## Agent Instructions

1. Read spec §3 M4 and §7 Known Risks (SSRF, duplicates).
2. Check TASK-3150 is in `sdd/tasks/completed/`.
3. Verify anchors (`grep -n "Slash-style commands embedded" wrapper.py`).
4. Update index status → `"in-progress"`.
5. Implement from the blueprint; complete every `# FILL IN:`.
6. Verify acceptance criteria.
7. Move this file to `sdd/tasks/completed/TASK-3151-msteams-wrapper-formdesigner-branch.md`; index → `"done"`; Completion Note.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
