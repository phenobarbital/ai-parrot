"""FEAT-734 M4 outbound Teams FormDesigner mixin tests."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import uuid

import pytest

pytest.importorskip("botbuilder")

from parrot.integrations.msteams.formdesigner_client import FormDescriptor, FormDesignerError, RenderedCard
from parrot.integrations.msteams.formdesigner_mixin import TeamsFormDesignerMixin

GUID = "11111111-2222-3333-4444-555555555555"
FORM_UID = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")


class _Base:
    """Stands in for Agent, which calls ``agent_tools`` during initialization."""

    def __init__(self, *args, **kwargs):
        self.tools = self.agent_tools()

    def agent_tools(self):
        return []


class FDAgent(TeamsFormDesignerMixin, _Base):
    """Test agent composed with the FormDesigner mixin."""


class FakeStore:
    """Read-only session store that records forbidden attribute access."""

    def __init__(self, session=None, *, expired=False):
        self.session = session or SimpleNamespace(
            authenticated=True,
            nav_session_token="nav-token",
            nav_user_id="user-1",
            tenant_id=GUID,
        )
        self.expired = expired
        self.calls = []

    async def get_or_create(self, turn_context):
        self.calls.append("get_or_create")
        return self.session

    def is_expired(self, session):
        self.calls.append("is_expired")
        return self.expired

    def __getattr__(self, name):
        self.calls.append(name)
        raise AssertionError(f"unexpected store access: {name}")


class FakeReader:
    """FormReader-compatible fake for command and toolkit tests."""

    def __init__(self, form=None, forms=None):
        self.form = form or _form()
        self.forms = forms if forms is not None else [_descriptor()]
        self.calls = []
        self.error = None

    async def list_forms(self, **kwargs):
        self.calls.append(("list", kwargs))
        if self.error:
            raise self.error
        return self.forms

    async def get_form_by_slug(self, **kwargs):
        self.calls.append(("slug", kwargs))
        if self.error:
            raise self.error
        return _descriptor() if kwargs["slug"] == "survey" else None

    async def get_form(self, **kwargs):
        self.calls.append(("form", kwargs))
        if self.error:
            raise self.error
        return self.form

    async def render_teams(self, **kwargs):
        self.calls.append(("render", kwargs))
        if self.error:
            raise self.error
        card = {
            "type": "AdaptiveCard",
            "version": "1.5",
            "body": [],
            "actions": [{"type": "Action.Submit", "data": {"_action": "next"}}],
        }
        return RenderedCard(
            content=card,
            content_type="application/vnd.microsoft.card.adaptive",
            metadata={"total_sections": len(self.form.sections)} if kwargs.get("section_index") is not None else {},
        )

    async def close(self):
        self.closed = True


def _descriptor():
    return FormDescriptor(form_uid=FORM_UID, form_id="survey", title="Survey")


def _form(sections=1):
    return SimpleNamespace(
        form_uid=FORM_UID,
        form_id="survey",
        version="1",
        published_version=None,
        sections=[SimpleNamespace() for _ in range(sections)],
    )


def _ctx(text="/getform", conv_type="personal"):
    ctx = MagicMock()
    ctx.activity.text = text
    ctx.activity.conversation.id = "conv-1"
    ctx.activity.conversation.conversation_type = conv_type
    ctx.activity.channel_data = {"tenant": {"id": GUID}}
    ctx.send_activity = AsyncMock()
    return ctx


def _card(ctx):
    return ctx.send_activity.await_args.args[0].attachments[0].content


def _agent(reader=None, store=None, **kwargs):
    agent = FDAgent(
        formdesigner_client=reader or FakeReader(),
        formdesigner_session_store=store or FakeStore(),
        **kwargs,
    )
    agent._fd_tenant_map = {GUID: "workspace"}
    return agent


@pytest.mark.asyncio
async def test_mixin_never_calls_ensure_authenticated():
    store = FakeStore()
    agent = _agent(store=store)
    await agent.handle_listforms(_ctx())
    assert "ensure_authenticated" not in store.calls


@pytest.mark.asyncio
async def test_getform_slug_sends_card_remote():
    ctx = _ctx("<at>bot</at> /getform survey")
    await _agent().handle_getform(ctx)
    assert _card(ctx)["type"] == "AdaptiveCard"


@pytest.mark.asyncio
async def test_getform_uid_sends_card_remote():
    ctx = _ctx(f"/getform {FORM_UID}")
    await _agent().handle_getform(ctx)
    assert _card(ctx)["type"] == "AdaptiveCard"


@pytest.mark.asyncio
async def test_getform_unknown_slug_sends_not_found():
    ctx = _ctx("/getform missing")
    await _agent().handle_getform(ctx)
    assert "No form found" in _card(ctx)["body"][0]["text"]


@pytest.mark.asyncio
async def test_getform_no_arg_sends_picker():
    ctx = _ctx()
    await _agent().handle_getform(ctx)
    assert _card(ctx)["body"][1]["type"] == "Input.ChoiceSet"


@pytest.mark.asyncio
async def test_listforms_empty_state():
    ctx = _ctx("/listforms")
    await _agent(FakeReader(forms=[])).handle_listforms(ctx)
    assert "no forms" in _card(ctx)["body"][0]["text"].lower()


@pytest.mark.asyncio
async def test_no_session_sends_login_card_and_fetches_nothing():
    reader = FakeReader()
    session = SimpleNamespace(authenticated=False, nav_session_token=None, nav_user_id=None, tenant_id=GUID)
    ctx = _ctx()
    await _agent(reader, FakeStore(session)).handle_getform(ctx)
    assert "sign in" in _card(ctx)["body"][0]["text"].lower()
    assert not reader.calls


@pytest.mark.asyncio
async def test_group_chat_refused():
    reader = FakeReader()
    ctx = _ctx(conv_type="groupChat")
    await _agent(reader).handle_getform(ctx)
    assert "1:1" in _card(ctx)["body"][0]["text"]
    assert not reader.calls


@pytest.mark.asyncio
async def test_local_mode_renders_with_teams_renderer(monkeypatch):
    reader = FakeReader()
    monkeypatch.setattr("parrot.integrations.msteams.formdesigner_mixin.LocalFormReader", lambda *args, **kwargs: reader)
    ctx = _ctx("/getform survey")
    await _agent(formdesigner_mode="local", formdesigner_registry=object()).handle_getform(ctx)
    assert _card(ctx)["type"] == "AdaptiveCard"


@pytest.mark.asyncio
async def test_local_mode_without_secret_refuses():
    ctx = _ctx("/getform survey")
    await _agent(formdesigner_mode="local", formdesigner_registry=object()).handle_getform(ctx)
    assert "not configured" in _card(ctx)["body"][0]["text"].lower()


@pytest.mark.asyncio
async def test_local_membership_denied_before_registry(monkeypatch):
    reader = FakeReader()
    reader.error = FormDesignerError("denied", status=403)
    monkeypatch.setattr("parrot.integrations.msteams.formdesigner_mixin.LocalFormReader", lambda *args, **kwargs: reader)
    ctx = _ctx()
    await _agent(formdesigner_mode="local", formdesigner_registry=object()).handle_listforms(ctx)
    assert "don't have access" in _card(ctx)["body"][0]["text"]


@pytest.mark.asyncio
async def test_local_membership_authorized(monkeypatch):
    reader = FakeReader()
    monkeypatch.setattr("parrot.integrations.msteams.formdesigner_mixin.LocalFormReader", lambda *args, **kwargs: reader)
    ctx = _ctx()
    await _agent(formdesigner_mode="local", formdesigner_registry=object()).handle_listforms(ctx)
    assert reader.calls[0][0] == "list"


@pytest.mark.asyncio
async def test_sectioned_form_starts_wizard_with_control_objects():
    ctx = _ctx("/getform survey")
    await _agent(FakeReader(form=_form(2))).handle_getform(ctx)
    control = _card(ctx)["actions"][0]["data"]["_formdesigner_action"]
    assert control["kind"] == "wizard"
    assert control["section_index"] == 0


@pytest.mark.asyncio
async def test_toolkit_turn_isolation_and_cleanup():
    agent = _agent()
    ctx = _ctx()
    async with agent.formdesigner_turn(ctx):
        tool = next(tool for tool in agent.tools if tool.name == "formdesigner_get_form")
        await tool.execute(form="survey")
        await tool.execute(form="survey")
        await agent.flush_formdesigner_cards(ctx)
    assert ctx.send_activity.await_count == 1
    list_tool = next(tool for tool in agent.tools if tool.name == "formdesigner_list_forms")
    assert (await list_tool.execute()).result == {"status": "unavailable", "reason": "login_required"}


@pytest.mark.asyncio
async def test_flush_rechecks_expired_session():
    store = FakeStore()
    reader = FakeReader()
    agent = _agent(reader, store)
    ctx = _ctx()
    async with agent.formdesigner_turn(ctx):
        agent._fd_wizards.start(
            conversation_id="conv-1", form_uid=FORM_UID, tenant="workspace", total_sections=1, owner_user_id="user-1", form_version="1"
        )
        from parrot.integrations.msteams.formdesigner_turn import active_turn

        active_turn().enqueue(FORM_UID)
        store.expired = True
        await agent.flush_formdesigner_cards(ctx)
    assert "sign in" in _card(ctx)["body"][0]["text"].lower()


def test_apply_teams_config_constructor_wins():
    config = SimpleNamespace(
        formdesigner_base_url="https://config.example",
        formdesigner_tenant="config-tenant",
        formdesigner_public_url="https://public.example",
        formdesigner_submit_secret="config-secret",
        formdesigner_api_base_path="/configured",
        formdesigner_mode="local",
        formdesigner_render_timeout=11,
        formdesigner_submit_timeout=12,
        formdesigner_allowed_hosts=["EXAMPLE.COM"],
        formdesigner_tenant_map={GUID: "workspace"},
    )
    agent = _agent(formdesigner_base_url="https://constructor.example", formdesigner_mode="remote")
    agent.apply_teams_config(config)
    assert agent._fd_base_url == "https://constructor.example"
    assert agent.formdesigner_mode == "remote"
    assert agent._fd_allowed_hosts == ["example.com"]


@pytest.mark.asyncio
async def test_aclose_closes_sessions():
    reader = FakeReader()
    agent = _agent(reader)
    http = AsyncMock(closed=False)
    agent._fd_http = http
    await agent.aclose()
    assert reader.closed
    http.close.assert_awaited_once()
