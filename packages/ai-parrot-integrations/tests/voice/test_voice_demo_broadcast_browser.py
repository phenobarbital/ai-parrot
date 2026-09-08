"""Browser tests for the demo page's broadcast mode (FEAT-537 TASK-2965).

Drives the **actual served page** in a real headless Chromium, with only three
boundaries faked: `WebSocket`, `fetch` (for the broadcast REST API) and the
LiveKit SDK.  Everything above them — the floor gate, the resampler, the role
rendering — is the real page code.

The assertions concentrate on the one property that matters most and is
easiest to regress: **an ungranted participant's microphone is never opened.**
`getUserMedia` is spied on rather than mocked away, so "never called" is a
fact about the page rather than about the test's setup.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import types
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest
import uvloop
from aiohttp.test_utils import TestServer

# Same reason (and same fix) as FEAT-536's test_voice_demo_avatar_browser.py:
# Playwright launches a Node.js subprocess whose plain-asyncio codepath needs a
# child watcher that asyncio only registers lazily, while this repo installs
# uvloop's own child-watcher-free subprocess support process-wide. Installing
# uvloop's policy here, at module import time, means every test in this file
# creates its event loop under it from the start. (Restoring the *default*
# policy instead leaves Playwright's connection task raising
# NotImplementedError from get_child_watcher on teardown.)
asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

_REPO_ROOT = Path(__file__).resolve().parents[4]
_SERVER_PATH = _REPO_ROOT / "examples" / "clients" / "voice" / "server.py"
_SERVER_PKG_SRC = _REPO_ROOT / "packages" / "ai-parrot-server" / "src"
if str(_SERVER_PKG_SRC) not in sys.path:
    sys.path.insert(0, str(_SERVER_PKG_SRC))

async_playwright = pytest.importorskip(
    "playwright.async_api", reason="playwright is required for browser tests"
).async_playwright


def _client_stub_modules() -> Optional[Dict[str, Any]]:
    """Stand-ins for the client satellites, so the example can be imported.

    Same rationale (and same per-test installation) as
    ``test_voice_demo_broadcast_backend.py``: ``server.py`` imports
    ``GeminiLiveClient``/``NovaClient`` at module level purely for the
    capability panel, and neither is involved in broadcast behaviour.
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
        def __init__(self, *_a: Any, **_kw: Any) -> None:
            pass

        @property
        def voice_capabilities(self) -> Any:
            return _caps(VoiceProvider.GOOGLE_LIVE, "Puck")

    class _StubNova:
        def __init__(self, *_a: Any, **_kw: Any) -> None:
            pass

        @property
        def voice_capabilities(self) -> Any:
            return _caps(VoiceProvider.NOVA, "matthew")

    google_live = types.ModuleType("parrot.clients.google.live")
    google_live.GeminiLiveClient = _StubGemini  # type: ignore[attr-defined]
    amazon_nova = types.ModuleType("parrot.clients.amazon.nova")
    amazon_nova.NovaClient = _StubNova  # type: ignore[attr-defined]
    return {
        "parrot.clients.google": types.ModuleType("parrot.clients.google"),
        "parrot.clients.google.live": google_live,
        "parrot.clients.amazon": types.ModuleType("parrot.clients.amazon"),
        "parrot.clients.amazon.nova": amazon_nova,
    }


def _load_server_module(name: str):
    spec = importlib.util.spec_from_file_location(name, _SERVER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# ── Faked browser boundaries ───────────────────────────────────────────────

_INIT_SCRIPT = """
window.__wsSent = [];
window.__getUserMediaCalls = 0;
window.__fetchCalls = [];

class FakeWebSocket {
  constructor(url, protocols) {
    this.url = url;
    this.protocols = protocols;
    this.readyState = 0;
    window.__lastWs = this;
    if (String(url).includes('/ws/voice/broadcast/')) window.__controlWs = this;
    setTimeout(() => { this.readyState = 1; if (this.onopen) this.onopen({}); }, 0);
  }
  send(data) { window.__wsSent.push(JSON.parse(data)); }
  close() { this.readyState = 3; if (this.onclose) this.onclose({}); }
  push(obj) { if (this.onmessage) this.onmessage({ data: JSON.stringify(obj) }); }
}
FakeWebSocket.OPEN = 1; FakeWebSocket.CONNECTING = 0; FakeWebSocket.CLOSED = 3;
window.WebSocket = FakeWebSocket;

// Spy, not a stub: "never called" must be a fact about the page.
navigator.mediaDevices = navigator.mediaDevices || {};
navigator.mediaDevices.getUserMedia = async () => {
  window.__getUserMediaCalls += 1;
  return { getTracks: () => [{ stop() {} }] };
};

// Minimal LiveKit SDK.
class FakeTrack { constructor(kind) { this.kind = kind; } attach() {} detach() {} }
class FakeRoom {
  constructor() { this.listeners = {}; this.canPlaybackAudio = true;
    this.remoteParticipants = new Map(); window.__latestRoom = this;
    this.localParticipant = { publishTrack: () => {} }; }
  on(e, cb) { (this.listeners[e] = this.listeners[e] || []).push(cb); }
  async connect() {}
  async disconnect() {}
  removeAllListeners() { this.listeners = {}; }
  async startAudio() {}
  emit(e, ...a) { (this.listeners[e] || []).forEach((cb) => cb(...a)); }
}
window.LivekitClient = {
  Room: FakeRoom,
  RoomEvent: { TrackSubscribed: "trackSubscribed", TrackUnsubscribed: "trackUnsubscribed",
               Disconnected: "disconnected", AudioPlaybackStatusChanged: "audioPlaybackStatusChanged" },
  Track: { Kind: { Video: "video", Audio: "audio" } },
};

// Broadcast REST API, driven by window.__serverState so a test can move the
// floor the way the real server would.
window.__serverState = {
  broadcast_id: "bc-test", state: "avatar", version: 1, output_epoch: 1,
  media_ready: true, selected_identity: "avatar-x", avatar_identity: "avatar-x",
  direct_identity: "direct-x", viewer_count: 1, max_viewers: 10,
  moderator_display_id: "lease-me", speaker_display_id: "lease-me",
  floor_state: "granted", floor_epoch: 1, hand_requests: [], reason: null,
};
const jsonResponse = (status, body) => ({
  ok: status >= 200 && status < 300, status,
  json: async () => body,
});
window.fetch = async (url, options = {}) => {
  window.__fetchCalls.push({ url: String(url), method: options.method || "GET",
                             headers: options.headers || {},
                             body: options.body ? JSON.parse(options.body) : null });
  const path = String(url);
  if (options.method === "POST" && path.endsWith("/voice-broadcasts")) {
    return jsonResponse(201, { broadcast_id: "bc-test", share_path: "/?broadcast=bc-test",
                               state: window.__serverState });
  }
  if (path.includes("/viewers/") && path.endsWith("/connection")) {
    return jsonResponse(200, { public_state: window.__serverState, lease_id: "lease-me",
                               livekit_url: "wss://livekit.example", room: "bcast-1",
                               client_token: "viewer-jwt", expires_at: "2030-01-01T00:00:00Z" });
  }
  if (options.method === "POST" && path.endsWith("/viewers")) {
    return jsonResponse(201, { lease_id: "lease-me", role: "moderator",
                               media_ready: true, state: window.__serverState });
  }
  if (options.method === "DELETE") return { ok: true, status: 204, json: async () => ({}) };
  if (options.method === "POST") return jsonResponse(200, { state: window.__serverState });
  return jsonResponse(200, { state: window.__serverState });
};
"""


# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture
def _stubs(monkeypatch: pytest.MonkeyPatch):
    stubs = _client_stub_modules()
    if stubs:
        for name, module in stubs.items():
            monkeypatch.setitem(sys.modules, name, module)
    return None


@pytest.fixture
async def demo_server(_stubs, monkeypatch: pytest.MonkeyPatch):
    """The real demo app, with broadcast mode advertised as available."""
    module = _load_server_module("voice_demo_server_broadcast_browser")
    app = module.build_app()
    # The page only needs the config block to say "available"; every REST call
    # is answered by the faked `fetch` above.
    app["broadcast_service"] = object()
    app["broadcast_unavailable_reason"] = None
    app["demo_participants"] = {"tok-alice": "alice"}
    server = TestServer(app)
    await server.start_server()
    yield server
    await server.close()


@pytest.fixture
async def demo_page(demo_server):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        errors: List[str] = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.errors = errors  # type: ignore[attr-defined]
        await page.add_init_script(_INIT_SCRIPT)
        await page.goto(str(demo_server.make_url("/")))
        await page.wait_for_function("window.__CONFIG__ !== undefined", timeout=5000)
        yield page
        await browser.close()


async def _enter_broadcast(page, *, speaker: bool = True) -> None:
    """Join the faked broadcast, optionally without holding the floor."""
    await page.evaluate(
        """(speaker) => {
            if (!speaker) {
                window.__serverState.speaker_display_id = 'lease-other';
                window.__serverState.moderator_display_id = 'lease-other';
            }
            window.__demoToken = 'tok-alice';
        }""",
        speaker,
    )
    await page.evaluate(
        """async () => {
            const client = window.voiceChatClient || window.__client;
            client.demoToken = 'tok-alice';
            await client.enterBroadcast({ broadcastId: 'bc-test' });
        }"""
    )
    await page.wait_for_function(
        "() => (window.voiceChatClient || window.__client).broadcastClient !== null",
        timeout=5000,
    )


# ── Tests ──────────────────────────────────────────────────────────────────


async def test_page_exposes_the_broadcast_panel(demo_page) -> None:
    assert await demo_page.locator("#broadcastPanel").count() == 1
    config = await demo_page.evaluate("window.__CONFIG__.broadcast")
    assert config["available"] is True
    assert config["agentId"] == "voice-assistant"
    assert demo_page.errors == []  # type: ignore[attr-defined]


async def test_stateful_resampler_carries_phase_across_buffers(demo_page) -> None:
    """The carried phase means buffer boundaries neither click nor drift.

    Uses 44.1 kHz — a *non-integer* ratio to 16 kHz — because that is where a
    per-buffer resampler's truncation shows up: it would emit
    ``floor(4800/2.75625)`` samples per buffer and silently lose the remainder
    every time. The signal is one continuous sine split across two buffers, so
    any discontinuity in the output is the resampler's, not the input's.
    """
    result = await demo_page.evaluate(
        """async () => {
            const bc = await import('/static/broadcast-ui.js');
            const N = 4800;
            const make = (offset) => {
                const buf = new Float32Array(N);
                for (let i = 0; i < N; i += 1) buf[i] = Math.sin((offset + i) / 200);
                return buf;
            };
            const state = bc.createResamplerState();
            const a = bc.resampleTo16k(state, make(0), 44100);
            const b = bc.resampleTo16k(state, make(N), 44100);
            const joined = Float32Array.from([...a, ...b]);
            let maxJump = 0;
            for (let i = 1; i < joined.length; i += 1) {
                maxJump = Math.max(maxJump, Math.abs(joined[i] - joined[i - 1]));
            }
            // What a NON-stateful resampler would have produced, for contrast.
            const naive = 2 * Math.floor(N / (44100 / 16000));
            return { a: a.length, b: b.length, total: joined.length, maxJump, naive,
                     pcmBytes: bc.floatToPcm16(a).byteLength };
        }"""
    )
    expected = round(2 * 4800 / (44100 / 16000))
    # No samples lost to per-buffer truncation.
    assert abs(result["total"] - expected) <= 1
    assert result["total"] > result["naive"]
    assert result["pcmBytes"] == result["a"] * 2
    # One continuous sine in, one continuous sine out: the largest
    # sample-to-sample step stays at the signal's own slope.
    assert result["maxJump"] < 0.05


async def test_resampler_passes_through_at_16k(demo_page) -> None:
    result = await demo_page.evaluate(
        """async () => {
            const bc = await import('/static/broadcast-ui.js');
            const state = bc.createResamplerState();
            const input = new Float32Array(1600).fill(0.25);
            const out = bc.resampleTo16k(state, input, 16000);
            return { len: out.length, first: out[0] };
        }"""
    )
    assert result["len"] == 1600
    assert result["first"] == pytest.approx(0.25)


async def test_ungranted_participant_never_requests_microphone(demo_page) -> None:
    """AC8: no grant, no microphone — not even a permission prompt."""
    await _enter_broadcast(demo_page, speaker=False)

    talk_disabled = await demo_page.evaluate("document.getElementById('recordBtn').disabled")
    assert talk_disabled is True

    await demo_page.evaluate(
        "(window.voiceChatClient || window.__client).startRecording()"
    )
    assert await demo_page.evaluate("window.__getUserMediaCalls") == 0


async def test_ready_to_speak_does_not_enable_talk_without_floor(demo_page) -> None:
    """A generic transport frame must not override server floor permission."""
    await _enter_broadcast(demo_page, speaker=False)
    await demo_page.evaluate(
        """() => {
            const client = window.voiceChatClient || window.__client;
            client.handleMessage({ type: 'ready_to_speak', message: 'Ready' });
        }"""
    )
    assert await demo_page.evaluate("document.getElementById('recordBtn').disabled") is True

    # The same frame in single-user mode still enables Talk — unchanged.
    await demo_page.evaluate(
        """() => {
            const client = window.voiceChatClient || window.__client;
            client.broadcastMode = false;
            client.handleMessage({ type: 'ready_to_speak', message: 'Ready' });
        }"""
    )
    assert await demo_page.evaluate("document.getElementById('recordBtn').disabled") is False


async def test_granted_participant_can_talk_and_sends_floor_epoch(demo_page) -> None:
    await _enter_broadcast(demo_page, speaker=True)
    assert await demo_page.evaluate("document.getElementById('recordBtn').disabled") is False

    stamped = await demo_page.evaluate(
        """() => {
            const client = window.voiceChatClient || window.__client;
            return client.withFloorEpoch({ type: 'start_recording' });
        }"""
    )
    assert stamped["floor_epoch"] == 1


async def test_revoke_disables_talk_and_stops_capture(demo_page) -> None:
    await _enter_broadcast(demo_page, speaker=True)
    await demo_page.evaluate(
        """() => {
            const client = window.voiceChatClient || window.__client;
            client.isRecording = true;
            window.__serverState.speaker_display_id = 'lease-other';
            window.__serverState.version = 2;
            window.__controlWs.push({ type: 'broadcast_state', state: window.__serverState });
            window.__controlWs.push({ type: 'floor_revoked', floor_epoch: 2 });
        }"""
    )
    await demo_page.wait_for_function(
        "() => document.getElementById('recordBtn').disabled === true", timeout=5000
    )
    # And no audio may be emitted after the revoke.
    sent_before = await demo_page.evaluate("window.__wsSent.length")
    await demo_page.evaluate(
        """() => {
            const client = window.voiceChatClient || window.__client;
            client.sendAudioChunk(new Int16Array([1, 2, 3]).buffer);
        }"""
    )
    assert await demo_page.evaluate("window.__wsSent.length") == sent_before


async def test_share_link_has_no_secrets(demo_page) -> None:
    await _enter_broadcast(demo_page, speaker=True)
    link = await demo_page.evaluate(
        "(window.voiceChatClient || window.__client).broadcastClient.shareLink('https://demo.example')"
    )
    assert link == "https://demo.example/?broadcast=bc-test"
    assert "tok-alice" not in link
    assert "token" not in link


async def test_demo_token_is_never_persisted(demo_page) -> None:
    await _enter_broadcast(demo_page, speaker=True)
    storage = await demo_page.evaluate("JSON.stringify(window.localStorage)")
    assert "tok-alice" not in storage
    assert "tok-alice" not in await demo_page.evaluate("window.location.href")


async def test_stale_state_disables_talk(demo_page) -> None:
    """Losing contact with the server must mute the microphone (spec §2)."""
    await _enter_broadcast(demo_page, speaker=True)
    await demo_page.evaluate(
        """() => {
            const client = window.voiceChatClient || window.__client;
            client.broadcastClient.lastStateAt = Date.now() - 10000;
            client.broadcastClient.checkFreshness();
        }"""
    )
    assert await demo_page.evaluate("document.getElementById('recordBtn').disabled") is True


async def test_control_socket_attaches_with_the_lease(demo_page) -> None:
    await _enter_broadcast(demo_page, speaker=True)
    sent = await demo_page.evaluate("window.__wsSent")
    types_sent = [frame.get("type") for frame in sent]
    assert "attach" in types_sent
    attach = next(frame for frame in sent if frame.get("type") == "attach")
    assert attach["lease_id"] == "lease-me"
    # `start_session` attaches to the existing broadcast session; it never
    # creates a bot.
    assert "start_session" in types_sent


async def test_no_token_in_the_control_socket_url(demo_page) -> None:
    """Credentials travel in the subprotocol, never a query string."""
    await _enter_broadcast(demo_page, speaker=True)
    url = await demo_page.evaluate("window.__controlWs.url")
    protocols = await demo_page.evaluate("window.__controlWs.protocols")
    assert "tok-alice" not in url
    assert "token" not in url
    assert protocols == ["jwt", "tok-alice"]


async def test_api_calls_carry_the_bearer_token(demo_page) -> None:
    await _enter_broadcast(demo_page, speaker=True)
    calls = await demo_page.evaluate("window.__fetchCalls")
    assert calls
    assert all(
        call["headers"].get("Authorization") == "Bearer tok-alice" for call in calls
    )


async def test_no_page_errors(demo_page) -> None:
    await _enter_broadcast(demo_page, speaker=True)
    assert demo_page.errors == []  # type: ignore[attr-defined]
