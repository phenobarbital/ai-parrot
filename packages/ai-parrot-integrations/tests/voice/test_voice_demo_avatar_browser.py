"""Browser E2E tests for FEAT-536 TASK-2947 — the Voice demo's avatar
viewer lifecycle in a real Chromium page (spec §4 "Browser Unit and E2E
Tests").

Loads the ACTUAL served ``examples/clients/voice/static/dual_provider.html``
(via a real ``aiohttp`` server — ``server.build_app()``/``index_handler()``
templating runs for real) in a real headless Chromium browser via
``playwright.async_api`` + ``pytest-asyncio`` (this repo's existing
Playwright dependency, no new browser plugin). Only two boundaries are
faked, both injected via ``page.add_init_script()`` BEFORE the page's own
scripts run, so the real HTML/``VoiceChatClient``/``AvatarViewerController``
implementation is exercised unmodified:

- ``window.WebSocket`` — a scriptable fake so the test can push
  ``session_started``/``display_data``/``tool_call`` frames and inspect
  every frame the page actually sent, without a real VoiceChatHandler
  backend.
- ``window.LivekitClient`` — a fake ``{Room, RoomEvent, Track}`` surface
  (found via ``loadAvatarSdk()``'s ``if (window.LivekitClient) return
  window.LivekitClient;`` short-circuit, so the real
  ``/voice-assets/livekit-client.umd.js`` route is never fetched and no
  real LiveKit/cloud connection is made) with deterministic, test-visible
  connect/track/publish counters.

Passing these mocked provider/browser tests is not proof of a real
AWS/Gemini/LiveAvatar session (spec's own "Does NOT Exist" note) — that
real-live acceptance is TASK-2949's scope.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from pathlib import Path

import pytest
import uvloop
from aiohttp.test_utils import TestServer
from playwright.async_api import async_playwright

# Playwright's Python driver launches a Node.js subprocess
# (asyncio.create_subprocess_exec) whose default-asyncio-loop codepath
# needs a child watcher that plain asyncio only registers lazily. This
# repo installs uvloop's own (child-watcher-free) subprocess support as a
# process-wide default via parrot.utils.uv — but only the FIRST time some
# parrot module is imported, which importing examples/clients/voice/
# server.py inside a fixture does too late for THIS test's own
# pytest-asyncio event loop (already created against whatever policy was
# active at collection time). Installing uvloop's policy here, at module
# import time — before pytest-asyncio creates any test's event loop —
# makes every test in this file consistently launch Playwright's
# subprocess under uvloop's own subprocess support from the start.
asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

_REPO_ROOT = Path(__file__).resolve().parents[4]
_SERVER_PATH = _REPO_ROOT / "examples" / "clients" / "voice" / "server.py"


def _load_server_module():
    """Import examples/clients/voice/server.py by file path (same pattern
    as TASK-2943's test_voice_demo_assets.py — it is a standalone script,
    not part of any installed package)."""
    spec = importlib.util.spec_from_file_location("voice_demo_server_browser_e2e", _SERVER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------
# Fake WebSocket + fake LiveKit SDK — injected before any page script
# ---------------------------------------------------------------------

_FAKE_BOUNDARIES_INIT_SCRIPT = """
window.__wsLog = [];
window.__wsSentMessages = [];
window.__wsCounter = 0;
class FakeWebSocket {
  constructor(url) {
    this.url = url;
    this.readyState = 0;
    this._id = (window.__wsCounter += 1);
    window.__fakeWsInstance = this;
    window.__wsLog.push('construct#' + this._id);
    setTimeout(() => { this.readyState = 1; if (this.onopen) this.onopen({}); }, 0);
  }
  send(data) { window.__wsSentMessages.push(data); }
  close() { this.readyState = 3; window.__wsLog.push('close#' + this._id); if (this.onclose) this.onclose({}); }
  // Test-only: simulate a server -> client push on THIS instance.
  push(obj) { if (this.onmessage) this.onmessage({ data: JSON.stringify(obj) }); }
}
FakeWebSocket.OPEN = 1;
FakeWebSocket.CONNECTING = 0;
FakeWebSocket.CLOSED = 3;
window.WebSocket = FakeWebSocket;

class FakeTrack {
  constructor(kind) { this.kind = kind; }
  attach(el) {
    window.__attachCalls = (window.__attachCalls || 0) + 1;
    window.__lastAttachKind = this.kind;
    window.__lastAttachElId = el ? el.id : null;
  }
  detach() { window.__detachCalls = (window.__detachCalls || 0) + 1; }
}
window.__FakeTrack = FakeTrack;

window.__roomInstances = [];
class FakeRoom {
  constructor() {
    this.listeners = {};
    this.canPlaybackAudio = true;
    this._connectDelay = null; // Promise a test can install to defer connect()
    window.__roomInstances.push(this);
    window.__latestRoom = this;
    this.localParticipant = {
      publishTrack: () => { window.__publishCalls = (window.__publishCalls || 0) + 1; },
    };
  }
  on(evt, cb) { (this.listeners[evt] = this.listeners[evt] || []).push(cb); }
  async connect(url, token) {
    window.__connectCalls = (window.__connectCalls || 0) + 1;
    window.__lastConnectArgs = [url, token];
    if (this._connectDelay) { await this._connectDelay; }
  }
  async disconnect() { window.__disconnectCalls = (window.__disconnectCalls || 0) + 1; }
  removeAllListeners() { this.listeners = {}; }
  async startAudio() {
    window.__startAudioCalls = (window.__startAudioCalls || 0) + 1;
    this.canPlaybackAudio = true;
  }
  emit(evt, ...args) { (this.listeners[evt] || []).forEach((cb) => cb(...args)); }
}
window.__FakeRoom = FakeRoom;
window.LivekitClient = {
  Room: FakeRoom,
  RoomEvent: {
    TrackSubscribed: "trackSubscribed",
    TrackUnsubscribed: "trackUnsubscribed",
    Disconnected: "disconnected",
    AudioPlaybackStatusChanged: "audioPlaybackStatusChanged",
  },
  Track: { Kind: { Video: "video", Audio: "audio" } },
};
"""

_AVATAR_BLOCK = {
    "active": True,
    "livekit_url": "wss://livekit.example.com",
    "client_token": "viewer-jwt",
    "room": "room-1",
    "audio": "dual",
}


# ---------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------


@pytest.fixture
async def demo_server():
    """A real aiohttp server for the ACTUAL demo app — server.build_app()
    and index_handler()'s __CONFIG__ templating run for real."""
    module = _load_server_module()
    app = module.build_app()
    server = TestServer(app)
    await server.start_server()
    yield server
    await server.close()


@pytest.fixture
async def demo_page(demo_server):
    """A real headless Chromium page loading the actual served page, with
    only the WebSocket and LiveKit SDK boundaries faked (see module
    docstring)."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.errors = errors  # type: ignore[attr-defined]
        await page.add_init_script(_FAKE_BOUNDARIES_INIT_SCRIPT)
        await page.goto(str(demo_server.make_url("/")))
        await page.wait_for_function("window.__fakeWsInstance !== undefined", timeout=5000)
        yield page
        await browser.close()


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------


async def _push_ws_message(page, message: dict) -> None:
    await page.evaluate("window.__fakeWsInstance.push(%s)" % json.dumps(message))


async def _sent_ws_messages(page) -> list[dict]:
    raw = await page.evaluate("window.__wsSentMessages")
    return [json.loads(m) for m in raw]


async def _open_settings_and_enable_avatar(page, *, tenant_id: str = "acme") -> None:
    """Open the settings panel and check the real Avatar checkbox —
    exercises the actual UI control, not a direct state write. Enabling
    avatar while already connected (this page's own auto-connect fires at
    load) restarts the session through the EXISTING reconnect flow
    (onAvatarSettingChanged() -> teardownAvatarViewer()+reconnect()) — the
    test waits for that second socket rather than assuming none happens."""
    await page.click("#settingsBtn")
    await page.wait_for_timeout(350)  # let the slide-in transition settle
    await page.check("#avatarEnabledCheckbox")
    await page.eval_on_selector(
        "#avatarTenantId",
        "(el, v) => { el.value = v; el.dispatchEvent(new Event('change')); }",
        tenant_id,
    )
    await page.click("#closeSettings")  # the overlay would otherwise intercept later clicks
    await page.wait_for_timeout(350)
    await page.wait_for_function("window.__wsCounter >= 2", timeout=3000)
    await page.wait_for_function("window.__fakeWsInstance.readyState === 1", timeout=3000)


async def _start_avatar_session(page, *, tenant_id: str = "acme") -> dict:
    """Enable avatar, drive 'connected' -> start_session -> session_started
    (with an active avatar block), and return the sent start_session
    payload for assertions."""
    await _open_settings_and_enable_avatar(page, tenant_id=tenant_id)
    await _push_ws_message(page, {"type": "connected", "session_id": "sess-e2e"})
    await page.wait_for_timeout(50)
    sent = await _sent_ws_messages(page)
    start_session_payload = sent[-1]
    await _push_ws_message(
        page,
        {"type": "session_started", "session_id": "sess-e2e", "avatar": dict(_AVATAR_BLOCK)},
    )
    await page.wait_for_function("window.__connectCalls === 1", timeout=3000)
    return start_session_payload


async def _emit_track(page, kind: str) -> None:
    await page.evaluate(
        "(k) => { const t = new window.__FakeTrack(k); window.__latestRoom.emit('trackSubscribed', t); }",
        kind,
    )


# ── test_voice_demo_avatar_browser_request_and_tracks ─────────────────────


class TestVoiceDemoAvatarBrowserRequestAndTracks:
    @pytest.mark.asyncio
    async def test_voice_demo_avatar_browser_request_and_tracks(self, demo_page):
        page = demo_page

        start_session_payload = await _start_avatar_session(page)

        # Correct top-level request fields — never nested under "config".
        assert start_session_payload["avatar"] is True
        assert start_session_payload["tenant_id"] == "acme"
        assert "avatar" not in start_session_payload.get("config", {})

        # One subscribe-only Room, listeners registered before connect
        # (avatar-viewer.js's own unit tests already prove the ordering;
        # here we prove the ACTUAL served page wires it identically).
        assert await page.evaluate("window.__connectCalls") == 1
        assert await page.evaluate("window.__lastConnectArgs") == [
            _AVATAR_BLOCK["livekit_url"],
            _AVATAR_BLOCK["client_token"],
        ]

        await _emit_track(page, "video")
        await _emit_track(page, "audio")
        await page.wait_for_timeout(50)

        assert await page.evaluate("window.__attachCalls") == 2
        # Zero local publication — the viewer is subscribe-only.
        assert await page.evaluate("window.__publishCalls") in (None, 0)

        # Visible video state + status text update in the ACTUAL DOM.
        assert await page.is_visible("#avatarCard")
        assert await page.is_visible("#avatarVideo")
        assert await page.inner_text("#avatarStatusText") == "Avatar live"
        assert await page.evaluate("document.getElementById('avatarVideo').muted") is True

        assert page.errors == []  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_text_tool_and_display_panels_update(self, demo_page):
        """Text/tool/display panels update from fake events regardless of
        avatar state — proven on the actual served page's DOM, not a
        hand-written stand-in."""
        page = demo_page
        await _push_ws_message(page, {"type": "connected", "session_id": "sess-e2e"})
        await page.wait_for_timeout(50)
        await _push_ws_message(page, {"type": "session_started", "session_id": "sess-e2e"})
        await page.wait_for_timeout(50)

        await _push_ws_message(page, {"type": "display_data", "data": {"topic": "weather", "kind": "echo"}})
        await _push_ws_message(
            page,
            {
                "type": "tool_call",
                "name": "voice_echo",
                "arguments": {"topic": "weather"},
                "result": {"output": "Echo: weather"},
                "execution_time_ms": 12.3,
            },
        )
        await page.wait_for_timeout(50)

        assert await page.is_visible("#toolEventsPanel")
        panel_text = await page.inner_text("#toolEventsList")
        assert "weather" in panel_text
        assert "voice_echo" in panel_text
        # textContent/JSON only — never raw HTML from a tool payload.
        assert await page.eval_on_selector("#toolEventsList", "el => el.querySelector('script') === null")
        assert page.errors == []  # type: ignore[attr-defined]


# ── test_voice_demo_browser_audio_and_autoplay ────────────────────────────


class TestVoiceDemoBrowserAudioAndAutoplay:
    @pytest.mark.asyncio
    async def test_voice_demo_browser_audio_and_autoplay(self, demo_page):
        page = demo_page
        await _start_avatar_session(page)
        await _emit_track(page, "audio")
        await page.wait_for_timeout(50)

        # Track playable by default (fake room.canPlaybackAudio=true) ->
        # single-source switch already happened.
        assert await page.evaluate("document.getElementById('avatarAudio').muted") is False
        assert await page.locator("#avatarAudioSourceSelect").input_value() == "avatar"

        # Autoplay denied: flip canPlaybackAudio false and re-fire the
        # status-changed event -> the fallback continues and the "Enable
        # avatar audio" affordance appears.
        await page.evaluate("window.__latestRoom.canPlaybackAudio = false")
        await page.evaluate("window.__latestRoom.emit('audioPlaybackStatusChanged')")
        await page.wait_for_timeout(50)
        assert await page.is_visible("#avatarEnableAudioBtn")

        # User enable-audio click -> Room.startAudio() -> playable again ->
        # switches back to avatar output.
        await page.click("#avatarEnableAudioBtn")
        await page.wait_for_timeout(50)
        assert await page.evaluate("window.__startAudioCalls") == 1
        assert await page.locator("#avatarAudioSourceSelect").input_value() == "avatar"
        assert await page.evaluate("document.getElementById('avatarAudio').muted") is False

        # Explicit mute silences the avatar element and must not be
        # undone by an automatic playback-status re-fire.
        await page.click("#avatarMuteBtn")
        await page.wait_for_timeout(50)
        assert await page.evaluate("document.getElementById('avatarAudio').muted") is True
        await page.evaluate("window.__latestRoom.emit('audioPlaybackStatusChanged')")
        await page.wait_for_timeout(50)
        assert await page.evaluate("document.getElementById('avatarAudio').muted") is True

        assert page.errors == []  # type: ignore[attr-defined]


# ── test_voice_demo_browser_stale_room_cleanup ────────────────────────────


class TestVoiceDemoBrowserStaleRoomCleanup:
    @pytest.mark.asyncio
    async def test_voice_demo_browser_stale_room_cleanup(self, demo_page):
        """A deferred room.connect() from a superseded generation, rapid
        provider changes, Avatar off and page teardown must never leave
        two live rooms, attach stale media, or throw."""
        page = demo_page
        await _open_settings_and_enable_avatar(page)

        # Install a controllable delay on the NEXT room's connect() before
        # triggering session_started — this is the deferred-connect case.
        await page.evaluate(
            "() => { window.__nextConnectResolve = null;"
            " window.__connectDelayPromise = new Promise((r) => { window.__nextConnectResolve = r; });"
            " const OrigRoom = window.__FakeRoom;"
            " window.LivekitClient.Room = class extends OrigRoom {"
            "   constructor() { super(); this._connectDelay = window.__connectDelayPromise; }"
            " };"
            "}"
        )
        await _push_ws_message(page, {"type": "connected", "session_id": "sess-stale"})
        await page.wait_for_timeout(50)
        await _push_ws_message(
            page, {"type": "session_started", "session_id": "sess-stale", "avatar": dict(_AVATAR_BLOCK)}
        )
        await page.wait_for_timeout(50)
        stale_room_count_before = await page.evaluate("window.__roomInstances.length")
        assert stale_room_count_before == 1

        # Avatar-off BEFORE the deferred connect() resolves — this must
        # tear down the (still-connecting) viewer. Reopen settings first —
        # _open_settings_and_enable_avatar() closes the panel on its way
        # out, and the checkbox is not actionable while off-canvas.
        await page.click("#settingsBtn")
        await page.wait_for_timeout(350)
        await page.uncheck("#avatarEnabledCheckbox")
        await page.click("#closeSettings")
        await page.wait_for_timeout(50)

        # Now let the stale connect() resolve.
        await page.evaluate("window.__nextConnectResolve()")
        await page.wait_for_timeout(100)

        # The stale room must have been disconnected, not left live, and
        # no late media may have attached from it.
        assert await page.evaluate("window.__disconnectCalls") >= 1
        assert await page.is_visible("#avatarCard") is False
        assert await page.evaluate("document.getElementById('avatarVideo').srcObject") is None

        # A late trackSubscribed replayed against the STALE room's own
        # captured listeners must not attach media (generation guard).
        stale_room_handle = "window.__roomInstances[0]"
        await page.evaluate(
            "(sel) => {"
            " const room = eval(sel);"
            " const t = new window.__FakeTrack('video');"
            " room.emit('trackSubscribed', t);"
            "}",
            stale_room_handle,
        )
        await page.wait_for_timeout(50)
        assert await page.evaluate("window.__attachCalls") in (None, 0)

        assert page.errors == []  # type: ignore[attr-defined]


# ── test_voice_demo_browser_interrupt_and_fallback ────────────────────────


class TestVoiceDemoBrowserInterruptAndFallback:
    @pytest.mark.asyncio
    async def test_voice_demo_browser_interrupt_and_fallback(self, demo_page):
        """Ordinary voice survives an unavailable avatar/SDK, and the
        explicit Interrupt control sends the EXISTING start_recording
        message and clears queued local audio."""
        page = demo_page

        # Missing/inactive avatar leaves ordinary voice usable.
        await _open_settings_and_enable_avatar(page)
        await _push_ws_message(page, {"type": "connected", "session_id": "sess-fallback"})
        await page.wait_for_timeout(50)
        await _push_ws_message(
            page,
            {
                "type": "session_started",
                "session_id": "sess-fallback",
                "avatar": {"active": False, "reason": "avatar mode is not enabled for this tenant"},
            },
        )
        await page.wait_for_timeout(50)
        # The avatar never actually joins a room when the server reports
        # it inactive — this is the acceptance-critical guarantee here
        # (ordinary voice must not be blocked on it).
        assert await page.evaluate("window.__connectCalls") in (None, 0)
        assert await page.inner_text("#avatarStatusText") != "Avatar live"
        # Post-code-review fix: teardownAvatarViewer({preserveStatusText:
        # true}) no longer clobbers handleAvatarSessionStarted()'s more
        # specific "Avatar unavailable: <reason>" message with its own
        # generic "Avatar off" text — the actual reason must reach the
        # visible panel.
        status_text = await page.inner_text("#avatarStatusText")
        assert "unavailable" in status_text.lower()
        # Never leak internal reasons that could resemble credentials —
        # nothing token/secret-shaped appears in the visible panel,
        # regardless of which of the two messages above ends up shown.
        for forbidden in ("client_token", "api_key", "livekit_url"):
            assert forbidden not in status_text

        # Ordinary voice text/response panel still works without avatar.
        await _push_ws_message(page, {"type": "response_chunk", "text": "Hello there", "audio_base64": ""})
        await page.wait_for_timeout(50)
        assert "Hello there" in await page.inner_text("#chatContainer")

        # Queue a local PCM chunk (simulates in-flight WebSocket audio)
        # then interrupt — it must be cleared, and the EXISTING
        # start_recording message sent (no new protocol message).
        await page.evaluate("voiceChat.audioPlaybackQueue = [new Int16Array([1, 2, 3]).buffer]")
        await page.evaluate("voiceChat.setInterruptEnabled(true)")
        await page.click("#interruptBtn")
        await page.wait_for_timeout(50)

        sent = await _sent_ws_messages(page)
        assert any(m.get("type") == "start_recording" for m in sent)
        assert await page.evaluate("voiceChat.audioPlaybackQueue.length") == 0

        assert page.errors == []  # type: ignore[attr-defined]
