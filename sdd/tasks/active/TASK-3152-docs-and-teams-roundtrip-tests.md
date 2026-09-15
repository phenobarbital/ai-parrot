# TASK-3152: Documentation + end-to-end round-trip tests (render `teams` → bot forward → `POST …/data`)

**Feature**: FEAT-551 — MS Teams FormDesigner Renderer (Adaptive Card + submit envelope via the Teams bot)
**Spec**: `sdd/specs/msteams-formdesigner-renderer.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3148, TASK-3149, TASK-3151
**Assigned-to**: unassigned
**Parallel**: false — closes the feature; needs every module landed.

---

## Context

Spec §3 Module 5 and §4 Integration Tests. Proves the whole cycle with real FormDesigner routes
and the botbuilder-free helpers: `setup_form_api(public_base_url=…)` → `GET …/render/teams?with_meta=true`
→ take the card's `_formdesigner` envelope + inputs as a Teams `activity.value` → `verify_envelope`
+ `post_submission` against the SAME aiohttp test app → 200 / 422 / 403. Then documents the
contract for operators.

---

## Scope

- `docs/formdesigner-msteams-renderer.md` (new) with the sections listed in spec §3 M5; one-paragraph pointer section in `docs/msteams.md` before `## Troubleshooting`.
- Round-trip tests in `packages/ai-parrot-integrations/tests/msteams/test_formdesigner_roundtrip.py` (no botbuilder needed — uses the helpers, not the wrapper).

**NOT in scope**: new behaviour; Redis dedupe; attachment intake.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/formdesigner-msteams-renderer.md` | CREATE | operator + developer guide |
| `docs/msteams.md` | MODIFY | pointer section |
| `packages/ai-parrot-integrations/tests/msteams/test_formdesigner_roundtrip.py` | CREATE | integration tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from aiohttp import web
from parrot_formdesigner.api.routes import setup_form_api                         # routes.py:191 (kwargs public_base_url/teams_renderer from TASK-3149)
from parrot_formdesigner.services.registry import FormRegistry                    # registry.py:240 ; async def register(...) :466 ; async def get(form_uid, *, tenant=None) :976
from parrot_formdesigner.renderers.teams import ENVELOPE_KEY, TeamsSubmitEnvelope  # TASK-3147
from parrot.integrations.msteams.formdesigner_submit import extract_answers, post_submission, verify_envelope, build_reply_card   # TASK-3150
# fixtures precedent: packages/parrot-formdesigner/tests/unit/api/test_render_dispatcher.py:28-62 (_tenant_wrapped_render, sample_form)
```

### Existing Signatures to Use
```python
# parrot_formdesigner routes (unchanged)
GET  {bp}/{tenant}/forms/{form_uid}/render/{format}     # routes.py:388-392 (mounted tenant="public"; private forms enforce membership)
POST {bp}/{tenant}/forms/{form_uid}/data                # routes.py:398-401 -> handlers.py:1464 submit_data
# submit_data responses: 200 {"submission_id", "is_valid": True, "forwarded", "forward_status", "forward_error"} | 422 {"is_valid": False, "errors": {...}} | 403 private
# handle_render (TASK-3149): ?with_meta=true -> {"content", "content_type", "warnings", "metadata"}
# docs/msteams.md headings: "## Integration with AI-Parrot" :349 ; "## Troubleshooting" :397 ; "## Resources" :425
```

### Does NOT Exist
- ~~`docs/formdesigner-msteams-renderer.md`~~ — created by THIS task.
- ~~a `tests/integration/` dir in ai-parrot-integrations~~ — put the round-trip under `tests/msteams/` (existing dir).
- ~~https in the aiohttp test server~~ — the test app is plain http, so `verify_envelope` cannot pass on the real test URL. In the round-trip: (a) assert `verify_envelope` PASSES on the rendered https envelope with `allowed_hosts=["forms.test"]` (renderer configured with `public_base_url="https://forms.test"`), then (b) POST with `post_submission` to a copy of the envelope whose `submit_url` is rewritten to the test server's http URL (`env.model_copy(update={"submit_url": ...})`). Document this split in the test docstring.
- ~~navigator-auth session scaffolding~~ — the public-form path needs none; the private-form 403 test relies on how `setup_form_api` wires `_wrap_auth` — if that requires a `token_validator`, SKIP the bearer-success variant with a clear reason and keep the 403 assertion only.

---

## Implementation Notes

### Pattern to Follow
- `test_render_dispatcher.py:175-212` for building an app around `FormRegistry`; here use `setup_form_api(app, registry, public_base_url="https://forms.test")` so the real routes and the `teams` registration are exercised.

### Key Constraints
- Docs must include: envelope JSON example; `FORMDESIGNER_PUBLIC_URL` / `setup_form_api(public_base_url=…)`; bot config fields (`formdesigner_allowed_hosts`, `_submit_token`, `_submit_secret`, `_submit_timeout`) and their env names; Teams limitations (no uploads — quote Microsoft; v1.6 ceiling; styling ignored); security model (allowlist, sig, bearer); duplicate-submission caveat; walkthrough.

---

## Implementation Blueprint

### Steps (in order)
1. Write the round-trip tests first — *why*: they are the feature's acceptance evidence (spec §4 Integration Tests).
2. Write the guide; add the pointer section to `docs/msteams.md` — *why*: spec M5 AC.

### `packages/ai-parrot-integrations/tests/msteams/test_formdesigner_roundtrip.py` (CREATE)
```python
"""FEAT-551 round-trip: render `teams` card -> Teams-like activity.value -> verify -> POST .../data.

The aiohttp test server is http://, while the envelope (and S3) require https://. We therefore
verify the envelope AS RENDERED (https://forms.test) and POST to a copy whose submit_url is
rewritten to the test server — see "Does NOT Exist" in the task.
"""
import pytest
from aiohttp import web
from parrot_formdesigner.api.routes import setup_form_api
from parrot_formdesigner.services.registry import FormRegistry
from parrot_formdesigner.renderers.teams import ENVELOPE_KEY, TeamsSubmitEnvelope
from parrot.integrations.msteams.formdesigner_submit import build_reply_card, extract_answers, post_submission, verify_envelope

pytestmark = pytest.mark.asyncio


@pytest.fixture
def public_form():
    # FILL IN: FormSchema(form_id="teams-rt", tenant="navigator", is_public=True, sections=[one section with TEXT "name" (required) + BOOLEAN "ok"]) — bounded by schema.py:453-471
    raise NotImplementedError


@pytest.fixture
async def app_client(aiohttp_client, public_form):
    registry = FormRegistry()
    await registry.register(public_form)
    app = web.Application()
    setup_form_api(app, registry, public_base_url="https://forms.test")
    return await aiohttp_client(app)


async def test_teams_card_roundtrip_public_form(app_client, public_form):
    resp = await app_client.get(f"/api/v1/navigator/forms/{public_form.form_uid}/render/teams?with_meta=true")
    assert resp.status == 200
    meta = await resp.json()
    submit = meta["content"]["actions"][-1]
    env = TeamsSubmitEnvelope.model_validate(submit["data"][ENVELOPE_KEY])
    verify_envelope(env, allowed_hosts=["forms.test"], secret=None)           # S3 passes on the rendered https URL
    value = {**submit["data"], "name": "Ada", "ok": "true"}                     # what Teams would put in activity.value
    local = env.model_copy(update={"submit_url": str(app_client.make_url(f"/api/v1/navigator/forms/{public_form.form_uid}/data"))})
    outcome = await post_submission(app_client.session, local, extract_answers(value), bearer_token=None, timeout=5.0)
    assert outcome.status == 200 and outcome.body["is_valid"] is True and outcome.body["submission_id"]
    assert "AdaptiveCard" == build_reply_card(outcome, env)["type"]


async def test_teams_card_validation_errors_422(app_client, public_form):
    # FILL IN: same flow with value missing required "name" -> outcome.status == 422 and "name" in outcome.body["errors"];
    #   build_reply_card text mentions "name" — bounded by spec §4
    raise NotImplementedError


async def test_teams_card_private_form_403(aiohttp_client, public_form):
    # FILL IN: register a copy with is_public=False; POST via post_submission without token -> 403 (or document skip if
    #   _wrap_auth needs a token_validator to even reach enforce_membership_unless_public) — bounded by spec §4 / §7 "Private forms"
    raise NotImplementedError
```
**Why**: exercises real routes + real helpers end-to-end without botbuilder; the https/http split keeps S3 honest.

### `docs/formdesigner-msteams-renderer.md` (CREATE)
```markdown
# FormDesigner → MS Teams: Adaptive Card renderer and bot submit path (FEAT-551)

## What it does            <!-- renderer returns JSON; bot forwards; diagram from spec §2 -->
## Rendering a form         <!-- GET …/render/teams[?with_meta=true]; FORMDESIGNER_PUBLIC_URL / setup_form_api(public_base_url=…, teams_renderer=…) -->
## The `_formdesigner` envelope   <!-- JSON example from spec §2; fields; `sig` (HMAC-SHA256 over canonical JSON) -->
## Bot configuration        <!-- formdesigner_allowed_hosts / _submit_token / _submit_secret / _submit_timeout + {NAME}_FORMDESIGNER_* env -->
## Security model           <!-- https only, allowlist, path/tenant/uid check, optional sig, bearer for private forms, no redirects -->
## Teams limitations        <!-- "Adaptive Cards within Teams don't provide support for file or image uploads" (Microsoft); v1.6; styling ignored; upload fields -> web form link -->
## Duplicate submissions    <!-- best-effort activity.id dedupe; server-side idempotency is a follow-up -->
## Walkthrough              <!-- render → post card (caller) → user submits → bot POSTs → confirmation card -->
## Troubleshooting          <!-- 415 teams not registered; 400 no tenant/base URL; "not enabled" allowlist; 403 private -->
```
**Why**: sections fixed by spec §3 M5; fill each with 1–3 short paragraphs and the JSON/config snippets. (Section headings are the contract; `<!-- -->` notes are what to write.)

### `docs/msteams.md` (MODIFY)
```markdown
<!-- occurrences: 1 (verified: grep -c '^## Troubleshooting' docs/msteams.md) -->
<!-- BEFORE — insert above `## Troubleshooting` (verified: docs/msteams.md:397) -->
## FormDesigner forms in Teams (FEAT-551)

FormDesigner can export any form as an MS Teams Adaptive Card (`GET …/forms/{form_uid}/render/teams`).
The bot receives the card's Submit, verifies the `_formdesigner` envelope and forwards the answers to
`POST …/forms/{form_uid}/data`. Configure `formdesigner_allowed_hosts` (and optionally
`formdesigner_submit_token` / `formdesigner_submit_secret`) on the bot. Full guide:
[docs/formdesigner-msteams-renderer.md](formdesigner-msteams-renderer.md).
```
**Why**: keeps the existing Teams doc as the entry point (spec M5 AC "docs/msteams.md links to it").

### FILL IN checklist
- [ ] `public_form` fixture; 422 and 403 tests — bounded by spec §4 Integration Tests.
- [ ] Guide body per section notes — bounded by spec §3 M5 "Responsibility".

---

## Acceptance Criteria

- [ ] `pytest packages/ai-parrot-integrations/tests/msteams/test_formdesigner_roundtrip.py -v` passes (no botbuilder needed)
- [ ] `docs/formdesigner-msteams-renderer.md` exists with all nine sections; `docs/msteams.md` links to it
- [ ] Guide quotes the Microsoft limitation and documents the four bot config fields + env names
- [ ] Full suites green: `pytest packages/parrot-formdesigner/tests/unit -q` and `pytest packages/ai-parrot-integrations/tests/msteams -q`

---

## Test Specification

See blueprint.

---

## Agent Instructions

1. Read spec §2, §4, §7.
2. Check TASK-3148, TASK-3149, TASK-3151 are in `sdd/tasks/completed/`.
3. Verify anchors (`grep -n "^## Troubleshooting" docs/msteams.md`).
4. Update index status → `"in-progress"`.
5. Implement from the blueprint; complete every `# FILL IN:`.
6. Verify acceptance criteria.
7. Move this file to `sdd/tasks/completed/TASK-3152-docs-and-teams-roundtrip-tests.md`; index → `"done"`; Completion Note.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
