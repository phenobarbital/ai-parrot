"""FEAT-734 end-to-end FormDesigner serving through Teams wrapper seams."""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytest.importorskip("botbuilder")
from aiohttp import web  # noqa: E402
from parrot_formdesigner.api.render import _RENDERERS, handle_render, register_renderer  # noqa: E402
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection  # noqa: E402
from parrot_formdesigner.core.types import FieldType  # noqa: E402
from parrot_formdesigner.renderers.teams import ENVELOPE_KEY, TeamsFormRenderer, TeamsSubmitEnvelope  # noqa: E402
from parrot_formdesigner.services.registry import FormRegistry  # noqa: E402

from parrot.integrations.msteams.formdesigner_client import FormDesignerClient  # noqa: E402
from parrot.integrations.msteams.formdesigner_mixin import PICKER_ACTION_KEY, TeamsFormDesignerMixin  # noqa: E402
from parrot.integrations.msteams.formdesigner_submit import SubmitOutcome  # noqa: E402
from parrot.integrations.msteams.wrapper import MSTeamsAgentWrapper  # noqa: E402

pytestmark = pytest.mark.asyncio

GUID = "11111111-2222-3333-4444-555555555555"
SECRET = "s3cret"
TENANT = "acme"


async def _tenant_wrapped_render(request: web.Request) -> web.Response:
    """Set the URL tenant before delegating to the real render dispatcher."""
    request["tenant"] = request.match_info["tenant"]
    return await handle_render(request)


@pytest.fixture(autouse=True)
def _reset_renderers():
    """Isolate the dispatcher global registry for every test."""
    snapshot = dict(_RENDERERS)
    _RENDERERS.clear()
    yield
    _RENDERERS.clear()
    _RENDERERS.update(snapshot)


@pytest.fixture
def three_section_form() -> FormSchema:
    """Return a public form whose three sections make wizard boundaries visible."""
    return FormSchema(
        form_id="visit",
        title="Store visit",
        tenant=TENANT,
        is_public=True,
        sections=[
            FormSection(
                section_id="details",
                title="Details",
                fields=[FormField(field_id="name", field_type=FieldType.TEXT, label="Name")],
            ),
            FormSection(
                section_id="timing",
                title="Timing",
                fields=[FormField(field_id="day", field_type=FieldType.DATE, label="Day")],
            ),
            FormSection(
                section_id="notes",
                title="Notes",
                fields=[FormField(field_id="notes", field_type=FieldType.TEXT, label="Notes")],
            ),
        ],
    )


class FakeStore:
    """Authenticated session collaborator used by the real mixin identity path."""

    def __init__(self) -> None:
        self.session = SimpleNamespace(
            authenticated=True,
            nav_session_token="nav-tok",
            nav_user_id="user-1",
            tenant_id=GUID,
        )

    async def get_or_create(self, turn_context):
        """Return the fixed authenticated session."""
        return self.session

    def is_expired(self, session) -> bool:
        """Keep the test bearer valid."""
        return False


class AllowAllAuthorizer:
    """Local-mode membership seam that permits the fixed test identity."""

    async def require_membership(self, *, tenant: str, bearer_token: str, user_id: str) -> None:
        """Accept the known local test tenant and identity."""
        assert (tenant, bearer_token, user_id) == (TENANT, "nav-tok", "user-1")


class _BaseAgent:
    """Small Agent stand-in that exposes the cooperative tool hook."""

    def __init__(self, *args, **kwargs) -> None:
        self.tools = self.agent_tools()

    def agent_tools(self) -> list[object]:
        """Return no parent tools for the integration fixture."""
        return []


class FormAgent(TeamsFormDesignerMixin, _BaseAgent):
    """Real serving mixin composed with the smallest possible parent agent."""


def _context(*, text: str = "", value: dict | None = None, activity_id: str = "activity-1") -> MagicMock:
    """Build a Bot Framework-shaped personal-chat turn context."""
    context = MagicMock()
    context.activity.text = text
    context.activity.value = value
    context.activity.id = activity_id
    context.activity.conversation.id = "conversation-1"
    context.activity.conversation.conversation_type = "personal"
    context.activity.from_property.id = "channel-user-1"
    context.activity.channel_data = {"tenant": {"id": GUID}}
    context.send_activity = AsyncMock()
    return context


def _sent_card(context: MagicMock) -> dict:
    """Return the Adaptive Card from the most recent turn response."""
    return context.send_activity.await_args.args[0].attachments[0].content


def _descriptor(form: FormSchema) -> dict:
    """Mirror FormAPIHandler's list descriptor wire shape."""
    return {
        "form_uid": str(form.form_uid),
        "form_id": form.form_id,
        "title": form.title,
        "description": form.description,
        "version": form.version,
        "source": "memory",
        "created_at": form.created_at.isoformat() if form.created_at else None,
    }


async def _remote_server(aiohttp_server, form: FormSchema, *, supports_sections: bool = True):
    """Start a real dispatcher-backed FormDesigner read server for one form."""
    registry = FormRegistry()
    await registry.register(form, tenant=TENANT)
    renderer = TeamsFormRenderer(public_base_url="https://forms.test", signing_secret=SECRET)
    register_renderer("teams", renderer)

    async def list_forms(request: web.Request) -> web.Response:
        return web.json_response({"forms": [_descriptor(item) for item in await registry.list_forms(tenant=TENANT)]})

    async def get_form(request: web.Request) -> web.Response:
        form_item = await registry.get(uuid.UUID(request.match_info["form_uid"]), tenant=request.match_info["tenant"])
        if form_item is None:
            return web.json_response({"error": "not found"}, status=404)
        return web.json_response(form_item.model_dump(mode="json"))

    async def old_render(request: web.Request) -> web.Response:
        """Emulate a pre-section-index server that always renders the full form."""
        form_item = await registry.get(uuid.UUID(request.match_info["form_uid"]), tenant=request.match_info["tenant"])
        rendered = await renderer.render(form_item, tenant=TENANT)
        return web.json_response(
            {
                "content": rendered.content,
                "content_type": rendered.content_type,
                "warnings": [],
                "metadata": rendered.metadata,
            }
        )

    app = web.Application()
    app["form_registry"] = registry
    app.router.add_get("/api/v1/{tenant}/forms", list_forms)
    app.router.add_get("/api/v1/{tenant}/forms/{form_uid}", get_form)
    app.router.add_get(
        "/api/v1/{tenant}/forms/{form_uid}/render/{format}",
        _tenant_wrapped_render if supports_sections else old_render,
    )
    return await aiohttp_server(app)


def _agent(*, mode: str, form: FormSchema, server=None) -> FormAgent:
    """Build a configured real mixin for either remote or local rendering."""
    store = FakeStore()
    if mode == "remote":
        client = FormDesignerClient(str(server.make_url("")))
        agent = FormAgent(formdesigner_client=client, formdesigner_session_store=store)
    else:
        registry = FormRegistry()
        # The caller registers synchronously through the fixture's running loop below.
        agent = FormAgent(
            formdesigner_mode="local",
            formdesigner_registry=registry,
            formdesigner_authorizer=AllowAllAuthorizer(),
            formdesigner_public_url="https://forms.test",
            formdesigner_signing_secret=SECRET,
            formdesigner_session_store=store,
        )
        agent._roundtrip_registry = registry
    agent.apply_teams_config(
        SimpleNamespace(
            formdesigner_base_url=str(server.make_url("")) if server else None,
            formdesigner_tenant=TENANT,
            formdesigner_public_url="https://forms.test",
            formdesigner_submit_secret=SECRET,
            formdesigner_api_base_path="/api/v1",
            formdesigner_mode=mode,
            formdesigner_render_timeout=5.0,
            formdesigner_submit_timeout=5.0,
            formdesigner_allowed_hosts=["forms.test"],
            formdesigner_tenant_map={GUID: TENANT},
        )
    )
    return agent


def _wrapper(agent: FormAgent, store: FakeStore) -> MSTeamsAgentWrapper:
    """Construct the wrapper through its established lightweight test seam."""
    wrapper = MSTeamsAgentWrapper.__new__(MSTeamsAgentWrapper)
    wrapper.config = SimpleNamespace(allowed_conversation_ids=None, allowed_user_ids=None, name="forms-agent")
    wrapper.logger = MagicMock()
    wrapper._command_router = MagicMock()
    wrapper.form_orchestrator = MagicMock()
    wrapper.send_text = AsyncMock()
    wrapper.send_card = AsyncMock()
    wrapper._formdesigner_session = None
    wrapper.agent = agent
    wrapper._session_store = store
    wrapper._wire_formdesigner_agent()
    return wrapper


async def test_getform_slug_sends_card_remote_e2e(aiohttp_server, three_section_form):
    """A remote /getform slug traverses the client, dispatcher, renderer, and mixin."""
    server = await _remote_server(aiohttp_server, three_section_form)
    agent = _agent(mode="remote", form=three_section_form, server=server)
    context = _context(text="/getform visit")

    await agent.handle_getform(context)

    card = _sent_card(context)
    assert card["type"] == "AdaptiveCard"
    assert card["actions"][0]["data"][PICKER_ACTION_KEY]["section_index"] == 0
    await agent.aclose()


@pytest.mark.parametrize("mode", ["remote", "local"])
async def test_wizard_generated_actions_route_to_mixin(aiohttp_server, three_section_form, mode: str):
    """Generated next/submit actions re-enter through the wrapper and post only terminal answers."""
    server = await _remote_server(aiohttp_server, three_section_form) if mode == "remote" else None
    agent = _agent(mode=mode, form=three_section_form, server=server)
    if mode == "local":
        await agent._roundtrip_registry.register(three_section_form, tenant=TENANT)
    wrapper = _wrapper(agent, agent._fd_store)
    initial = _context(text="/getform visit")
    await agent.handle_getform(initial)
    first = _sent_card(initial)
    posted: list[dict] = []

    async def capture_submission(session, envelope, answers, **kwargs):
        posted.append(answers)
        return SubmitOutcome(status=200, body={"submission_id": "submission-1"})

    with patch("parrot.integrations.msteams.formdesigner_mixin.post_submission", side_effect=capture_submission):
        for index, answer in enumerate(({"name": "Ada"}, {"day": "2026-10-24"}, {"notes": "done"})):
            card = first if index == 0 else _sent_card(context)
            assert "actions" in card, card
            expected_action = "submit" if index == 2 else "next"
            action = next(
                action
                for action in card["actions"]
                if action["type"] == "Action.Submit" and action["data"].get("_action") == expected_action
            )
            value = {**action["data"], **answer}
            context = _context(value=value, activity_id=f"activity-{index + 2}")
            await wrapper._handle_card_submission(context, MagicMock(continue_dialog=AsyncMock()))

    assert posted == [{"name": "Ada", "day": "2026-10-24", "notes": "done"}]
    assert _sent_card(context)["type"] == "AdaptiveCard"
    await agent.aclose()


async def test_remote_wizard_section_contract(aiohttp_server, three_section_form):
    """Remote cards contain just their requested section and retain a signed terminal envelope."""
    server = await _remote_server(aiohttp_server, three_section_form)
    client = FormDesignerClient(str(server.make_url("")))

    cards = [
        await client.render_teams(
            tenant=TENANT, form_uid=three_section_form.form_uid, bearer_token="nav-tok", section_index=i
        )
        for i in range(3)
    ]

    for index, card in enumerate(cards):
        input_ids = {block["id"] for block in card.content["body"] if block.get("type", "").startswith("Input.")}
        assert input_ids == ({"name"}, {"day"}, {"notes"})[index]
        assert card.metadata["section_index"] == index
    assert ENVELOPE_KEY not in str(cards[0].content)
    assert ENVELOPE_KEY in str(cards[-1].content)
    assert TeamsSubmitEnvelope.model_validate(cards[-1].metadata["envelope"]).verify(SECRET)
    await client.close()


async def test_remote_wizard_rejects_old_server(aiohttp_server, three_section_form):
    """A server that ignores section_index produces an error card, never a whole-form card."""
    server = await _remote_server(aiohttp_server, three_section_form, supports_sections=False)
    agent = _agent(mode="remote", form=three_section_form, server=server)
    context = _context(text="/getform visit")

    await agent.handle_getform(context)

    card = _sent_card(context)
    assert "Forms are unavailable" in card["body"][0]["text"]
    assert {block.get("id") for block in card["body"]} != {"name", "day", "notes"}
    await agent.aclose()


async def test_toolkit_normal_chat_delivers_card(aiohttp_server, three_section_form):
    """The toolkit queues metadata-only output and the normal-turn flush sends one card."""
    server = await _remote_server(aiohttp_server, three_section_form)
    agent = _agent(mode="remote", form=three_section_form, server=server)
    context = _context()

    async with agent.formdesigner_turn(context):
        tool = next(item for item in agent.tools if item.name == "formdesigner_get_form")
        result = await tool.execute(form="visit")
        await agent.flush_formdesigner_cards(context)

    result_data = result.result
    assert result_data["card_pending"] is True
    assert "AdaptiveCard" not in json.dumps(result_data)
    assert context.send_activity.await_count == 1
    await agent.aclose()
