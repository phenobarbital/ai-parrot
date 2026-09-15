"""FEAT-551 round-trip: render `teams` card -> Teams-like activity.value -> verify -> POST .../data.

The aiohttp test server is http://, while the envelope (and S3) require https://. We therefore
verify the envelope AS RENDERED (https://forms.test) and POST to a copy whose submit_url is
rewritten to the test server — see "Does NOT Exist" in TASK-3152.

Routes are hand-wired directly to ``handle_render``/``FormAPIHandler.submit_data`` (bypassing
navigator-auth's ``is_authenticated``/``user_session`` decorators that ``setup_form_api()``
normally applies), mirroring the established precedent in
``packages/parrot-formdesigner/tests/unit/api/test_render_dispatcher.py`` and
``packages/parrot-formdesigner/tests/integration/test_render_xml.py`` — those tests exercise
the dispatcher/handler logic itself, not navigator-auth's session backend, which is not
configured in this unit-test environment (`setup_form_api()`-mounted routes 400 with
"Authentication Backend is not enabled" without one).

No botbuilder import here: these tests exercise the FormDesigner routes and the botbuilder-free
``formdesigner_submit`` helpers directly, never the wrapper.
"""
import pytest
from aiohttp import web
from parrot_formdesigner.api.handlers import FormAPIHandler
from parrot_formdesigner.api.render import _RENDERERS, handle_render, register_teams_renderer
from parrot_formdesigner.core import FormSchema, FormSection
from parrot_formdesigner.core.schema import FormField
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.renderers.teams import ENVELOPE_KEY, TeamsSubmitEnvelope
from parrot_formdesigner.services.registry import FormRegistry

from parrot.integrations.msteams.formdesigner_submit import (
    build_reply_card,
    extract_answers,
    post_submission,
    verify_envelope,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _reset_renderers():
    """Isolate the module-global renderer registry between tests (test_render_dispatcher.py precedent)."""
    snapshot = dict(_RENDERERS)
    _RENDERERS.clear()
    yield
    _RENDERERS.clear()
    _RENDERERS.update(snapshot)


async def _tenant_wrapped_render(request: web.Request) -> web.Response:
    """Stash the URL-declared tenant, mirroring what @requires_tenant does (no auth backend needed)."""
    request["tenant"] = request.match_info["tenant"]
    return await handle_render(request)


def _tenant_wrapped_submit(handler: FormAPIHandler):
    async def _submit(request: web.Request) -> web.Response:
        request["tenant"] = request.match_info["tenant"]
        return await handler.submit_data(request)

    return _submit


@pytest.fixture
def public_form() -> FormSchema:
    """A public, tenant-scoped form with one required TEXT field and one BOOLEAN field."""
    return FormSchema(
        form_id="teams-rt",
        title="Teams Round-Trip Form",
        tenant="navigator",
        is_public=True,
        sections=[
            FormSection(
                section_id="main",
                title="Main",
                fields=[
                    FormField(field_id="name", field_type=FieldType.TEXT, label="Name", required=True),
                    FormField(field_id="ok", field_type=FieldType.BOOLEAN, label="OK", required=False),
                ],
            )
        ],
    )


def _build_app(registry: FormRegistry) -> web.Application:
    register_teams_renderer(public_base_url="https://forms.test")
    handler = FormAPIHandler(registry)
    app = web.Application()
    app["form_registry"] = registry
    app.router.add_get("/api/v1/{tenant}/forms/{form_uid}/render/{format}", _tenant_wrapped_render)
    app.router.add_post("/api/v1/{tenant}/forms/{form_uid}/data", _tenant_wrapped_submit(handler))
    return app


@pytest.fixture
async def app_client(aiohttp_client, public_form):
    registry = FormRegistry()
    await registry.register(public_form)
    return await aiohttp_client(_build_app(registry))


async def test_teams_card_roundtrip_public_form(app_client, public_form):
    resp = await app_client.get(f"/api/v1/navigator/forms/{public_form.form_uid}/render/teams?with_meta=true")
    assert resp.status == 200
    meta = await resp.json()
    submit = next(a for a in meta["content"]["actions"] if a["data"].get("_action") == "submit")
    env = TeamsSubmitEnvelope.model_validate(submit["data"][ENVELOPE_KEY])
    verify_envelope(env, allowed_hosts=["forms.test"], secret=None)  # S3 passes on the rendered https URL

    # What Teams would put in activity.value: the card's control keys plus the user's answers.
    value = {**submit["data"], "name": "Ada", "ok": "true"}
    local = env.model_copy(
        update={
            "submit_url": str(app_client.make_url(f"/api/v1/navigator/forms/{public_form.form_uid}/data")),
        }
    )
    outcome = await post_submission(app_client.session, local, extract_answers(value), bearer_token=None, timeout=5.0)
    assert outcome.status == 200
    assert outcome.body["is_valid"] is True
    assert outcome.body["submission_id"]
    assert build_reply_card(outcome, env)["type"] == "AdaptiveCard"


async def test_teams_card_validation_errors_422(app_client, public_form):
    resp = await app_client.get(f"/api/v1/navigator/forms/{public_form.form_uid}/render/teams?with_meta=true")
    meta = await resp.json()
    submit = next(a for a in meta["content"]["actions"] if a["data"].get("_action") == "submit")
    env = TeamsSubmitEnvelope.model_validate(submit["data"][ENVELOPE_KEY])

    # Omit the required "name" field.
    value = {**submit["data"], "ok": "true"}
    local = env.model_copy(
        update={
            "submit_url": str(app_client.make_url(f"/api/v1/navigator/forms/{public_form.form_uid}/data")),
        }
    )
    outcome = await post_submission(app_client.session, local, extract_answers(value), bearer_token=None, timeout=5.0)
    assert outcome.status == 422
    assert outcome.body["is_valid"] is False
    assert "name" in outcome.body["errors"]
    reply_body = build_reply_card(outcome, env)["body"]
    assert any("name" in block.get("text", "") for block in reply_body)


async def test_teams_card_private_form_403(aiohttp_client, public_form):
    """A private form's submit route requires tenant membership (spec §7 "Private forms").

    No navigator-auth session is attached to the hand-wired request (``getattr(request,
    "session", None)`` is ``None``), so ``enforce_membership_unless_public``'s default-deny
    path applies directly — no token_validator scaffolding needed. Posting straight to the
    route (rather than through ``post_submission``) is sufficient since the membership check
    runs before body parsing/validation.
    """
    private_form = public_form.model_copy(update={"is_public": False})
    registry = FormRegistry()
    await registry.register(private_form)
    client = await aiohttp_client(_build_app(registry))

    resp = await client.post(
        f"/api/v1/navigator/forms/{private_form.form_uid}/data",
        json={"name": "Ada", "ok": "true"},
    )
    assert resp.status == 403
