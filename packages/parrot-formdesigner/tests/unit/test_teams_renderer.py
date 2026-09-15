"""Unit tests for TeamsFormRenderer / TeamsSubmitEnvelope (FEAT-551 TASK-3147)."""
import json
import pytest
from parrot_formdesigner.core import FormSchema, FormSection          # verified: test_renderers.py:4
from parrot_formdesigner.core.schema import FormField                 # verified: test_renderers.py:5
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.renderers import AdaptiveCardRenderer, TeamsFormRenderer, TeamsSubmitEnvelope
from parrot_formdesigner.renderers.teams import ENVELOPE_KEY, TeamsRenderConfigError

pytestmark = pytest.mark.asyncio


@pytest.fixture
def form() -> FormSchema:
    return FormSchema(
        form_id="teams-demo",
        title="Teams Demo Form",
        tenant="navigator",
        is_public=True,
        sections=[
            FormSection(
                section_id="main",
                title="Main Section",
                fields=[
                    FormField(
                        field_id="name",
                        field_type=FieldType.TEXT,
                        label="Full Name",
                        required=True
                    ),
                    FormField(
                        field_id="newsletter",
                        field_type=FieldType.BOOLEAN,
                        label="Subscribe to newsletter",
                        required=False
                    )
                ]
            )
        ]
    )


@pytest.fixture
def renderer() -> TeamsFormRenderer:
    return TeamsFormRenderer("https://forms.test/", api_base_path="/api/v1", ui_base_path="", signing_secret="s3cr3t")


async def test_teams_envelope_shape(renderer, form):
    result = await renderer.render(form, tenant="navigator")
    # `form.cancel_allowed` defaults to True, so `_build_form_actions` appends a Cancel
    # action after Submit — locate Submit by its `_action` literal, not by position.
    submit = next(a for a in result.content["actions"] if a["data"].get("_action") == "submit")
    assert submit["type"] == "Action.Submit" and submit["data"]["_action"] == "submit"
    env = TeamsSubmitEnvelope.model_validate(submit["data"][ENVELOPE_KEY])
    assert str(env.submit_url) == f"https://forms.test/api/v1/navigator/forms/{form.form_uid}/data"
    assert str(env.form_url) == f"https://forms.test/navigator/forms/{form.form_uid}"
    assert env.form_version == form.version and env.is_public is True and env.sig
    assert result.metadata["channel"] == "msteams" and result.metadata["envelope_version"] == 1


async def test_teams_envelope_sign_verify_roundtrip(renderer, form):
    env = renderer.build_envelope(form, "navigator")
    assert env.verify("s3cr3t") and not env.verify("other")
    assert not env.model_copy(update={"sig": None}).verify("s3cr3t")
    assert not env.model_copy(update={"tenant": "evil"}).verify("s3cr3t")


async def test_teams_render_requires_tenant_and_base_url(form, monkeypatch):
    # Test that TeamsFormRenderer raises TeamsRenderConfigError when no tenant is provided.
    # `form` (fixture) already carries tenant="navigator", so a tenant-less copy is required
    # to genuinely exercise the "no tenant" branch of render().
    form_without_tenant = form.model_copy(update={"tenant": None})
    with pytest.raises(TeamsRenderConfigError):
        await TeamsFormRenderer("https://x").render(form_without_tenant)

    # Test that TeamsFormRenderer raises TeamsRenderConfigError when no public base URL is configured
    monkeypatch.delenv("FORMDESIGNER_PUBLIC_URL", raising=False)
    with pytest.raises(TeamsRenderConfigError):
        await TeamsFormRenderer().render(form, tenant="t")


async def test_adaptive_unaffected(form):
    result = await AdaptiveCardRenderer().render(form)
    submit = next(a for a in result.content["actions"] if a["data"].get("_action") == "submit")
    assert submit["data"] == {"_action": "submit"} and result.metadata is None


async def test_teams_wizard_last_step_only_has_envelope(form):
    renderer = TeamsFormRenderer("https://forms.test/")
    # `form` (fixture) is single-section, so its only index is always the last step — a
    # multi-section form is required to exercise a genuine non-last step with a Next action.
    multi_section_form = FormSchema(
        form_id="wizard-demo",
        title="Wizard Demo Form",
        tenant="navigator",
        is_public=True,
        sections=[
            FormSection(
                section_id="step1",
                title="Step 1",
                fields=[
                    FormField(
                        field_id="field1",
                        field_type=FieldType.TEXT,
                        label="Field 1"
                    )
                ]
            ),
            FormSection(
                section_id="step2",
                title="Step 2",
                fields=[
                    FormField(
                        field_id="field2",
                        field_type=FieldType.TEXT,
                        label="Field 2"
                    )
                ]
            )
        ]
    )
    
    # First step - should not have envelope
    result = await renderer.render_section(multi_section_form, 0, show_back=True, show_skip=False)
    submit_actions = [action for action in result.content["actions"] if action["type"] == "Action.Submit"]
    next_action = next((action for action in submit_actions if action["data"]["_action"] == "next"), None)
    assert next_action is not None
    assert ENVELOPE_KEY not in next_action["data"]
    
    # Last step - should have envelope
    result = await renderer.render_section(multi_section_form, 1, show_back=True, show_skip=False)
    submit_actions = [action for action in result.content["actions"] if action["type"] == "Action.Submit"]
    submit_action = next((action for action in submit_actions if action["data"]["_action"] == "submit"), None)
    assert submit_action is not None
    assert ENVELOPE_KEY in submit_action["data"]