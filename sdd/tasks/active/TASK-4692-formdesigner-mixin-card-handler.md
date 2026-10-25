# TASK-4692: TeamsFormDesignerMixin: picker, wizard and submit handler (M4 part 2)

**Feature**: FEAT-734 — Serve FormDesigner forms from a Teams agent
**Spec**: `sdd/specs/formdesigner-serve-forms.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L
**Depends-on**: TASK-4691
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 4**, second half: the ONE card-submission handler,
`handle_formdesigner_card(turn_context, submitted_data) -> bool`, covering the
picker action, wizard Next/Cancel/Submit, and a single-card terminal submit —
always POSTing with the **speaking user's** bearer (never
`formdesigner_submit_token`), with the signed envelope verified as defence in
depth. Spec §3 Delivery contracts ("Wizard routing and state") define the
validation rules this task enforces.

Extends `formdesigner_mixin.py` and `test_formdesigner_serve.py` from TASK-4691
(same files → strictly after it). Wave 4.

**Cross-feature note — FEAT-733 is not merged.** Today's `verify_envelope`
skips the signature check when `secret is None` and has no `require_signature`.
So the mixin enforces the signature ITSELF: no configured secret → refuse; an
envelope without `sig` → refuse; then call `verify_envelope(...)` with keywords
only (`allowed_hosts=`, `secret=`, `api_base_path=`). This is correct both before
and after FEAT-733 lands (its default `require_signature=True` agrees).

---

## Scope

- Add `handle_formdesigner_card`, `_fd_wizard_action`, `_fd_submit`,
  `_fd_section_field_ids`, `_fd_allowed_hosts_for` to `TeamsFormDesignerMixin`.
- Routing (return value):
  - `data[PICKER_ACTION_KEY] == "get_form"` → `serve_form(form_ref=data["form_uid"])` → `True`
    (the card's `tenant` is ignored; identity is re-resolved).
  - `data[PICKER_ACTION_KEY]` is a dict with `kind == "wizard"` → `_fd_wizard_action` → `True` ALWAYS
    (even when invalid — wizard actions must never fall through to the service-token lane).
  - `ENVELOPE_KEY` present, no control object: mixin not enabled → `False`
    (wrapper's FEAT-551 fallback); else `_fd_submit` → `True`.
  - anything else → `False`.
- Wizard rules (under `state.lock`): reject mismatched owner, tenant, `wizard_id`,
  `section_index`, unknown action, changed form version, consumed state, or a
  duplicate `activity.id` (checked INSIDE the lock). Missing/expired state →
  "send /getform again" card, never a partial POST.
- Answers: drop the whole `PICKER_ACTION_KEY` object, then `extract_answers`,
  then keep only field IDs of the CURRENT section.
- Terminal: verify envelope; match `env.tenant`, `env.form_uid`, `env.form_version`
  to the state; set `state.consumed = True` BEFORE the one POST; `finish()` after.
- Never show a verification reason to the user (log it; reply with a generic card).
- Append the tests listed under Test Specification.

**NOT in scope**: wrapper routing (TASK-4693); Back/Skip (disabled in v1).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/formdesigner_mixin.py` | MODIFY | handle_formdesigner_card, _fd_wizard_action, _fd_submit |
| `packages/ai-parrot-integrations/tests/msteams/test_formdesigner_serve.py` | MODIFY | inbound handler tests |


---

## Codebase Contract (Anti-Hallucination)

### Verified Imports (add to formdesigner_mixin.py)
```python
from parrot_formdesigner.renderers.teams import ENVELOPE_KEY      # renderers/teams.py:36
from .formdesigner_submit import (                                 # formdesigner_submit.py
    EnvelopeRejected,       # line 28
    build_reply_card,       # line 122
    extract_answers,        # line 60 — strips ONLY {"_action", "_formdesigner"}; NOT PICKER_ACTION_KEY
    parse_envelope,         # line 32 — raises EnvelopeRejected
    post_submission,        # line 73
    verify_envelope,        # line 44
)
```

### Existing Signatures to Use
```python
# formdesigner_submit.py
def verify_envelope(env, *, allowed_hosts: list[str], secret: str | None, api_base_path: str = "/api/v1") -> None  # line 44
#   checks https, host allowlist, path == {api}/{tenant}/forms/{uid}/data, then signature ONLY if secret is not None
async def post_submission(session, env, answers, *, bearer_token: str | None, timeout: float,
                          max_response_bytes: int = MAX_RESPONSE_BYTES) -> SubmitOutcome   # line 73 — never raises
def build_reply_card(outcome: SubmitOutcome, env: TeamsSubmitEnvelope) -> dict             # line 122
class RecentActivityCache: def seen(self, activity_id: str) -> bool                        # line 209 (marks + reports)

# renderers/teams.py
class TeamsSubmitEnvelope(BaseModel):                                # line 52
    form_uid: uuid.UUID; tenant: str; form_version: str; submit_url: HttpUrl; sig: str | None = None

# From TASK-4691 (formdesigner_mixin.py): _fd_identity, _fd_reader, _fd_send_card, _fd_send_turn_problem,
#   _fd_enabled, _fd_decorate_wizard, _fd_get_http, serve_form, self._fd_wizards (WizardStore),
#   self._fd_recent, self._fd_signing_secret, self._fd_allowed_hosts, self._fd_api_base_path,
#   self._fd_submit_timeout, self._fd_base_url, self._fd_public_url
# From TASK-4684: WizardStore.get/advance/finish/discard; WizardState.lock/consumed/answers/section_index/total_sections
# From TASK-4688: PICKER_ACTION_KEY, PICKER_GET_FORM, build_error_card

# parrot_formdesigner/core/schema.py: FormSection.fields: list[SectionItem] (279) — a SectionItem with a
#   `fields` attribute is a subsection; leaf items have `field_id`.
```

### Does NOT Exist
- ~~`verify_envelope(..., require_signature=...)`~~ — FEAT-733, NOT on dev. Do not pass it.
- ~~`resolve_submit_tenant()`~~ — FEAT-733, not on dev.
- ~~`extract_answers` stripping `_formdesigner_action`~~ — it does not; strip it yourself first.
- ~~Any use of `config.formdesigner_submit_token`~~ in the mixin — forbidden (AC: user bearer only).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-integrations/src/parrot/integrations/msteams/formdesigner_mixin.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-integrations/tests/msteams/test_formdesigner_serve.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/msteams/formdesigner_submit.py#verify_envelope",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/msteams/formdesigner_submit.py#parse_envelope",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/msteams/formdesigner_submit.py#extract_answers",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/msteams/formdesigner_submit.py#post_submission",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/msteams/formdesigner_submit.py#build_reply_card",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/msteams/formdesigner_submit.py#EnvelopeRejected",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/renderers/teams.py#TeamsSubmitEnvelope"
  ]
}
```

---

## Implementation Notes

- `_fd_allowed_hosts_for()`: configured `self._fd_allowed_hosts`, else the hostname of
  `self._fd_public_url` (local) / `self._fd_base_url` (remote) — the origin this mixin itself
  chose is trusted; an empty result refuses every submit.
- Next on the last section, Submit on a non-last section → reject (stale/forged).
- Every wizard step re-fetches the schema with `reader.get_form` — in local mode that
  re-runs membership (spec: "again for each wizard step") and gives the section field IDs.

---

## Implementation Blueprint

### Steps (in order)
1. `handle_formdesigner_card` router — *why*: the bool contract decides whether FEAT-551's fallback runs.
2. `_fd_submit` (shared by single-card and terminal wizard) — *why*: one signature/bearer path.
3. `_fd_wizard_action` — *why*: all state validation in one locked block.
4. Tests.

### `formdesigner_mixin.py` (MODIFY) — router + helpers
```python
# occurrences: 1 (verified after TASK-4691: grep -c '    async def aclose(self) -> None:' formdesigner_mixin.py)
# BEFORE — insert above `    async def aclose(self) -> None:` (inside TeamsFormDesignerMixin)
    async def handle_formdesigner_card(self, turn_context: TurnContext, submitted_data: dict[str, Any]) -> bool:
        """Route: picker -> serve form; wizard step -> next section; terminal envelope -> verify + post as the user.

        Returns True when fully handled; False lets the wrapper run its FEAT-551 branch.
        """
        control = submitted_data.get(PICKER_ACTION_KEY)
        if control == PICKER_GET_FORM:
            ref = submitted_data.get("form_uid")
            if not ref:
                await self._fd_send_card(build_error_card("Please choose a form."), turn_context)
            else:
                await self.serve_form(turn_context, form_ref=str(ref))
            return True
        if isinstance(control, dict) and control.get("kind") == "wizard":
            await self._fd_wizard_action(turn_context, submitted_data, control)
            return True
        if ENVELOPE_KEY in submitted_data and control is None:
            if not self._fd_enabled():
                return False
            turn = await self._fd_identity(turn_context)
            if await self._fd_send_turn_problem(turn, turn_context):
                return True
            activity_id = getattr(turn_context.activity, "id", None)
            if activity_id and self._fd_recent.seen(activity_id):
                return True
            answers = extract_answers({k: v for k, v in submitted_data.items() if k != PICKER_ACTION_KEY})
            await self._fd_submit(turn_context, turn, submitted_data, answers, state=None)
            return True
        return False

    def _fd_allowed_hosts_for(self) -> list[str]:
        if self._fd_allowed_hosts:
            return list(self._fd_allowed_hosts)
        origin = self._fd_public_url if self.formdesigner_mode == "local" else self._fd_base_url
        host = urlparse(origin).hostname if origin else None
        return [host.lower()] if host else []

    @staticmethod
    def _fd_section_field_ids(form: Any, index: int) -> set[str]:
        """Leaf field IDs of one section (subsections flattened)."""
        # FILL IN: walk form.sections[index].fields; items with `fields` recurse; else add item.field_id
        raise NotImplementedError
```

### `formdesigner_mixin.py` (MODIFY) — `_fd_submit` (append below the helpers)
```python
    async def _fd_submit(
        self, turn_context: TurnContext, turn: FormDesignerTurn, submitted_data: dict[str, Any],
        answers: dict[str, Any], *, state: WizardState | None,
    ) -> None:
        """Verify the signed envelope, then POST `answers` with the user's bearer. Never raises."""
        try:
            if not self._fd_signing_secret:
                raise EnvelopeRejected("no signing secret configured")
            env = parse_envelope(submitted_data)
            if not env.sig:
                raise EnvelopeRejected("unsigned envelope")
            verify_envelope(
                env, allowed_hosts=self._fd_allowed_hosts_for(), secret=self._fd_signing_secret,
                api_base_path=self._fd_api_base_path,
            )
            if env.tenant != turn.tenant:
                raise EnvelopeRejected("envelope tenant does not match the speaking user's tenant")
            # FILL IN: when state is not None — require env.form_uid == state.form_uid and
            #   env.form_version == state.form_version (else EnvelopeRejected); set state.consumed = True
            #   BEFORE the POST; answers = {**state.answers, **answers}
            outcome = await post_submission(
                await self._fd_get_http(), env, answers,
                bearer_token=turn.bearer, timeout=self._fd_submit_timeout,
            )
            self._fd_logger.info("formdesigner submit: form=%s status=%s", env.form_uid, outcome.status)
            await self._fd_send_card(build_reply_card(outcome, env), turn_context)
        except EnvelopeRejected as exc:
            self._fd_logger.warning("formdesigner submit rejected: %s", exc)  # reason stays in logs
            await self._fd_send_card(build_error_card("This form can't be submitted. Please request it again."), turn_context)
        except Exception:  # noqa: BLE001 — a Teams handler must never see an exception
            self._fd_logger.exception("formdesigner submit failed")
            await self._fd_send_card(build_error_card("Could not process your submission."), turn_context)
        finally:
            if state is not None:
                self._fd_wizards.finish(conversation_id=turn.conversation_id, form_uid=state.form_uid)
```
**Why**: `bearer_token=turn.bearer` is the only bearer this path can ever use (AC). `finish` in `finally` removes consumed state after the outcome is handled (spec: "remove it after the outcome is handled").

### `formdesigner_mixin.py` (MODIFY) — `_fd_wizard_action` (append below `_fd_submit`)
```python
    async def _fd_wizard_action(
        self, turn_context: TurnContext, submitted_data: dict[str, Any], control: dict[str, Any]
    ) -> None:
        """Validate a wizard control object against state, then Next / Cancel / terminal Submit."""
        turn = await self._fd_identity(turn_context)
        if await self._fd_send_turn_problem(turn, turn_context):
            return
        try:
            form_uid = uuid.UUID(str(control.get("form_uid")))
        except ValueError:
            await self._fd_send_card(build_error_card("This form step is not valid."), turn_context)
            return
        state = self._fd_wizards.get(conversation_id=turn.conversation_id, form_uid=form_uid)
        if state is None:
            await self._fd_send_card(build_error_card("This form expired. Send /getform to start again."), turn_context)
            return
        async with state.lock:
            action = control.get("action")
            # FILL IN: reject (error card, return) unless ALL hold: not state.consumed;
            #   control["wizard_id"] == str(state.wizard_id); control["section_index"] == state.section_index;
            #   state.owner_user_id == turn.user_id; state.tenant == turn.tenant; action in {"next","cancel","submit"};
            #   "next" only when section_index < total_sections - 1; "submit" only on the last section.
            # FILL IN: duplicate delivery — activity id seen in self._fd_recent -> return silently (inside the lock)
            if action == "cancel":
                self._fd_wizards.discard(conversation_id=turn.conversation_id, form_uid=form_uid)
                await self._fd_send_card(build_error_card("Form cancelled."), turn_context)
                return
            # FILL IN: reader = self._fd_reader(turn); form = await reader.get_form(tenant=turn.tenant,
            #   form_uid=form_uid, bearer_token=turn.bearer) (FormDesignerError -> error card + discard);
            #   (form.published_version or form.version) != state.form_version -> discard + "form changed" card
            raw = extract_answers({k: v for k, v in submitted_data.items() if k != PICKER_ACTION_KEY})
            allowed = self._fd_section_field_ids(form, state.section_index)
            answers = {k: v for k, v in raw.items() if k in allowed}
            if action == "submit":
                await self._fd_submit(turn_context, turn, submitted_data, answers, state=state)
                return
            self._fd_wizards.advance(state, answers)
            # FILL IN: rendered = await reader.render_teams(..., section_index=state.section_index);
            #   metadata section_index must equal state.section_index; card = append_render_warnings(
            #   self._fd_decorate_wizard(rendered.content, state), rendered.warnings); send it
```

### `tests/msteams/test_formdesigner_serve.py` (MODIFY — append)
```python
# Inbound half (TASK-4692). Reuse FDAgent / FakeStore / _ctx from the top of the module.
async def test_picker_submit_serves_form(): ...                       # FILL IN
async def test_single_card_submit_uses_user_bearer_not_service_token(): ...  # FILL IN: Authorization == "Bearer nav-tok"
async def test_unsigned_or_unsecured_envelope_refused(): ...          # FILL IN: no secret / no sig -> no POST
async def test_envelope_tenant_mismatch_refused(): ...                # FILL IN
async def test_duplicate_activity_not_double_posted(): ...            # FILL IN
async def test_wizard_walks_sections_then_submits(): ...              # FILL IN: 3 sections; only terminal posts; answers merged
async def test_wizard_rejects_stale_foreign_and_concurrent_actions(): ...  # FILL IN: wrong owner/tenant/wizard/index/version,
                                                                      #   expired, duplicate, asyncio.gather(next, next) -> one advance
async def test_wizard_control_object_never_reaches_post(): ...        # FILL IN
async def test_wizard_cancel_removes_state_without_post(): ...        # FILL IN
async def test_mixin_declines_when_not_configured(): ...              # FILL IN: returns False -> wrapper fallback
```
Use a fake `post_submission` via `monkeypatch.setattr("parrot.integrations.msteams.formdesigner_mixin.post_submission", fake)` to capture `bearer_token` and `answers`.

### FILL IN checklist
- [ ] `_fd_section_field_ids`
- [ ] `_fd_submit` wizard-state checks
- [ ] `_fd_wizard_action` validation, dedupe, schema re-fetch, next-section render
- [ ] ten test bodies

---

## Acceptance Criteria

- [ ] Every POST carries the session's `nav_session_token`; `formdesigner_submit_token` appears nowhere in the mixin.
- [ ] No secret / unsigned envelope / wrong tenant → refused, no POST, no reason shown to the user.
- [ ] Wizard: only the terminal Submit posts; earlier answers included; control object never posted.
- [ ] Stale, foreign, expired, duplicate and concurrent actions never advance twice or post partial data.
- [ ] All recognized wizard actions return `True`; unconfigured mixin returns `False` for a bare envelope.
- [ ] `ruff check` clean.

## Validation Commands

- `pytest packages/ai-parrot-integrations/tests/msteams/test_formdesigner_serve.py -q`


---

## Test Specification

Ten appended tests in the blueprint (spec §4: `test_picker_submit_serves_form`,
`test_wizard_walks_sections_then_submits`, `test_submit_uses_user_bearer_not_service_token`,
`test_duplicate_activity_not_double_posted`, `test_wizard_rejects_stale_foreign_and_concurrent_actions`,
`test_mixin_declines_unknown_envelope_falls_back` at the handler level).

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug formdesigner-serve-forms --feature-id FEAT-734`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in
   `sdd/tasks/index/formdesigner-serve-forms.json`
4. **Verify the Codebase Contract** — confirm every import/signature before writing code; never use anything under "Does NOT Exist"
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every `# FILL IN:` marker, never change a fixed signature or path
7. **Verify** — run the Validation Commands with
   `PYTHONPATH=packages/ai-parrot-integrations/src:packages/ai-parrot/src:packages/parrot-formdesigner/src`
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4692 formdesigner-serve-forms verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
