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
    submit = result.content["actions"][-1]
    assert submit["type"] == "Action.Submit" and submit["data"]["_action"] == "submit"
    env = TeamsSubmitEnvelope.model_validate(submit["data"][ENVELOPE_KEY])
    assert str(env.submit_url) == f"https://forms.test/api/v1/navigator/forms/{form.form_uid}/data"
    assert str(env.form_url) == f"https://forms.test/navigator/forms/{form.form_uid}"
    assert env.form_version == form.version and env.is_public is True and env.sig
    assert result.metadata["channel"] == "msteams" and result.metadata["envelope_version"] == 1


def test_teams_envelope_sign_verify_roundtrip(renderer, form):
    env = renderer.build_envelope(form, "navigator")
    assert env.verify("s3cr3t") and not env.verify("other")
    assert not env.model_copy(update={"sig": None}).verify("s3cr3t")
    assert not env.model_copy(update={"tenant": "evil"}).verify("s3cr3t")


async def test_teams_render_requires_tenant_and_base_url(form, monkeypatch):
    # Test that TeamsFormRenderer raises TeamsRenderConfigError when no tenant is provided
    with pytest.raises(TeamsRenderConfigError):
        await TeamsFormRenderer("https://x").render(form)
    
    # Test that TeamsFormRenderer raises TeamsRenderConfigError when no public base URL is configured
    monkeypatch.delenv("FORMDESIGNER_PUBLIC_URL", raising=False)
    with pytest.raises(TeamsRenderConfigError):
        await TeamsFormRenderer().render(form, tenant="t")


async def test_adaptive_unaffected(form):
    result = await AdaptiveCardRenderer().render(form)
    assert result.content["actions"][-1]["data"] == {"_action": "submit"} and result.metadata is None


async def test_teams_wizard_last_step_only_has_envelope(form):
    renderer = TeamsFormRenderer("https://forms.test/")
    # Test that non-last wizard steps don't have envelope
    result = await renderer.render_section(form, 0, show_back=True, show_skip=False)
    submit_actions = [action for action in result.content["actions"] if action["type"] == "Action.Submit"]
    # Should have Back and Next buttons, but no envelope in Next button
    next_action = next((action for action in submit_actions if action["data"]["_action"] == "next"), None)
    assert next_action is not None
    assert ENVELOPE_KEY not in next_action["data"]
    
    # Test that last wizard step has envelope
    result = await renderer.render_section(form, 0, show_back=True, show_skip=False)
    submit_actions = [action for action in result.content["actions"] if action["type"] == "Action.Submit"]
    # For a single-section form, the last step should have the submit action with envelope
    # But we need to make it explicitly the last step
    result = await renderer.render_section(form, 0, show_back=True, show_skip=False)
    # Since it's a single section form, we can't easily test the "last step" behavior
    # Let's create a multi-section form for this test
    
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