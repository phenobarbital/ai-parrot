"""Shared browser fakes and fixtures for FEAT-537 multi-browser tests.

Faked boundaries and nothing else:

* **`WebSocket`** — the page's control socket. Real frames, fake transport.
* **The LiveKit SDK** — a multi-participant `FakeRoom` whose tracks carry a
  publisher `identity` and, when attached, tick per-page counters so a test can
  assert "this browser actually received media" rather than "a badge said
  connected". Spec §4 is explicit that a connected badge alone is insufficient.
* **`getUserMedia`** — a **spy**, not a stub, so "never called" is a fact about
  the page.

`fetch` is deliberately **not** faked: the REST API is the real
`register_voice_broadcast_routes` handler over a real `BroadcastService`.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path
from typing import Any, Dict, List, Optional

_REPO_ROOT = Path(__file__).resolve().parents[4]
SERVER_PATH = _REPO_ROOT / "examples" / "clients" / "voice" / "server.py"
SERVER_PKG_SRC = _REPO_ROOT / "packages" / "ai-parrot-server" / "src"
ARTIFACTS_DIR = _REPO_ROOT / "artifacts" / "logs"

if str(SERVER_PKG_SRC) not in sys.path:
    sys.path.insert(0, str(SERVER_PKG_SRC))

AGENT_ID = "voice-assistant"
TENANT_ID = "demo"
API_PREFIX = f"/api/v1/agents/{AGENT_ID}/voice-broadcasts"

#: Ten demo participants plus one over the limit, so scenario 4 can try an
#: eleventh admission with a *valid* token (an invalid one would 401 first and
#: prove nothing about the seat limit).
PARTICIPANTS: List[str] = [
    "mod", "alice", "bob", "carol", "dave", "erin", "frank", "grace", "heidi",
    "ivan", "judy",
]

DEMO_TOKENS: Dict[str, str] = {name: f"tok-{name}" for name in PARTICIPANTS}
DEMO_PARTICIPANTS_ENV: str = ",".join(
    f"{name}:{token}" for name, token in DEMO_TOKENS.items()
)


def client_stub_modules() -> Optional[Dict[str, Any]]:
    """Stand-ins for the client satellites, when they are not installed.

    ``server.py`` imports ``GeminiLiveClient``/``NovaClient`` at module level
    only to read each provider's capability descriptor for the UI panel;
    neither participates in broadcast behaviour.  Install per test with
    ``monkeypatch.setitem`` so they never leak into another module's imports.

    Returns:
        ``{module_name: module}`` to install, or ``None`` when unnecessary.
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


def load_server_module(name: str) -> Any:
    """Import ``examples/clients/voice/server.py`` by path."""
    spec = importlib.util.spec_from_file_location(name, SERVER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def ensure_server_handler(monkeypatch: Any) -> None:
    """Make this worktree's ``parrot.handlers.voice_broadcast`` importable.

    Worktree artifact: the editable install resolves ``parrot.handlers`` to the
    main checkout, and once any module has imported it the package ``__path__``
    is fixed.  Extending it here keeps these tests order-independent.
    """
    import importlib

    try:
        importlib.import_module("parrot.handlers.voice_broadcast")
    except ModuleNotFoundError:
        handlers = importlib.import_module("parrot.handlers")
        worktree = str(SERVER_PKG_SRC / "parrot" / "handlers")
        if worktree not in handlers.__path__:
            monkeypatch.setattr(
                handlers, "__path__", list(handlers.__path__) + [worktree]
            )


# ── Browser init script ────────────────────────────────────────────────────

INIT_SCRIPT = """
window.__wsSent = [];
window.__getUserMediaCalls = 0;
window.__consoleLog = [];
window.__videoFrames = 0;
window.__audioSamples = 0;
window.__attachedIdentities = [];
window.__detachCount = 0;

(() => {
  const original = console.log;
  console.log = (...args) => { window.__consoleLog.push(args.join(' ')); original(...args); };
})();

class FakeWebSocket {
  constructor(url, protocols) {
    this.url = url; this.protocols = protocols; this.readyState = 0;
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

// A spy, so "never called" is a property of the page, not of the mock.
navigator.mediaDevices = navigator.mediaDevices || {};
navigator.mediaDevices.getUserMedia = async () => {
  window.__getUserMediaCalls += 1;
  return { getTracks: () => [{ stop() {} }] };
};

// Media counters: an attached track ticks real numbers, so a test can assert
// this browser RECEIVED media rather than that a badge said "connected".
class FakeTrack {
  constructor(kind, identity) { this.kind = kind; this.__identity = identity; this._timer = null; }
  attach(el) {
    window.__attachedIdentities.push(this.__identity + ':' + this.kind);
    if (this._timer) return el;
    this._timer = setInterval(() => {
      if (this.kind === 'video') window.__videoFrames += 1;
      else window.__audioSamples += 480;
    }, 10);
    return el;
  }
  detach() {
    window.__detachCount += 1;
    if (this._timer) { clearInterval(this._timer); this._timer = null; }
  }
}
window.__FakeTrack = FakeTrack;

class FakeParticipant {
  constructor(identity) { this.identity = identity; this.trackPublications = new Map(); }
  publish(kind) {
    const track = new FakeTrack(kind, this.identity);
    this.trackPublications.set(this.identity + ':' + kind, { track });
    return track;
  }
}

class FakeRoom {
  constructor() {
    this.listeners = {}; this.canPlaybackAudio = true;
    this.remoteParticipants = new Map();
    this.localParticipant = { publishTrack: () => {} };
    window.__latestRoom = this;
  }
  on(e, cb) { (this.listeners[e] = this.listeners[e] || []).push(cb); }
  async connect() { window.__roomConnected = true; }
  async disconnect() { window.__roomConnected = false; }
  removeAllListeners() { this.listeners = {}; }
  async startAudio() { this.canPlaybackAudio = true; }
  emit(e, ...a) { (this.listeners[e] || []).forEach((cb) => cb(...a)); }
  // Test hook: a publisher joins and starts sending.
  addPublisher(identity, kinds) {
    let participant = this.remoteParticipants.get(identity);
    if (!participant) {
      participant = new FakeParticipant(identity);
      this.remoteParticipants.set(identity, participant);
    }
    for (const kind of kinds) {
      const track = participant.publish(kind);
      this.emit('trackSubscribed', track, {}, participant);
    }
  }
}
window.__FakeRoom = FakeRoom;
window.LivekitClient = {
  Room: FakeRoom,
  RoomEvent: { TrackSubscribed: "trackSubscribed", TrackUnsubscribed: "trackUnsubscribed",
               Disconnected: "disconnected", AudioPlaybackStatusChanged: "audioPlaybackStatusChanged" },
  Track: { Kind: { Video: "video", Audio: "audio" } },
};
"""


def write_measurements(scenario: str, payload: Dict[str, Any]) -> Path:
    """Write a per-scenario measurement file for the acceptance record.

    Args:
        scenario: Scenario slug.
        payload: JSON-serialisable measurements. Must contain no credentials.

    Returns:
        The path written.
    """
    from datetime import datetime, timezone

    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    target = ARTIFACTS_DIR / f"feat-537-browser-{scenario}-{stamp}.json"
    body = {
        "feature": "FEAT-537",
        "task": "TASK-2968",
        "scenario": scenario,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        **payload,
    }
    target.write_text(json.dumps(body, indent=2), encoding="utf-8")
    return target
