"""Unit tests for the Phase C worker + pipeline (FEAT-243, TASK-004 + Q-deploy).

Run WITHOUT a live room: the pipeline's component factories / ``AgentSession``,
the FEAT-242 client / room-manager, and the per-job ``LiveAvatarClient`` are all
faked. The PROCESS-model ``entrypoint`` is exercised with those fakes; only the
real LiveKit room connection is out of scope (Phase C integration tests).
"""

import json
from types import SimpleNamespace

import pytest

from parrot.integrations.liveavatar.models import (
    AvatarSessionHandle,
    LiveAvatarConfig,
    LiveKitRoomTokens,
)
from parrot.integrations.liveavatar.livekit_agent import worker as worker_mod
from parrot.integrations.liveavatar.livekit_agent.models import AvatarJobMetadata
from parrot.integrations.liveavatar.livekit_agent.pipeline import build_session
from parrot.integrations.liveavatar.livekit_agent.worker import (
    WorkerConfig,
    build_livekit_config,
    configure,
    entrypoint,
    open_avatar_session,
    parse_job_metadata,
    prewarm,
    register_stop_session_shutdown,
)


# ── Fakes ──────────────────────────────────────────────────────────────────


class FakeSession:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class FakeRoomManager:
    def __init__(self, tokens):
        self._tokens = tokens
        self.calls = []

    def mint_room_tokens(self, *, room, identity):
        self.calls.append((room, identity))
        return self._tokens


class FakeClient:
    def __init__(self, created_handle):
        self._created = created_handle
        self.created_with = None
        self.started = []
        self.stopped = []

    async def create_session_token(self, cfg, *, livekit_config=None):
        self.created_with = (cfg, livekit_config)
        return self._created

    async def start_session(self, handle):
        self.started.append(handle)
        return {"ok": True}

    async def stop_session(self, handle):
        self.stopped.append(handle)


class FakeJobCtx:
    def __init__(self, metadata: str):
        self.job = SimpleNamespace(metadata=metadata)
        self.shutdown_callbacks = []

    def add_shutdown_callback(self, cb):
        self.shutdown_callbacks.append(cb)


def _tokens() -> LiveKitRoomTokens:
    return LiveKitRoomTokens(
        livekit_url="wss://proj.livekit.cloud",
        room="s1",
        client_token="client-jwt",
        agent_token="agent-jwt",
    )


def _created_handle() -> AvatarSessionHandle:
    return AvatarSessionHandle(
        session_id="ignored-by-api",
        liveavatar_session_id="la-123",
        session_token="bearer-xyz",
        ws_url="wss://avatar.media/ws",
        agent_name="demo",
    )


def _cfg() -> LiveAvatarConfig:
    return LiveAvatarConfig(api_key="k", avatar_id="a", is_sandbox=True)


def _meta() -> AvatarJobMetadata:
    return AvatarJobMetadata(
        ws_url="wss://proj.livekit.cloud",
        session_id="s1",
        agent_name="demo",
        tenant_id="t1",
    )


# ── Tests ──────────────────────────────────────────────────────────────────


def test_build_session_components():
    """build_session wires STT / VAD / turn-detection / TTS into the session."""
    vad = SimpleNamespace(name="silero-vad")
    stt = SimpleNamespace(name="deepgram-stt")
    tts = SimpleNamespace(name="cartesia-tts")
    turn = SimpleNamespace(name="multilingual-turn")

    session = build_session(
        vad,
        stt=stt,
        tts=tts,
        turn_detection=turn,
        session_factory=FakeSession,
    )

    assert isinstance(session, FakeSession)
    assert session.kwargs["stt"] is stt
    assert session.kwargs["vad"] is vad
    assert session.kwargs["tts"] is tts
    assert session.kwargs["turn_detection"] is turn


def test_parse_job_metadata():
    """ctx.job.metadata JSON parses into AvatarJobMetadata."""
    ctx = FakeJobCtx(
        json.dumps(
            {
                "ws_url": "wss://proj.livekit.cloud",
                "session_id": "s1",
                "agent_name": "demo",
                "tenant_id": "t1",
            }
        )
    )
    meta = parse_job_metadata(ctx)
    assert meta.session_id == "s1"
    assert meta.agent_name == "demo"
    assert meta.tenant_id == "t1"


def test_build_livekit_config():
    """Tokens compose into the avatar's livekit_config (joins our room)."""
    cfg = build_livekit_config(_tokens())
    assert cfg == {
        "url": "wss://proj.livekit.cloud",
        "room": "s1",
        "agentToken": "agent-jwt",
    }


@pytest.mark.asyncio
async def test_open_avatar_session():
    """open_avatar_session mints tokens, creates + starts the session."""
    room_manager = FakeRoomManager(_tokens())
    client = FakeClient(_created_handle())

    handle = await open_avatar_session(client, _cfg(), room_manager, _meta())

    # Minted tokens for our room, keyed by session_id, identity = agent_name
    assert room_manager.calls == [("s1", "demo")]
    # create_session_token received the livekit_config for BYO transport
    _, livekit_config = client.created_with
    assert livekit_config["room"] == "s1"
    assert livekit_config["agentToken"] == "agent-jwt"
    # Returned handle carries our session_id / tenant_id / agent_name
    assert handle.session_id == "s1"
    assert handle.tenant_id == "t1"
    assert handle.agent_name == "demo"
    assert handle.liveavatar_session_id == "la-123"
    # Session was started
    assert client.started == [handle]


@pytest.mark.asyncio
async def test_stop_session_shutdown_callback():
    """stop_session is registered as a shutdown callback and runs on teardown."""
    client = FakeClient(_created_handle())
    handle = AvatarSessionHandle(
        session_id="s1",
        liveavatar_session_id="la-123",
        session_token="bearer",
        ws_url="wss://avatar.media/ws",
        agent_name="demo",
    )
    ctx = FakeJobCtx("{}")

    cb = register_stop_session_shutdown(ctx, client, handle)

    # Registered exactly one shutdown callback
    assert ctx.shutdown_callbacks == [cb]
    # Invoking it tears the session down
    assert client.stopped == []
    await ctx.shutdown_callbacks[0]()
    assert client.stopped == [handle]


@pytest.mark.asyncio
async def test_stop_session_shutdown_callback_swallows_errors():
    """Teardown never raises even if stop_session fails."""

    class FailingClient(FakeClient):
        async def stop_session(self, handle):
            raise RuntimeError("network down")

    client = FailingClient(_created_handle())
    handle = AvatarSessionHandle(
        session_id="s1",
        liveavatar_session_id="la-123",
        session_token="bearer",
        ws_url="wss://avatar.media/ws",
        agent_name="demo",
    )
    ctx = FakeJobCtx("{}")

    register_stop_session_shutdown(ctx, client, handle)
    # Must not raise
    await ctx.shutdown_callbacks[0]()


# ── PROCESS-model: configure / prewarm / entrypoint (Q-deploy) ──────────────


@pytest.fixture(autouse=True)
def _reset_worker_config():
    """Isolate the module-level worker config between tests."""
    worker_mod._CONFIG = None
    yield
    worker_mod._CONFIG = None


class FakeEntrypointClient:
    """LiveAvatarClient stand-in with async-context + session lifecycle."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.entered = False
        self.exited = False
        self.started = []

    async def __aenter__(self):
        self.entered = True
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self.exited = True

    async def create_session_token(self, cfg, *, livekit_config=None):
        self.livekit_config = livekit_config
        return _created_handle()

    async def start_session(self, handle):
        self.started.append(handle)


class FakeEntrypointCtx:
    def __init__(self, metadata, vad="prewarmed-vad"):
        self.job = SimpleNamespace(metadata=metadata)
        self.proc = SimpleNamespace(userdata={"vad": vad})
        self.room = SimpleNamespace(name="room-1")
        self.shutdown_callbacks = []
        self.connected = False

    def add_shutdown_callback(self, cb):
        self.shutdown_callbacks.append(cb)

    async def connect(self):
        self.connected = True


async def _resolver(name):
    return SimpleNamespace(name=name)


def test_configure_sets_module_config_and_defaults():
    """configure() stores a WorkerConfig with the injected pieces."""
    sink = object()
    cfg = configure(
        bot_resolver=_resolver,
        cfg=_cfg(),
        output_sink=sink,
        room_manager=FakeRoomManager(_tokens()),
        agent_name="voice-worker",
    )
    assert isinstance(cfg, WorkerConfig)
    assert worker_mod._CONFIG is cfg
    assert cfg.output_sink is sink
    assert cfg.agent_name == "voice-worker"


@pytest.mark.asyncio
async def test_entrypoint_raises_without_configure():
    """entrypoint refuses to run if the worker was never configured."""
    with pytest.raises(RuntimeError, match="not configured"):
        await entrypoint(FakeEntrypointCtx("{}"))


def test_prewarm_loads_vad_into_userdata(monkeypatch):
    """prewarm stores a process-wide VAD in proc.userdata."""
    import sys
    import types

    fake_silero = types.ModuleType("livekit.plugins.silero")
    fake_silero.VAD = SimpleNamespace(load=lambda: "FAKE_VAD")
    monkeypatch.setitem(sys.modules, "livekit.plugins.silero", fake_silero)
    # also satisfy ``from livekit.plugins import silero``
    fake_plugins = types.ModuleType("livekit.plugins")
    fake_plugins.silero = fake_silero
    monkeypatch.setitem(sys.modules, "livekit.plugins", fake_plugins)

    proc = SimpleNamespace(userdata={})
    prewarm(proc)
    assert proc.userdata["vad"] == "FAKE_VAD"


@pytest.mark.asyncio
async def test_entrypoint_builds_deps_in_process_and_starts_session(monkeypatch):
    """The PROCESS-model entrypoint wires client/session/agent without bound deps."""
    # Capture the session built and the agent bound at start().
    started = {}

    class FakeSession:
        async def start(self, agent, room):
            started["agent"] = agent
            started["room"] = room

    captured_vad = {}

    def fake_build_session(vad):
        captured_vad["vad"] = vad
        return FakeSession()

    created_clients = []

    def fake_client_ctor(cfg):
        client = FakeEntrypointClient(cfg)
        created_clients.append(client)
        return client

    monkeypatch.setattr(worker_mod, "LiveAvatarClient", fake_client_ctor)
    monkeypatch.setattr(worker_mod, "build_session", fake_build_session)

    sink = object()
    configure(
        bot_resolver=_resolver,
        cfg=_cfg(),
        output_sink=sink,
        room_manager=FakeRoomManager(_tokens()),
    )

    meta = json.dumps(
        {"ws_url": "wss://x", "session_id": "s1", "agent_name": "demo", "tenant_id": "t1"}
    )
    ctx = FakeEntrypointCtx(meta, vad="prewarmed-vad")

    await entrypoint(ctx)

    # Per-job client built IN-PROCESS (not bound via partial), entered, session started.
    assert len(created_clients) == 1 and created_clients[0].entered
    assert created_clients[0].started, "start_session was called"
    # Prewarmed VAD flowed from ctx.proc.userdata into build_session.
    assert captured_vad["vad"] == "prewarmed-vad"
    # Room connected and the LiveAvatarAgent bound with our session_id + sink.
    assert ctx.connected is True
    assert started["room"] is ctx.room
    agent = started["agent"]
    assert agent._session_id == "s1"
    assert agent._agent_name == "demo"
    assert agent._bridge._sockets is sink
    # Shutdown callback registered; invoking it closes the per-job client.
    assert ctx.shutdown_callbacks
    await ctx.shutdown_callbacks[0]()
    assert created_clients[0].exited is True
