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

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import web
from parrot_formdesigner.api.handlers import FormAPIHandler
from parrot_formdesigner.api.render import _RENDERERS, handle_render, register_teams_renderer
from parrot_formdesigner.core import FormSchema, FormSection
from parrot_formdesigner.core.schema import FormField
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.renderers.teams import ENVELOPE_KEY, TeamsFormRenderer, TeamsSubmitEnvelope
from parrot_formdesigner.services.registry import FormRegistry

from parrot.integrations.msteams import wrapper as wrapper_mod
from parrot.integrations.msteams.formdesigner_submit import (
    SubmitOutcome,
    build_reply_card,
    extract_answers,
    post_submission,
    verify_envelope,
)
from parrot.integrations.msteams.wrapper import MSTeamsAgentWrapper

pytestmark = pytest.mark.asyncio

SIGNING_SECRET = "test-secret-not-a-real-key"


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


def _security_wrapper(*, secret: str | None, submit_token: str | None = None) -> MSTeamsAgentWrapper:
    """Build the minimal wrapper required to exercise the submit branch without a Bot Framework connection."""
    wrapper = MSTeamsAgentWrapper.__new__(MSTeamsAgentWrapper)
    wrapper.config = SimpleNamespace(
        formdesigner_allowed_hosts=["forms.test"],
        formdesigner_submit_token=submit_token,
        formdesigner_submit_secret=secret,
        formdesigner_submit_timeout=5.0,
        formdesigner_allow_unsigned_submissions=False,
        formdesigner_tenant_map=None,
        formdesigner_api_base_path="/api/v1",
    )
    wrapper.logger = MagicMock()
    wrapper.send_text = AsyncMock()
    wrapper.send_card = AsyncMock()
    wrapper._formdesigner_session = None
    wrapper._formdesigner_recent = wrapper_mod.RecentActivityCache()
    return wrapper


def _security_context(value: dict, activity_id: str, *, aad_tenant: str | None = None) -> MagicMock:
    """Build a Teams-like activity with dict-shaped channel data, as Bot Framework supplies it."""
    context = MagicMock()
    context.activity.value = value
    context.activity.id = activity_id
    context.activity.channel_data = {"tenant": {"id": aad_tenant}} if aad_tenant else {}
    return context


def _submission_data(envelope: TeamsSubmitEnvelope) -> dict:
    """Build the Action.Submit payload delivered by Teams for a rendered card."""
    return {"_action": "submit", ENVELOPE_KEY: envelope.model_dump(mode="json"), "name": "Ada", "ok": "true"}


@pytest.fixture
def signed_envelope(public_form: FormSchema) -> TeamsSubmitEnvelope:
    """A valid envelope for tenant ``navigator``, signed by the renderer's configured secret."""
    renderer = TeamsFormRenderer(public_base_url="https://forms.test", signing_secret=SIGNING_SECRET)
    return renderer.build_envelope(public_form, "navigator")


@pytest.fixture
def cross_tenant_envelope(public_form: FormSchema) -> TeamsSubmitEnvelope:
    """The unsigned, self-consistent attack envelope for the ``victim`` tenant."""
    renderer = TeamsFormRenderer(public_base_url="https://forms.test")
    return renderer.build_envelope(public_form, "victim")


class TestSubmitSecurityRoundtrip:
    """FEAT-733 — verify the whole Teams submit branch before its outbound POST seam."""

    async def test_cross_tenant_envelope_is_refused(self, cross_tenant_envelope: TeamsSubmitEnvelope) -> None:
        """A signed-mode bot refuses the self-consistent unsigned cross-tenant envelope before POSTing."""
        # This models the pre-fix unsafe mode: it accepts the same path/tenant-consistent envelope.
        verify_envelope(cross_tenant_envelope, allowed_hosts=["forms.test"], secret=None, require_signature=False)
        wrapper = _security_wrapper(secret=SIGNING_SECRET)
        value = _submission_data(cross_tenant_envelope)

        with patch.object(wrapper_mod, "post_submission", new_callable=AsyncMock) as post:
            await wrapper._handle_formdesigner_submit(_security_context(value, "cross-tenant-refusal"), value)

        post.assert_not_awaited()
        wrapper.send_text.assert_awaited_once()
        assert "signature is invalid" in wrapper.send_text.await_args.args[0]

    async def test_teams_card_roundtrip_signed(self, signed_envelope: TeamsSubmitEnvelope) -> None:
        """A renderer-signed card is verified, forwarded, and acknowledged with its submission id."""
        wrapper = _security_wrapper(secret=SIGNING_SECRET)
        value = _submission_data(signed_envelope)
        with (
            patch.object(wrapper_mod, "post_submission", new_callable=AsyncMock) as post,
            patch.object(wrapper, "_get_formdesigner_session", new_callable=AsyncMock),
        ):
            post.return_value = SubmitOutcome(status=200, body={"submission_id": "signed-submission"})
            await wrapper._handle_formdesigner_submit(_security_context(value, "signed-roundtrip"), value)

        assert post.await_args.args[1] == signed_envelope
        reply = wrapper.send_card.await_args.args[0]
        assert "Thank you!" in reply["body"][0]["text"]
        assert "signed-submission" in reply["body"][0]["text"]

    async def test_teams_card_roundtrip_private_form_403_then_bearer(
        self, signed_envelope: TeamsSubmitEnvelope
    ) -> None:
        """A private submission maps 403 to a permission card, then succeeds when the bearer is configured."""
        wrapper = _security_wrapper(secret=SIGNING_SECRET)
        value = _submission_data(signed_envelope)
        with (
            patch.object(wrapper_mod, "post_submission", new_callable=AsyncMock) as post,
            patch.object(wrapper, "_get_formdesigner_session", new_callable=AsyncMock),
        ):
            post.side_effect = [
                SubmitOutcome(status=403),
                SubmitOutcome(status=200, body={"submission_id": "private-submission"}),
            ]
            await wrapper._handle_formdesigner_submit(_security_context(value, "private-form-403"), value)
            wrapper.config.formdesigner_submit_token = "accepted-bearer"
            await wrapper._handle_formdesigner_submit(_security_context(value, "private-form-bearer"), value)

        assert post.await_args_list[0].kwargs["bearer_token"] is None
        assert post.await_args_list[1].kwargs["bearer_token"] == "accepted-bearer"
        assert "permission" in wrapper.send_card.await_args_list[0].args[0]["body"][0]["text"].lower()
        assert "private-submission" in wrapper.send_card.await_args_list[1].args[0]["body"][0]["text"]

    async def test_unsigned_renderer_against_signed_bot_is_refused(self, public_form: FormSchema) -> None:
        """A renderer without the paired signing secret cannot silently submit to a signed-mode bot."""
        unsigned_envelope = TeamsFormRenderer(public_base_url="https://forms.test").build_envelope(
            public_form, "navigator"
        )
        wrapper = _security_wrapper(secret=SIGNING_SECRET)
        value = _submission_data(unsigned_envelope)
        with patch.object(wrapper_mod, "post_submission", new_callable=AsyncMock) as post:
            await wrapper._handle_formdesigner_submit(_security_context(value, "unsigned-renderer"), value)

        post.assert_not_awaited()
        assert "signature is invalid" in wrapper.send_text.await_args.args[0]

    async def test_mapped_tenant_overrides_validly_signed_cross_tenant_claim(
        self, cross_tenant_envelope: TeamsSubmitEnvelope
    ) -> None:
        """A Bot Framework asserted tenant mapping wins over a valid signed card claim."""
        wrapper = _security_wrapper(secret=SIGNING_SECRET)
        wrapper.config.formdesigner_tenant_map = {"aad-navigator": "navigator"}
        value = _submission_data(cross_tenant_envelope.sign(SIGNING_SECRET))
        with (
            patch.object(wrapper_mod, "post_submission", new_callable=AsyncMock) as post,
            patch.object(wrapper, "_get_formdesigner_session", new_callable=AsyncMock),
        ):
            post.return_value = SubmitOutcome(status=200, body={"submission_id": "mapped-submission"})
            await wrapper._handle_formdesigner_submit(
                _security_context(value, "mapped-tenant", aad_tenant="aad-navigator"), value
            )

        forwarded_envelope = post.await_args.args[1]
        assert forwarded_envelope.tenant == "navigator"
        assert f"/api/v1/navigator/forms/{forwarded_envelope.form_uid}/data" in str(forwarded_envelope.submit_url)

    async def test_derivation_runs_after_verification(self, cross_tenant_envelope: TeamsSubmitEnvelope) -> None:
        """An invalid signature cannot reach tenant derivation or the outbound POST."""
        wrapper = _security_wrapper(secret=SIGNING_SECRET)
        wrapper.config.formdesigner_tenant_map = {"aad-navigator": "navigator"}
        value = _submission_data(cross_tenant_envelope)
        with (
            patch.object(wrapper_mod, "resolve_submit_tenant") as resolve_tenant,
            patch.object(wrapper_mod, "post_submission", new_callable=AsyncMock) as post,
        ):
            await wrapper._handle_formdesigner_submit(
                _security_context(value, "verification-before-derivation", aad_tenant="aad-navigator"), value
            )

        resolve_tenant.assert_not_called()
        post.assert_not_awaited()
