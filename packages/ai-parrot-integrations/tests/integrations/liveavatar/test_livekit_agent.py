"""Unit tests for the llm_node ai-parrot bridge (FEAT-243, TASK-003).

These run WITHOUT the ``liveavatar-voice`` extra: ``livekit-agents`` is absent,
so ``LiveAvatarAgent`` subclasses ``object`` and the streaming bifurcation is
exercised directly with fakes for ``chat_ctx`` and the ai-parrot bot.
"""

from types import SimpleNamespace

import pytest

from parrot.models.basic import CompletionUsage
from parrot.models.responses import AIMessage
from parrot.integrations.liveavatar.livekit_agent.agent import (
    DEFAULT_FILLER_TEXT,
    LiveAvatarAgent,
    _json_safe,
    _last_user_text,
    _message_text,
    _structured_payload,
)
from parrot.integrations.liveavatar.livekit_agent.models import (
    StructuredOutputMessage,
)


# ── Fakes ──────────────────────────────────────────────────────────────────


def _msg(role: str, text: str) -> SimpleNamespace:
    """A minimal livekit-style ChatMessage (role + str content)."""
    return SimpleNamespace(role=role, content=text)


def _chat_ctx(*messages: SimpleNamespace) -> SimpleNamespace:
    """A minimal livekit ChatContext exposing ``.items`` (1.x shape)."""
    return SimpleNamespace(items=list(messages))


def _ai_message(**overrides) -> AIMessage:
    """Build a minimal valid AIMessage sentinel (real model — fidelity)."""
    base = dict(
        input="q",
        output=overrides.pop("output", ""),
        model="m",
        provider="p",
        usage=CompletionUsage(),
    )
    base.update(overrides)
    return AIMessage(**base)


def _sentinel(**attrs) -> SimpleNamespace:
    """A duck-typed AIMessage-like final chunk.

    Used where the structured fields (e.g. ``tool_calls`` of duck-typed
    objects, custom ``output_mode``) don't need full AIMessage validation. The
    bridge only relies on attribute access, mirroring how ``llm_node`` reads it.
    """
    defaults = dict(
        tool_calls=[],
        data=None,
        response=None,
        code=None,
        artifact_id=None,
        output_mode=SimpleNamespace(value="default"),
    )
    defaults.update(attrs)
    return SimpleNamespace(**defaults)


class FakeBot:
    """ai-parrot bot whose ask_stream replays a scripted sequence of chunks."""

    def __init__(self, chunks):
        self._chunks = chunks
        self.calls = []

    async def ask_stream(self, question, session_id=None, **kwargs):
        self.calls.append({"question": question, "session_id": session_id})
        for chunk in self._chunks:
            yield chunk


class CapturingBridge:
    """Captures published StructuredOutputMessage objects."""

    def __init__(self):
        self.published = []

    async def publish(self, msg: StructuredOutputMessage):
        self.published.append(msg)


def _make_agent(bot, bridge=None, **kwargs):
    bridge = bridge or CapturingBridge()

    async def resolver(name):
        return bot

    return LiveAvatarAgent(
        agent_name="demo",
        session_id="s1",
        bot_resolver=resolver,
        output_bridge=bridge,
        tenant_id="t1",
        **kwargs,
    )


async def _collect(agen):
    return [item async for item in agen]


# ── Tests ──────────────────────────────────────────────────────────────────


def test_llm_node_last_user_text():
    """_last_user_text returns the LAST role='user' message text."""
    ctx = _chat_ctx(
        _msg("system", "you are helpful"),
        _msg("user", "first question"),
        _msg("assistant", "an answer"),
        _msg("user", "the latest question"),
    )
    assert _last_user_text(ctx) == "the latest question"


def test_last_user_text_supports_messages_shape():
    """Falls back to ``.messages`` when ``.items`` is absent."""
    ctx = SimpleNamespace(messages=[_msg("user", "hello there")])
    assert _last_user_text(ctx) == "hello there"


@pytest.mark.asyncio
async def test_llm_node_yields_speakable_str():
    """Plain str chunks from ask_stream are yielded as speakable strings."""
    bot = FakeBot(["Hello there. ", "How are you? ", _ai_message(response="")])
    agent = _make_agent(bot)

    out = await _collect(
        agent.llm_node(_chat_ctx(_msg("user", "hi")), tools=None, model_settings=None)
    )

    assert out == ["Hello there.", "How are you?"]
    # ask_stream invoked with the extracted user text + session_id
    assert bot.calls[0]["question"] == "hi"
    assert bot.calls[0]["session_id"] == "s1"


@pytest.mark.asyncio
async def test_speakable_flatten_reused():
    """Markdown is stripped via the FEAT-242 SpeakableFlattener before TTS."""
    bot = FakeBot(["This is **bold** and `code`. ", _ai_message(response="")])
    agent = _make_agent(bot)

    out = await _collect(
        agent.llm_node(_chat_ctx(_msg("user", "x")), tools=None, model_settings=None)
    )

    spoken = " ".join(out)
    # FEAT-242 flattener strips emphasis markers (keeping the words) and drops
    # inline code spans entirely (code is not read aloud).
    assert "**" not in spoken and "`" not in spoken
    assert "bold" in spoken
    assert "code" not in spoken


@pytest.mark.asyncio
async def test_llm_node_filler_on_tool_calls():
    """A tool turn with no speech emits the filler utterance (no dead air)."""
    tool_msg = _sentinel(
        tool_calls=[SimpleNamespace(name="get_sales")],
        data={"rows": [1, 2]},
    )
    bridge = CapturingBridge()
    bot = FakeBot([tool_msg])
    agent = _make_agent(bot, bridge=bridge)

    out = await _collect(
        agent.llm_node(_chat_ctx(_msg("user", "sales?")), tools=None, model_settings=None)
    )

    assert out == [DEFAULT_FILLER_TEXT]
    # structured output routed to the bridge, keyed by session_id
    assert len(bridge.published) == 1
    published = bridge.published[0]
    assert published.type == "tool_call"
    assert published.session_id == "s1"


@pytest.mark.asyncio
async def test_structured_output_routed_not_spoken():
    """A non-default output_mode (chart) is bridged; not double-spoken."""
    chart_msg = _ai_message(output_mode="chart", data={"spec": {}})
    bridge = CapturingBridge()
    bot = FakeBot(["Here is your chart. ", chart_msg])
    agent = _make_agent(bot, bridge=bridge)

    out = await _collect(
        agent.llm_node(_chat_ctx(_msg("user", "chart it")), tools=None, model_settings=None)
    )

    assert out == ["Here is your chart."]
    assert bridge.published[0].type == "chart"


@pytest.mark.asyncio
async def test_block_response_spoken_when_not_streamed():
    """A non-streamed text AIMessage (no tool calls) is spoken via the flattener."""
    bot = FakeBot([_ai_message(response="A single block answer.")])
    agent = _make_agent(bot)

    out = await _collect(
        agent.llm_node(_chat_ctx(_msg("user", "q")), tools=None, model_settings=None)
    )

    assert out == ["A single block answer."]


# ── Edge cases / robustness (review #6, #7) ─────────────────────────────────


def test_message_text_handles_callable_text_content():
    """_message_text resolves the ``text_content()`` callable form."""
    msg = SimpleNamespace(role="user", text_content=lambda: "from callable")
    assert _message_text(msg) == "from callable"


def test_message_text_joins_list_content_parts():
    """_message_text joins string parts of a list ``content``."""
    msg = SimpleNamespace(role="user", content=["hello", "world"])
    assert _message_text(msg) == "hello world"


@pytest.mark.asyncio
async def test_empty_user_text_skips_ask_stream():
    """With no user message, llm_node yields nothing and never calls ask_stream."""
    bot = FakeBot(["should not be reached"])
    agent = _make_agent(bot)

    out = await _collect(
        agent.llm_node(_chat_ctx(_msg("system", "sys only")), tools=None, model_settings=None)
    )

    assert out == []
    assert bot.calls == []


@pytest.mark.asyncio
async def test_bridge_failure_does_not_break_speech():
    """A failing OutputBridge.publish is logged, not propagated — speech continues."""

    class FailingBridge:
        async def publish(self, msg):
            raise RuntimeError("socket manager down")

    chart_msg = _ai_message(output_mode="chart", data={"spec": {}})
    bot = FakeBot(["Here is the chart. ", chart_msg])
    agent = _make_agent(bot, bridge=FailingBridge())

    out = await _collect(
        agent.llm_node(_chat_ctx(_msg("user", "chart")), tools=None, model_settings=None)
    )

    # The spoken text still made it through despite the bridge failure.
    assert out == ["Here is the chart."]


@pytest.mark.asyncio
async def test_multiple_sentinels_publish_without_double_filler():
    """Two structured sentinels each publish; filler is not repeated once spoke."""
    bridge = CapturingBridge()
    tool_msg_1 = _sentinel(tool_calls=[SimpleNamespace(name="a")], data={"x": 1})
    tool_msg_2 = _sentinel(tool_calls=[SimpleNamespace(name="b")], data={"y": 2})
    bot = FakeBot(["Working on it. ", tool_msg_1, tool_msg_2])
    agent = _make_agent(bot, bridge=bridge)

    out = await _collect(
        agent.llm_node(_chat_ctx(_msg("user", "go")), tools=None, model_settings=None)
    )

    # Spoke real text first -> no filler at all; both sentinels published.
    assert out == ["Working on it."]
    assert DEFAULT_FILLER_TEXT not in out
    assert [p.type for p in bridge.published] == ["tool_call", "tool_call"]


@pytest.mark.asyncio
async def test_dataframe_payload_is_json_safe_end_to_end():
    """A pandas DataFrame in AIMessage.data is sanitized so the broadcast encodes."""
    pd = pytest.importorskip("pandas")
    from datamodel.parsers.json import json_encoder

    bridge = CapturingBridge()
    df_msg = _ai_message(output_mode="table", data=pd.DataFrame({"a": [1, 2]}))
    bot = FakeBot([df_msg])
    agent = _make_agent(bot, bridge=bridge)

    await _collect(
        agent.llm_node(_chat_ctx(_msg("user", "table")), tools=None, model_settings=None)
    )

    published = bridge.published[0]
    assert published.type == "table"
    # The exact failure mode from review A-1: encoding must not raise.
    json_encoder(published.model_dump())
    assert published.payload["data"] == [{"a": 1}, {"a": 2}]


def test_json_safe_passes_through_plain_types():
    """_json_safe is a no-op for already-serializable structures."""
    assert _json_safe({"k": [1, "two", 3.0, None, True]}) == {
        "k": [1, "two", 3.0, None, True]
    }


def test_structured_payload_normalizes_dataframe():
    """_structured_payload converts a DataFrame data field to records."""
    pd = pytest.importorskip("pandas")
    msg = _ai_message(output_mode="table", data=pd.DataFrame({"a": [1]}))
    payload = _structured_payload(msg)
    assert payload["data"] == [{"a": 1}]


@pytest.mark.asyncio
async def test_barge_in_aclose_midstream_does_not_raise():
    """Closing the generator mid-utterance (barge-in) must not raise.

    Guards the deliberate choice to flush OUTSIDE a ``finally`` — a ``yield`` in
    ``finally`` would raise GeneratorExit when the LiveKit pipeline interrupts.
    """
    bot = FakeBot(["First sentence. ", "Second sentence. ", "Third. "])
    agent = _make_agent(bot)

    gen = agent.llm_node(
        _chat_ctx(_msg("user", "talk")), tools=None, model_settings=None
    )
    first = await gen.__anext__()
    assert first == "First sentence."

    # Simulate barge-in: consumer stops and closes the generator early.
    await gen.aclose()  # must not raise RuntimeError("ignored GeneratorExit")
