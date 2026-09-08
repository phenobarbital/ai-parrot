"""Dual VoiceChatHandler provider-switch demo (FEAT-418, TASK-2178).

One aiohttp app, two :class:`~parrot.voice.handler.VoiceChatHandler`
instances mounted at ``/ws/gemini`` and ``/ws/nova``, each backed by its
own :class:`~parrot.bots.VoiceBot` — same name, same system prompt, same
tools; only :class:`~parrot.models.voice.VoiceConfig` (and therefore the
underlying provider) differs. One browser page, one push-to-talk button,
one provider toggle.

If the FEAT-418 homologation between ``GeminiLiveClient`` and
``NovaClient`` is real, flipping the toggle changes nothing the user can
perceive except the voice — that is the acceptance test a human can run
end to end.

Why this reuses ``packages/ai-parrot-integrations/src/parrot/voice/ui/
chat.html`` instead of the raw-client static asset from TASK-2177
(``examples/clients/voice/static/index.html`` + ``app.js``, used by
``examples/clients/nova/audio.py``): ``VoiceChatHandler.handle_websocket``
speaks a real, richer WebSocket protocol (``start_session`` /
``audio_data`` / ``response_chunk`` / ``transcription`` /
``response_complete`` / ``ready_to_speak``) that is NOT compatible with
TASK-2177's deliberately simpler raw-client protocol (``start_turn`` /
``audio`` / ``text`` / ``turn_complete``) — the two UIs are for two
structurally different integration points, not interchangeable, per
TASK-2176's own "Does NOT Exist" note ("do not confuse the two or merge
them"). See ``sdd/tasks/completed/TASK-2178-provider-switch-example.md``'s
Completion Note for the full analysis. This example serves an adapted
copy of ``chat.html`` (``examples/clients/voice/static/dual_provider.html``)
that already speaks ``VoiceChatHandler``'s real protocol, with a provider
toggle, a capability panel, and per-turn usage counters layered on top.

Requirements
------------
* Google Gemini Live: ``GOOGLE_API_KEY`` (or Vertex AI credentials) resolved
  the same way ``GeminiLiveClient`` always resolves them.
* Amazon Nova 2 Sonic: AWS Bedrock credentials, and **Python >= 3.12** with
  ``pip install 'aws_sdk_bedrock_runtime[awscrt]==0.11.0'`` for the voice path.
  ``NovaClient`` itself imports and constructs fine without the SDK — it is
  only required at the first ``stream_voice()`` call. When the SDK is
  missing (e.g. Python 3.11), this example does NOT fail startup: the Nova
  route stays mounted but reports itself unavailable, both proactively (the
  browser's provider toggle is disabled with a reason) and defensively (a
  session-start attempt returns a clear WebSocket error instead of hanging).
  Voice requires SigV4 credentials with ``bedrock:InvokeModel`` permission
  on ``amazon.nova-2-sonic-v1:0`` in the selected region. This demo selects
  the ``nova_sonic`` entry in ``AWS_CREDENTIALS`` via ``aws_id``.
  To use environment credentials instead, remove that factory argument and set
  ``AWS_NOVA_SONIC_KEY_ID``, ``AWS_NOVA_SONIC_SECRET_KEY``, and
  ``AWS_NOVA_SONIC_REGION`` in ``env/.env`` (plus
  ``AWS_NOVA_SONIC_SESSION_TOKEN`` for temporary credentials), or pass
  explicit AWS credentials / ``aws_id`` to the bot factory. Otherwise the
  voice SDK uses its environment/IMDS chain. ``AWS_NOVA_API_KEY`` alone
  cannot authenticate voice: Bedrock API keys do not support
  ``InvokeModelWithBidirectionalStream``.

Usage
-----
.. code-block:: bash

    source .venv/bin/activate
    python examples/clients/voice/server.py
    python examples/clients/voice/server.py --port 9000

Then open http://localhost:8080, hold the button to talk on Gemini, flip
the toggle, hold to talk on Nova. Confirm: same agent behavior, same tool
call, only the voice differs.
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import logging
import os
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Load env/.env so AWS_NOVA_SONIC_* vars are available as os.environ defaults
# (same pattern as examples/clients/nova/audio.py — without this, VoiceBot's
# Nova credential resolution via navconfig.get() finds nothing).
# ---------------------------------------------------------------------------
_ENV_FILE = Path(__file__).resolve().parents[3] / "env" / ".env"
if _ENV_FILE.is_file():
    with open(_ENV_FILE) as _f:
        for _line in _f:
            _line = _line.strip()
            if not _line or _line.startswith("#") or "=" not in _line:
                continue
            _key, _, _val = _line.partition("=")
            os.environ.setdefault(_key.strip(), _val.strip())

from aiohttp import web
from parrot.bots import VoiceBot
from parrot.clients.google.live import GeminiLiveClient
from parrot.clients.protocols import VoiceCapable
from parrot.models.voice import VoiceCapabilities, VoiceConfig, VoiceProvider
from parrot.tools.abstract import AbstractTool, AbstractToolArgsSchema, ToolResult
from parrot.voice.handler import VoiceChatHandler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("voice.provider_switch.example")

STATIC_DIR = Path(__file__).resolve().parent / "static"
INDEX_ASSET = STATIC_DIR / "dual_provider.html"

BOT_NAME = "Assistant"
SYSTEM_PROMPT = (
    "You are a friendly voice assistant demonstrating provider parity "
    "between Google Gemini Live and Amazon Nova 2 Sonic. Keep every "
    "answer short and conversational -- two or three sentences at most. "
    "Use the get_weather tool whenever asked about the weather so a tool "
    "call is visible regardless of which provider is active."
)


# ---------------------------------------------------------------------------
# Demo tool (FEAT-536 TASK-2948 — spec §3 Module 6): a deterministic,
# voice-aware AbstractTool so BOTH providers exercise the SAME supported
# dual-output ToolResult route (voice_text + display_data), not just a
# plain string return. Both factories below instantiate their OWN fresh
# tool object — never a shared module-level singleton — so this tool's
# per-instance state (the resolved demo delay) can never leak between the
# Gemini and Nova bots, or between connections (spec: "Instantiate tools
# per bot factory; share their definition/behavior rather than mutable
# invocation state"). All returned data is a labeled demo fixture, not a
# real weather lookup.
# ---------------------------------------------------------------------------


class _WeatherArgs(AbstractToolArgsSchema):
    location: str = ""


class VoiceDemoWeatherTool(AbstractTool):
    """Deterministic weather demo tool with a bounded, opt-in slow-tool
    scenario.

    Set ``VOICEBOT_DEMO_TOOL_DELAY_SECONDS`` (clamped to
    ``[0, _MAX_DEMO_DELAY_SECONDS]``) to make this tool sleep before
    answering, so the real-live tool-interruption acceptance scenario
    (spec §4) can actually be exercised on demand — the demo runs at its
    normal (instant) speed otherwise.
    """

    name = "get_weather"
    description = "Get the current weather for a location."
    args_schema = _WeatherArgs

    _MAX_DEMO_DELAY_SECONDS = 30.0
    _DELAY_ENV_VAR = "VOICEBOT_DEMO_TOOL_DELAY_SECONDS"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._delay_seconds = self._resolve_demo_delay()

    def _resolve_demo_delay(self) -> float:
        raw = os.environ.get(self._DELAY_ENV_VAR, "0")
        try:
            value = float(raw)
        except ValueError:
            return 0.0
        return max(0.0, min(value, self._MAX_DEMO_DELAY_SECONDS))

    async def _execute(self, location: str = "", **kwargs: Any) -> ToolResult:
        if self._delay_seconds:
            await asyncio.sleep(self._delay_seconds)
        location_label = location or "your area"
        return ToolResult(
            success=True,
            status="success",
            result={"location": location_label, "condition": "sunny", "temp_c": 25},
            voice_text=f"It's sunny and 25 degrees Celsius in {location_label}.",
            display_data={
                "kind": "weather",
                "location": location_label,
                "condition": "sunny",
                "temp_c": 25,
                "demo_fixture": True,
            },
        )


# ---------------------------------------------------------------------------
# Nova SDK availability (Pre-Alpha, Python >= 3.12 only) — checked once at
# startup so the Nova route can degrade instead of failing the whole app.
# ---------------------------------------------------------------------------


def _nova_sdk_available() -> bool:
    """Whether the optional ``aws_sdk_bedrock_runtime`` package is
    importable. ``NovaClient`` itself imports and constructs fine without
    it — only its ``stream_voice()`` call needs the SDK."""
    try:
        import aws_sdk_bedrock_runtime  # noqa: F401
    except ImportError:
        return False
    return True


NOVA_AVAILABLE = _nova_sdk_available()
NOVA_UNAVAILABLE_REASON = (
    "aws_sdk_bedrock_runtime is not installed (Pre-Alpha, requires "
    "Python >= 3.12) — Nova route unavailable; the Gemini route still works."
)


# ---------------------------------------------------------------------------
# LiveKit SDK asset (FEAT-536 TASK-2943 — spec §2 "Delivering the existing
# LiveKit SDK to the standalone page"): serve the SAME locked
# `livekit-client` dependency `packages/ai-parrot-server/ui/package.json`
# already declares (^2.19.2, pnpm-lock.yaml resolves 2.22.1) from that
# package's own node_modules — never a CDN, never a different/upgraded
# version, and never node_modules at large. Missing installation degrades
# the avatar viewer only; both voice-provider WebSocket routes keep
# working regardless.
# ---------------------------------------------------------------------------

_UI_PACKAGE_DIR = Path(__file__).resolve().parents[3] / "packages" / "ai-parrot-server" / "ui"
_LIVEKIT_UMD_ROUTE = "/voice-assets/livekit-client.umd.js"


def _resolve_livekit_umd_path() -> Path | None:
    """Resolve the installed ``livekit-client`` UMD asset.

    Verified against the upstream 2.22.1 package manifest (spec §2) and
    the local lockfile: the UMD build lives at ``dist/livekit-client.umd.js``
    inside the package. Resolves through pnpm's symlinked
    ``node_modules/livekit-client`` — the real (symlink-followed) path is
    checked to still live under that same package directory, so a
    malformed/malicious symlink can never cause an unrelated file to be
    served.

    Returns:
        The resolved, existing path to the UMD asset, or ``None`` when
        the package is not installed (``pnpm install`` has not been run
        for the UI workspace) — a documented prerequisite, not a hard
        failure for this example.
    """
    package_dir = (_UI_PACKAGE_DIR / "node_modules" / "livekit-client").resolve()
    candidate = (package_dir / "dist" / "livekit-client.umd.js").resolve()
    if not candidate.is_file():
        return None
    try:
        candidate.relative_to(package_dir)
    except ValueError:
        # The resolved path escaped the package directory (e.g. a
        # tampered symlink) — refuse to serve it.
        return None
    return candidate


async def voice_assets_livekit_handler(request: web.Request) -> web.Response:  # noqa: ARG001
    """Serve the installed ``livekit-client`` UMD asset at a single,
    narrowly-scoped, EXACT route (no path parameter, so no traversal
    surface exists for this route at all — aiohttp's exact-match routing
    never dispatches ``/voice-assets/../…`` or any other URL here).

    Returns a controlled, non-crashing response when the package is not
    installed — the avatar viewer is unavailable, but both voice-provider
    WebSocket routes and the page itself keep working.
    """
    path = _resolve_livekit_umd_path()
    if path is None:
        return web.Response(
            status=503,
            text=(
                "livekit-client is not installed for the UI workspace "
                "(packages/ai-parrot-server/ui) — run its install step to "
                "enable the avatar viewer. Voice-provider routes are "
                "unaffected."
            ),
            content_type="text/plain",
        )
    return web.FileResponse(path, headers={"Content-Type": "application/javascript"})


# ---------------------------------------------------------------------------
# Bot factories — VoiceChatHandler calls bot_factory() fresh for every new
# WebSocket connection (see _handle_start_session), so each factory must
# build a brand-new VoiceBot rather than returning a shared instance.
# ---------------------------------------------------------------------------


def make_gemini_bot() -> VoiceBot:
    """Fresh VoiceBot for a new /ws/gemini connection — Google Gemini Live."""
    return VoiceBot(
        name=BOT_NAME,
        system_prompt=SYSTEM_PROMPT,
        tools=[VoiceDemoWeatherTool()],
        voice_config=VoiceConfig(provider=VoiceProvider.GOOGLE_LIVE, voice_name="Puck"),
    )


def make_nova_bot() -> VoiceBot:
    """Fresh VoiceBot for a new /ws/nova connection — Amazon Nova 2 Sonic.

    Constructing the bot never raises even when the Nova SDK is missing —
    only the first ``stream_voice()`` call does (``NovaAudio.
    _require_voice_sdk``). ``_handle_start_session()`` runs this factory
    synchronously inside ``handle_websocket``'s message loop, whose
    blanket ``except Exception`` reports any failure as a WebSocket
    ``error`` frame rather than crashing the connection — this explicit
    check turns that into an immediate, clear message instead of waiting
    for a confusing failure deeper in the turn.
    """
    if not NOVA_AVAILABLE:
        raise RuntimeError(NOVA_UNAVAILABLE_REASON)
    return VoiceBot(
        name=BOT_NAME,
        system_prompt=SYSTEM_PROMPT,
        tools=[VoiceDemoWeatherTool()],
        voice_config=VoiceConfig(provider=VoiceProvider.NOVA, voice_name="matthew"),
        aws_id="nova_sonic",
    )


# ---------------------------------------------------------------------------
# Capability panel data — read directly from each client's voice_capabilities
# descriptor (never hardcoded, so it can't silently drift, spec §3 Module 12
# Key Constraints) and serialized to JSON-safe values.
# ---------------------------------------------------------------------------


def _capabilities_to_json(caps: VoiceCapabilities) -> dict[str, Any]:
    """Convert a frozen ``VoiceCapabilities`` dataclass (which carries
    ``Enum`` members and ``frozenset``s) into a JSON-serializable dict."""
    data = dataclasses.asdict(caps)
    data["provider"] = caps.provider.value
    data["input_formats"] = sorted(f.value for f in caps.input_formats)
    data["output_formats"] = sorted(f.value for f in caps.output_formats)
    data["input_sample_rates"] = sorted(caps.input_sample_rates)
    data["output_sample_rates"] = sorted(caps.output_sample_rates)
    data["voice_catalog"] = sorted(caps.voice_catalog)
    return data


def build_capabilities() -> dict[str, Any]:
    """Instantiate a bare client per provider just to read its descriptor.

    Safe on any Python version / without credentials: both
    ``GeminiLiveClient()`` and ``NovaClient()`` resolve credentials lazily
    (only needed at the first real API call), and ``NovaClient()`` never
    needs ``aws_sdk_bedrock_runtime`` at construction time either — so the
    Nova descriptor is shown even when the Nova route itself is
    unavailable (spec: a descriptor that lies by omission is still a lie).

    These two clients are throwaways, read once for ``voice_capabilities``
    (a synchronous property) and never used again — deliberately not
    ``.close()``d. Neither constructor opens a network resource (no HTTP
    session, no socket); that only happens lazily inside ``stream_voice()``
    (see ``_ensure_client()``/``_open_stream()`` in each client), which is
    never called here.
    """
    gemini_client: VoiceCapable = GeminiLiveClient(voice_name="Puck")
    capabilities = {"gemini": _capabilities_to_json(gemini_client.voice_capabilities)}

    from parrot.clients.amazon.nova import NovaClient

    nova_client: VoiceCapable = NovaClient(model="nova-2-sonic", voice_id="matthew")
    capabilities["nova"] = _capabilities_to_json(nova_client.voice_capabilities)
    return capabilities


# ---------------------------------------------------------------------------
# aiohttp wiring
# ---------------------------------------------------------------------------


async def index_handler(request: web.Request) -> web.Response:
    """Serve the provider-switch UI, templated with provider/capability data."""
    import json

    cfg = {
        "providers": {
            "gemini": {
                "wsPath": "/ws/gemini",
                "label": "Gemini Live",
                "available": True,
                "voice": "Puck",
            },
            "nova": {
                "wsPath": "/ws/nova",
                "label": "Nova 2 Sonic",
                "available": NOVA_AVAILABLE,
                "voice": "matthew",
                "unavailableReason": None if NOVA_AVAILABLE else NOVA_UNAVAILABLE_REASON,
            },
        },
        "capabilities": request.app["capabilities"],
        # FEAT-536 TASK-2943: only the asset URL and its availability are
        # exposed here — never a credential, never a LiveAvatar/LiveKit
        # secret (those only ever reach the browser via each session's own
        # session_started.avatar viewer credentials, Module 5/TASK-2945).
        "avatar": {
            "sdkUrl": _LIVEKIT_UMD_ROUTE,
            "available": _resolve_livekit_umd_path() is not None,
        },
    }
    # Anchored to the exact bootstrap statement (`window.__CONFIG__ =
    # __CONFIG__;`), count=1 — a bare token-wide str.replace() would ALSO
    # rewrite the two other `window.__CONFIG__.providers`/`.capabilities`
    # *property accesses* further down the same script (they legitimately
    # contain the substring "__CONFIG__" as part of `window.__CONFIG__`,
    # not as the template placeholder) into invalid JavaScript, silently
    # breaking every script block on the page (code-review finding).
    html = INDEX_ASSET.read_text().replace(
        "window.__CONFIG__ = __CONFIG__;",
        f"window.__CONFIG__ = {json.dumps(cfg)};",
        1,
    )
    return web.Response(text=html, content_type="text/html")


def build_app() -> web.Application:
    """Wire two VoiceChatHandler instances (Gemini + Nova) into one app."""
    app = web.Application()
    app["capabilities"] = build_capabilities()

    gemini_handler = VoiceChatHandler(
        bot_factory=make_gemini_bot,
        ws_route="/ws/gemini",
        health_route="/health/gemini",
    )
    nova_handler = VoiceChatHandler(
        bot_factory=make_nova_bot,
        ws_route="/ws/nova",
        health_route="/health/nova",
    )

    # include_static=False: this example serves its own index route (with
    # __CONFIG__ templating) and the shared static/ directory below, rather
    # than VoiceChatHandler's generic static-file mount.
    gemini_handler.setup_routes(app, include_static=False)
    nova_handler.setup_routes(app, include_static=False)

    app.router.add_get("/", index_handler)
    app.router.add_static("/static/", path=STATIC_DIR, name="static")
    # FEAT-536 TASK-2943: single, exact, narrowly-scoped route — never a
    # prefix/static mount over node_modules (that would expose the whole
    # tree, not just the one locked asset).
    app.router.add_get(_LIVEKIT_UMD_ROUTE, voice_assets_livekit_handler)

    if not NOVA_AVAILABLE:
        logger.warning("Nova route mounted but reports unavailable: %s", NOVA_UNAVAILABLE_REASON)

    return app


def parse_args() -> argparse.Namespace:
    """Parse command-line options for the demo server."""
    parser = argparse.ArgumentParser(
        description="Dual VoiceChatHandler provider-switch demo (Gemini Live + Nova 2 Sonic)",
    )
    parser.add_argument("--host", default="localhost", help="Bind host (default: localhost)")
    parser.add_argument("--port", type=int, default=8080, help="Bind port (default: 8080)")
    return parser.parse_args()


def main() -> None:
    """Run the aiohttp provider-switch demo server."""
    args = parse_args()
    app = build_app()
    logger.info(
        "Provider-switch voice demo on http://%s:%d  (nova_available=%s)",
        args.host,
        args.port,
        NOVA_AVAILABLE,
    )
    web.run_app(app, host=args.host, port=args.port, print=None)


if __name__ == "__main__":
    main()
