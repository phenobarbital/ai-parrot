"""Unit tests for TeamsFormRenderer / TeamsSubmitEnvelope (FEAT-551 TASK-3147/TASK-3148)."""
import json
import pytest
from parrot_formdesigner.core import FormSchema, FormSection, FormSubsection   # verified: test_renderers.py:4
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

def _walk(node):
    """Yield every dict node in a nested Adaptive Card items/actions/body tree (TASK-3148)."""
    if isinstance(node, dict):
        yield node
        for key in ("items", "actions", "body"):
            for child in node.get(key) or []:
                yield from _walk(child)
    elif isinstance(node, list):
        for child in node:
            yield from _walk(child)


@pytest.fixture
def upload_form() -> FormSchema:
    """Public form (tenant=navigator) with an IMAGE field at top level and a FILE field nested
    inside a FormSubsection — exercises `_upload_warnings`' section+subsection walk (TASK-3148)."""
    return FormSchema(
        form_id="teams-upload-demo",
        title="Teams Upload Demo",
        tenant="navigator",
        is_public=True,
        sections=[
            FormSection(
                section_id="main",
                title="Main",
                fields=[
                    FormField(field_id="photo", field_type=FieldType.IMAGE, label="Photo"),
                    FormSubsection(
                        subsection_id="attachments",
                        title="Attachments",
                        fields=[
                            FormField(field_id="doc", field_type=FieldType.FILE, label="Document"),
                        ],
                    ),
                ],
            )
        ],
    )


async def test_teams_upload_fields_openurl_and_warning(renderer, upload_form):
    result = await renderer.render(upload_form, tenant="navigator")
    opens = [n for n in _walk(result.content["body"]) if n.get("type") == "Action.OpenUrl"]
    assert len(opens) == 2
    assert all(
        o["url"] == f"https://forms.test/navigator/forms/{upload_form.form_uid}" for o in opens
    )
    # Neither upload field's id shows up on an Input.* element — they render as
    # Container + Action.OpenUrl instead (spec §3 M2).
    upload_ids = {"photo", "doc"}
    inputs = [
        n for n in _walk(result.content["body"])
        if str(n.get("type", "")).startswith("Input.") and n.get("id") in upload_ids
    ]
    assert inputs == []
    teams_warnings = [w for w in result.warnings if w.renderer == "teams"]
    assert sorted(w.field_type for w in teams_warnings) == ["file", "image"]


@pytest.mark.parametrize(
    "field_type",
    [FieldType.FILE, FieldType.IMAGE, FieldType.IMAGE_DROPZONE, FieldType.MULTI_UPLOAD],
)
async def test_teams_upload_field_types_all_get_openurl_and_warning(renderer, field_type):
    single_field_form = FormSchema(
        form_id="teams-upload-single",
        title="Teams Upload Single",
        tenant="navigator",
        is_public=True,
        sections=[
            FormSection(
                section_id="main",
                title="Main",
                fields=[FormField(field_id="upload", field_type=field_type, label="Upload")],
            )
        ],
    )
    result = await renderer.render(single_field_form, tenant="navigator")
    opens = [n for n in _walk(result.content["body"]) if n.get("type") == "Action.OpenUrl"]
    assert len(opens) == 1
    assert opens[0]["url"] == f"https://forms.test/navigator/forms/{single_field_form.form_uid}"
    teams_warnings = [
        w for w in result.warnings if w.renderer == "teams" and w.field_id == "upload"
    ]
    assert len(teams_warnings) == 1
    assert teams_warnings[0].field_type == field_type.value


async def test_adaptive_upload_fallback_unchanged(upload_form):
    result = await AdaptiveCardRenderer().render(upload_form)
    assert not [w for w in result.warnings if w.field_type in ("file", "image")]
    inputs = {n["id"]: n for n in _walk(result.content["body"]) if n.get("type") == "Input.Text" and "id" in n}
    assert inputs["photo"]["type"] == "Input.Text"
    assert inputs["doc"]["type"] == "Input.Text"
