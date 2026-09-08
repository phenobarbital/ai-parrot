"""Runnable-example broadcast backend tests (FEAT-537 TASK-2963).

Loads the real ``examples/clients/voice/server.py`` by path (the same pattern
the FEAT-536 demo tests use — it is a standalone script, not an installed
package) and exercises its broadcast wiring, demo authentication and safety
guards.

Nothing here contacts Redis, LiveKit or LiveAvatar: the registry is swapped for
the in-memory one and the media session for a fake, so these assert the
*wiring*, not vendor behaviour.
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
import types
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest
from aiohttp import web

_REPO_ROOT = Path(__file__).resolve().parents[4]
_SERVER_PATH = _REPO_ROOT / "examples" / "clients" / "voice" / "server.py"

# The example legitimately depends on `ai-parrot-server` for the broadcast HTTP
# routes. In a worktree the editable install still points at the main checkout,
# so this package's sources must be prepended for the worktree's own
# `parrot.handlers.voice_broadcast` to be importable — the same thing
# `packages/ai-parrot-server/tests/conftest.py` does for its own suite.
_SERVER_PKG_SRC = _REPO_ROOT / "packages" / "ai-parrot-server" / "src"
if str(_SERVER_PKG_SRC) not in sys.path:
    sys.path.insert(0, str(_SERVER_PKG_SRC))


def _client_stub_modules() -> Optional[Dict[str, Any]]:
    """Build stand-ins for the client satellites, when they are absent.

    ``server.py`` imports ``GeminiLiveClient`` and ``NovaClient`` at module
    level (from ``ai-parrot-client-google`` / ``-amazon``) purely to read each
    provider's ``voice_capabilities`` descriptor for the UI panel.  Neither is
    involved in broadcast wiring, so when the satellites are missing these
    stubs let the example import and the FEAT-537 wiring actually be tested,
    instead of adding a third un-runnable module (``test_voice_demo_assets.py``
    and ``test_voice_demo_avatar_browser.py`` already fail to collect for
    exactly this reason).

    Installed per test via ``monkeypatch.setitem`` so they are reverted
    afterwards — a process-global install would change how *other* test
    modules import and is exactly the kind of cross-test pollution that makes
    a suite order-dependent.

    Returns:
        ``{module_name: module}`` to install, or ``None`` when the real
        clients are importable.
    """
    try:
        import parrot.clients.google.live  # noqa: F401
        import parrot.clients.amazon.nova  # noqa: F401
    except Exception:  # noqa: BLE001
        pass
    else:
        return None

    from parrot.models.voice import AudioFormat, VoiceCapabilities, VoiceProvider

    def _caps(provider: Any, voice: str) -> Any:
        return VoiceCapabilities(
            provider=provider,
            native_stt_only=True,
            supports_top_p=True,
            supports_per_call_voice=True,
            supports_per_call_inference=True,
            parallel_tool_execution=True,
            emits_reconnect_signal=True,
            supports_session_resumption=True,
            max_session_seconds=None,
            max_output_tokens=4096,
            input_formats=frozenset({AudioFormat.PCM_16K}),
            output_formats=frozenset({AudioFormat.PCM_24K}),
            input_sample_rates=frozenset({16000}),
            output_sample_rates=frozenset({24000}),
            voice_catalog=frozenset({voice}),
            default_voice=voice,
        )

    class _StubGemini:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            pass

        @property
        def voice_capabilities(self) -> Any:
            return _caps(VoiceProvider.GOOGLE_LIVE, "Puck")

    class _StubNova:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            pass

        @property
        def voice_capabilities(self) -> Any:
            return _caps(VoiceProvider.NOVA, "matthew")

    google_pkg = types.ModuleType("parrot.clients.google")
    google_live = types.ModuleType("parrot.clients.google.live")
    google_live.GeminiLiveClient = _StubGemini  # type: ignore[attr-defined]
    amazon_pkg = types.ModuleType("parrot.clients.amazon")
    amazon_nova = types.ModuleType("parrot.clients.amazon.nova")
    amazon_nova.NovaClient = _StubNova  # type: ignore[attr-defined]
    return {
        "parrot.clients.google": google_pkg,
        "parrot.clients.google.live": google_live,
        "parrot.clients.amazon": amazon_pkg,
        "parrot.clients.amazon.nova": amazon_nova,
    }


def _load_server_module(name: str = "voice_demo_server_broadcast"):
    """Import the example server module by file path."""
    spec = importlib.util.spec_from_file_location(name, _SERVER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def server_module(monkeypatch: pytest.MonkeyPatch):
    """A freshly imported server module with a clean broadcast environment.

    Client stubs (when needed) are installed through ``monkeypatch`` so they
    disappear with the test and cannot change how any other module imports.
    """
    for name in (
        "VOICEBOT_BROADCAST_REDIS_URL",
        "VOICEBOT_DEMO_PARTICIPANTS",
        "VOICEBOT_BROADCAST_FAILURE_HOOK",
        "VOICEBOT_BROADCAST_WORKER_ID",
    ):
        monkeypatch.delenv(name, raising=False)

    stubs = _client_stub_modules()
    if stubs:
        for name, module in stubs.items():
            monkeypatch.setitem(sys.modules, name, module)
    module_name = f"voice_demo_server_broadcast_{id(monkeypatch)}"
    monkeypatch.setitem(sys.modules, module_name, types.ModuleType(module_name))
    loaded = _load_server_module(module_name)
    monkeypatch.setitem(sys.modules, module_name, loaded)
    return loaded


# ── Nova configuration ─────────────────────────────────────────────────────


def test_nova_voice_config_explicit(server_module) -> None:
    """Every field the LiveAvatar bridge depends on is stated, not defaulted."""
    from parrot.models.voice import VoiceProvider

    if not server_module.NOVA_AVAILABLE:
        # The factory guards on the SDK; assert the config it *would* build by
        # reading the source instead of skipping the check entirely.
        source = _SERVER_PATH.read_text()
        assert 'model="nova-2-sonic"' in source
        assert "input_sample_rate=16_000" in source
        assert "output_sample_rate=24_000" in source
        assert 'voice_name="matthew"' in source
        return

    config = server_module.make_nova_bot().voice_config
    assert config.provider is VoiceProvider.NOVA
    assert config.model == "nova-2-sonic"
    assert config.voice_name == "matthew"
    assert config.input_sample_rate == 16_000
    assert config.output_sample_rate == 24_000


# ── Demo participant table ─────────────────────────────────────────────────


def test_demo_participants_parsing(server_module, monkeypatch) -> None:
    monkeypatch.setenv(
        "VOICEBOT_DEMO_PARTICIPANTS", "alice:tokA, bob:tokB ,,broken,carol:tokC"
    )
    table = server_module._demo_participants()
    # Keyed by token, so a participant *name* can never be used as a credential.
    assert table == {"tokA": "alice", "tokB": "bob", "tokC": "carol"}


def test_demo_participants_empty_by_default(server_module) -> None:
    assert server_module._demo_participants() == {}


async def test_demo_token_validator_matches_the_http_table(server_module) -> None:
    """One table authenticates both transports."""
    table = {"tokA": "alice"}
    validator = server_module.make_demo_token_validator(table)
    user = await validator.validate("tokA")
    assert user is not None
    assert user.user_id == "alice"
    assert await validator.validate("wrong") is None


async def test_demo_principal_resolver_requires_a_bearer_token(
    server_module,
) -> None:
    resolve = server_module.make_demo_principal_resolver({"tokA": "alice"})

    class _Request:
        headers: Dict[str, str] = {}

    with pytest.raises(web.HTTPUnauthorized):
        await resolve(_Request(), "voice-assistant")

    class _Good(_Request):
        headers = {"Authorization": "Bearer tokA"}

    principal = await resolve(_Good(), "voice-assistant")
    assert principal.user_id == "alice"
    assert principal.tenant_id == "demo"
    assert principal.agent_id == "voice-assistant"
    assert principal.display_name == "Alice"


# ── Availability and configuration block ───────────────────────────────────


async def test_broadcast_unavailable_without_redis(server_module, aiohttp_client) -> None:
    """The single-user demo keeps working; the page is told why."""
    app = server_module.build_app()
    client = await aiohttp_client(app)

    response = await client.get("/")
    assert response.status == 200
    html = await response.text()
    config = _extract_config(html)
    assert config["broadcast"]["available"] is False
    assert "VOICEBOT_BROADCAST_REDIS_URL" in config["broadcast"]["unavailableReason"]
    # The pre-FEAT-537 routes are untouched.
    assert config["providers"]["gemini"]["wsPath"] == "/ws/gemini"
    assert config["providers"]["nova"]["wsPath"] == "/ws/nova"


def _extract_config(html: str) -> Dict[str, Any]:
    """Pull the templated ``window.__CONFIG__`` object out of the page."""
    # Anchored on the JSON object, not on the bare token: the page's own
    # comments mention `window.__CONFIG__` several times before the templated
    # assignment.
    match = re.search(r"window\.__CONFIG__ = (?=\{)", html)
    assert match is not None, "templated __CONFIG__ assignment not found"
    config, _end = json.JSONDecoder().raw_decode(html[match.end():])
    return config


def _walk(value: Any) -> List[Any]:
    """Flatten every scalar in a nested structure."""
    if isinstance(value, dict):
        out: List[Any] = []
        for key, item in value.items():
            out.append(key)
            out.extend(_walk(item))
        return out
    if isinstance(value, (list, tuple)):
        out = []
        for item in value:
            out.extend(_walk(item))
        return out
    return [value]


async def test_config_broadcast_block_has_no_tokens(
    server_module, aiohttp_client, monkeypatch
) -> None:
    """Participant NAMES reach the page; their tokens never do."""
    monkeypatch.setenv("VOICEBOT_DEMO_PARTICIPANTS", "alice:super-secret-a,bob:tok-b")
    app = server_module.build_app()
    client = await aiohttp_client(app)
    html = await (await client.get("/")).text()
    config = _extract_config(html)

    assert config["broadcast"]["demoParticipants"] == ["alice", "bob"]
    scalars = {str(value) for value in _walk(config)}
    assert "super-secret-a" not in scalars
    assert "tok-b" not in scalars
    assert "super-secret-a" not in html
    assert "tok-b" not in html


async def test_config_block_shape(server_module, aiohttp_client) -> None:
    app = server_module.build_app()
    client = await aiohttp_client(app)
    config = _extract_config(await (await client.get("/")).text())
    block = config["broadcast"]
    assert block["agentId"] == "voice-assistant"
    assert block["apiPrefix"] == (
        "/api/v1/agents/voice-assistant/voice-broadcasts"
    )
    assert block["wsPath"] == (
        "/ws/voice/broadcast/voice-assistant/{broadcast_id}"
    )
    assert block["maxViewers"] == 10


# ── Enabled broadcast mode (in-memory registry) ────────────────────────────


class _FakeMediaSession:
    def __init__(self, descriptor, registry, room_manager, worker_id, owner_epoch, **_kw):
        self.descriptor = descriptor
        self.registry = registry
        self.owner_epoch = owner_epoch
        self.output_epoch = 0
        self.floor_epoch = descriptor.floor_epoch
        self.room_name = descriptor.room_name or "room"
        self.avatar_identity = "avatar-x"
        self.direct_identity = "direct-x"

    async def start(self):
        from parrot.integrations.liveavatar.broadcast import BroadcastState

        await self.registry.transition(
            self.descriptor.tenant_id, self.descriptor.broadcast_id,
            BroadcastState.STARTING, expected_owner_epoch=self.owner_epoch,
        )
        await self.registry.transition(
            self.descriptor.tenant_id, self.descriptor.broadcast_id,
            BroadcastState.AVATAR, output_epoch=1,
            expected_owner_epoch=self.owner_epoch,
        )
        return BroadcastState.AVATAR

    def media_state(self):
        return {
            "room_name": self.room_name,
            "avatar_identity": self.avatar_identity,
            "direct_identity": self.direct_identity,
            "state": "avatar",
            "output_epoch": self.output_epoch,
            "floor_epoch": self.floor_epoch,
            "reason": None,
            "liveavatar_session_id": None,
        }

    async def switch_speaker(self, lease_id, floor_epoch):
        self.floor_epoch = floor_epoch

    async def aclose(self, **_kw):
        return None


class _FakeVoiceSession:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def set_fanout(self, fanout):
        return None

    async def close(self):
        return None


class _FakeRoomManager:
    url = "wss://fake.livekit.cloud"

    async def create_room(self, room, *, max_participants=12):
        return None

    def mint_publisher_token(self, room, identity, **_kw):
        return f"pub-{identity}"

    def mint_viewer_token(self, room, identity, *, ttl_s=60):
        return f"viewer-{identity}"

    async def list_participant_identities(self, room):
        return []

    async def remove_participant(self, room, identity):
        return None

    async def delete_room(self, room):
        return None


def _ensure_server_handler(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make this worktree's ``parrot.handlers.voice_broadcast`` importable.

    Worktree artifact, not a product concern: the editable install resolves
    ``parrot.handlers`` to the **main checkout**, which has no
    ``voice_broadcast`` module, and once another test module has imported
    ``parrot.handlers`` the package's ``__path__`` is already fixed — so a
    module-level ``sys.path`` insert only works when this file happens to run
    first.  Extending ``__path__`` here makes the test order-independent, and
    ``monkeypatch`` puts it back afterwards.
    """
    import importlib

    try:
        importlib.import_module("parrot.handlers.voice_broadcast")
    except ModuleNotFoundError:
        handlers = importlib.import_module("parrot.handlers")
        worktree_handlers = str(_SERVER_PKG_SRC / "parrot" / "handlers")
        if worktree_handlers not in handlers.__path__:
            monkeypatch.setattr(
                handlers,
                "__path__",
                list(handlers.__path__) + [worktree_handlers],
            )


@pytest.fixture
def broadcast_app(server_module, monkeypatch):
    """The example app with broadcast mode enabled over in-memory fakes."""
    from parrot.integrations.liveavatar.broadcast import InMemoryBroadcastRegistry
    from parrot.integrations.liveavatar.broadcast import service as service_module
    from parrot.integrations.liveavatar.broadcast import redis_registry

    _ensure_server_handler(monkeypatch)
    monkeypatch.setenv("VOICEBOT_BROADCAST_REDIS_URL", "redis://unused/0")
    monkeypatch.setenv("VOICEBOT_DEMO_PARTICIPANTS", "alice:tokA,bob:tokB")
    monkeypatch.setattr(server_module, "NOVA_AVAILABLE", True)
    monkeypatch.setattr(
        redis_registry.RedisBroadcastRegistry,
        "from_url",
        classmethod(lambda cls, *a, **kw: InMemoryBroadcastRegistry()),
    )
    monkeypatch.setattr(
        server_module, "make_nova_bot", lambda: None, raising=False
    )

    real_service = service_module.BroadcastService

    def _patched(*args, **kwargs):
        kwargs.setdefault("session_factory", _FakeMediaSession)
        kwargs.setdefault("voice_session_factory", _FakeVoiceSession)
        return real_service(*args, **kwargs)

    monkeypatch.setattr(service_module, "BroadcastService", _patched)

    import parrot.integrations.liveavatar.room_manager as room_manager_module

    monkeypatch.setattr(
        room_manager_module, "LiveKitRoomManager", _FakeRoomManager
    )
    return server_module.build_app()


async def test_broadcast_routes_are_mounted(broadcast_app, aiohttp_client) -> None:
    client = await aiohttp_client(broadcast_app)
    config = _extract_config(await (await client.get("/")).text())
    assert config["broadcast"]["available"] is True
    assert config["broadcast"]["unavailableReason"] is None

    paths = {
        getattr(route.resource, "canonical", "")
        for route in broadcast_app.router.routes()
    }
    # Registered as a TEMPLATE so `match_info["agent_id"]` resolves, exactly as
    # in production; the browser calls the concrete path in `apiPrefix`.
    assert "/api/v1/agents/{agent_id}/voice-broadcasts" in paths
    assert "/ws/voice/broadcast/{agent_id}/{broadcast_id}" in paths
    # The single-user routes are still there.
    assert "/ws/gemini" in paths
    assert "/ws/nova" in paths


async def test_demo_bearer_required(broadcast_app, aiohttp_client) -> None:
    client = await aiohttp_client(broadcast_app)
    url = "/api/v1/agents/voice-assistant/voice-broadcasts"

    response = await client.post(url, json={})
    assert response.status == 401

    response = await client.post(
        url, json={}, headers={"Authorization": "Bearer wrong"}
    )
    assert response.status == 401

    response = await client.post(
        url, json={}, headers={"Authorization": "Bearer tokA"}
    )
    assert response.status == 201
    body = await response.json()
    assert body["broadcast_id"].startswith("bc-")
    # Creating confers no moderator role.
    assert body["state"]["moderator_display_id"] is None


async def test_first_admitted_participant_becomes_moderator(
    broadcast_app, aiohttp_client
) -> None:
    client = await aiohttp_client(broadcast_app)
    url = "/api/v1/agents/voice-assistant/voice-broadcasts"
    created = await (
        await client.post(url, json={}, headers={"Authorization": "Bearer tokA"})
    ).json()
    bid = created["broadcast_id"]

    # bob joins first, so bob is moderator — not alice, who created it.
    first = await (
        await client.post(
            f"{url}/{bid}/viewers", json={}, headers={"Authorization": "Bearer tokB"}
        )
    ).json()
    second = await (
        await client.post(
            f"{url}/{bid}/viewers", json={}, headers={"Authorization": "Bearer tokA"}
        )
    ).json()
    assert first["role"] == "moderator"
    assert second["role"] == "viewer"


# ── Safety guards ──────────────────────────────────────────────────────────


def test_refuses_non_loopback_in_demo_mode(server_module, monkeypatch) -> None:
    """Demo tokens are config-file secrets, not credentials."""
    monkeypatch.setenv("VOICEBOT_DEMO_PARTICIPANTS", "alice:tokA")
    monkeypatch.setattr(
        server_module, "parse_args", lambda: _Args(host="0.0.0.0", port=8080)
    )
    with pytest.raises(SystemExit, match="Refusing to bind demo mode"):
        server_module.main()


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "::1"])
def test_loopback_hosts_are_accepted(server_module, monkeypatch, host: str) -> None:
    monkeypatch.setenv("VOICEBOT_DEMO_PARTICIPANTS", "alice:tokA")
    monkeypatch.setattr(
        server_module, "parse_args", lambda: _Args(host=host, port=8080)
    )
    monkeypatch.setattr(server_module, "build_app", lambda: web.Application())
    ran: List[Any] = []
    monkeypatch.setattr(
        server_module.web, "run_app", lambda *a, **kw: ran.append(kw)
    )
    server_module.main()
    assert ran


def test_no_loopback_restriction_without_demo_participants(
    server_module, monkeypatch
) -> None:
    """Real authentication in front means any bind host is the operator's call."""
    monkeypatch.setattr(
        server_module, "parse_args", lambda: _Args(host="0.0.0.0", port=8080)
    )
    monkeypatch.setattr(server_module, "build_app", lambda: web.Application())
    ran: List[Any] = []
    monkeypatch.setattr(
        server_module.web, "run_app", lambda *a, **kw: ran.append(kw)
    )
    server_module.main()
    assert ran


class _Args:
    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port


async def test_failure_hook_absent_by_default(broadcast_app, aiohttp_client) -> None:
    client = await aiohttp_client(broadcast_app)
    response = await client.post("/__demo__/broadcasts/bc-x/inject", json={})
    assert response.status == 404


async def test_failure_hook_present_only_with_the_flag(
    server_module, monkeypatch
) -> None:
    app = web.Application()
    assert server_module.register_failure_injection(app, object()) is False

    monkeypatch.setenv("VOICEBOT_BROADCAST_FAILURE_HOOK", "1")
    app2 = web.Application()
    assert server_module.register_failure_injection(app2, object()) is True
    paths = {
        getattr(route.resource, "canonical", "") for route in app2.router.routes()
    }
    assert "/__demo__/broadcasts/{broadcast_id}/inject" in paths
