"""End-to-end Nova 2 Sonic voice chat — aiohttp server + push-to-talk web UI.

A single-file, self-contained demo of
:meth:`parrot.clients.amazon.nova.audio.NovaAudio.stream_voice` (``NovaClient``)
driven straight from a browser microphone. No ``VoiceBot``, no
``VoiceChatHandler`` — the WebSocket handler talks to the raw client so the
client contract is visible end to end::

    browser mic (PCM 16-bit / 16 kHz / mono)
        │  WebSocket JSON  {"type": "audio", "data": "<base64>"}
        ▼
    VoiceSession (core)  ──►  asyncio.Queue[bytes | None]  ──►  audio_iterator
        │                                                        │
        │                          NovaClient.stream_voice(audio_iterator)
        │                                                        │
        │                                LiveVoiceResponse(text=…, audio_data=…)
        ▼
    WebSocket JSON  {"type": "text"|"audio", …}
        │
        ▼
    browser: chat bubbles + Web Audio playback (PCM 16-bit / 24 kHz / mono)

The push-to-talk web UI itself (HTML/CSS/JS) is a static asset shared with
the provider-switch example — see ``examples/clients/voice/static/``.

Turn model
----------
``stream_voice()`` returns when Nova Sonic emits ``completionEnd`` /
``END_TURN``, so **one push-to-talk press == one ``stream_voice()`` call**.
Each press opens a fresh bidirectional stream with a fresh audio queue;
releasing the button pushes the ``None`` end-of-turn sentinel that
``NovaAudio._audio_sender`` translates into a ``contentEnd`` event frame.

Requirements
------------
* **Python >= 3.12** — the voice path needs the Pre-Alpha AWS SDK::

      pip install 'aws_sdk_bedrock_runtime==0.7.0'

  ``NovaClient`` itself imports fine on 3.11; the SDK is only required at the
  first ``stream_voice()`` call (see ``NovaAudio._require_voice_sdk``).
* AWS credentials with Bedrock access to ``amazon.nova-2-sonic-v1:0`` in the
  target region, resolved by ``BedrockConverseBase`` from
  ``parrot.conf::AWS_CREDENTIALS`` (or pass ``--aws-id <profile>``).
* A browser with ``AudioWorklet`` support, served over ``localhost`` or HTTPS
  (``getUserMedia`` is blocked on plain HTTP origins).

Usage
-----
.. code-block:: bash

    source .venv/bin/activate
    python examples/clients/nova/audio.py
    python examples/clients/nova/audio.py --voice tiffany --region us-east-1
    python examples/clients/nova/audio.py --model nova-sonic --port 9000

Then open http://localhost:8080 and hold the button (or the spacebar) to talk.

Protocol reference
------------------
See ``docs/nova_voice_protocol.md`` (FEAT-408) for the full Nova Sonic event
sequence this client drives, including how ``LiveVoiceResponse.role``
distinguishes your transcription from the assistant's reply.
"""

from __future__ import annotations

import argparse
import base64
import json
import logging
import os
from pathlib import Path

from aiohttp import WSMsgType, web
from navconfig import config
from parrot.clients.amazon.nova import NovaClient
from parrot.voice.session import VoiceSession

# ---------------------------------------------------------------------------
# Load env/.env so AWS_NOVA_SONIC_* vars are available as os.environ defaults
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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
# Silence the verbose smithy/CRT debug chatter — they log full HTTP
# headers (including credentials) and every raw event-stream frame.
for _noisy in (
    "smithy_core",
    "smithy_http",
    "smithy_aws",
    "smithy_aws_event_stream",
    "awscrt",
    "botocore",
):
    logging.getLogger(_noisy).setLevel(logging.WARNING)
logger = logging.getLogger("nova.audio.example")

DEFAULT_SYSTEM_PROMPT = (
    "You are a friendly voice assistant. Keep every answer short, "
    "conversational and easy to listen to — two or three sentences at most."
)


# ---------------------------------------------------------------------------
# aiohttp handlers
# ---------------------------------------------------------------------------

# Shared push-to-talk web UI (HTML/CSS/JS), extracted from this module and
# reused as-is by the provider-switch example (FEAT-418, TASK-2178).
STATIC_DIR = Path(__file__).resolve().parents[1] / "voice" / "static"


async def index_handler(request: web.Request) -> web.Response:
    """Serve the single-page push-to-talk UI from the shared static asset."""
    cfg = {
        "model": request.app["model"],
        "voice": request.app["voice"],
        "region": request.app["region"],
        "inputSampleRate": NovaClient.INPUT_SAMPLE_RATE_HZ,
        "outputSampleRate": NovaClient.OUTPUT_SAMPLE_RATE_HZ,
        # Drives the UI copy in the shared static/app.js (headline, status
        # strings) without any provider-specific branching there — the
        # dual-provider example (TASK-2178) supplies its own label per
        # active provider.
        "providerLabel": "Nova 2 Sonic",
    }
    # Anchored to the exact bootstrap statement — a bare
    # str.replace("__CONFIG__", ...) also rewrites the substring inside
    # `window.__CONFIG__` (the JS global), producing `window.{...}` which
    # is a syntax error. Match the full statement instead (count=1).
    html = (
        (STATIC_DIR / "index.html")
        .read_text()
        .replace(
            "window.__CONFIG__ = __CONFIG__;",
            f"window.__CONFIG__ = {json.dumps(cfg)};",
            1,
        )
    )
    return web.Response(text=html, content_type="text/html")


async def websocket_handler(request: web.Request) -> web.WebSocketResponse:
    """Bridge one browser WebSocket to a core :class:`VoiceSession`."""
    ws = web.WebSocketResponse(heartbeat=30.0, max_msg_size=8 * 1024 * 1024)
    await ws.prepare(request)

    async def send_fn(payload: dict) -> None:
        if not ws.closed:
            await ws.send_json(payload)

    session = VoiceSession(
        client=request.app["client"],
        send_fn=send_fn,
        system_prompt=request.app["system_prompt"],
    )
    request.app["sessions"].add(session)
    logger.info("Browser connected — session %s", session.session_id)

    await ws.send_json(
        {
            "type": "ready",
            "session_id": session.session_id,
            "model": request.app["model"],
            "voice": request.app["voice"],
        }
    )

    try:
        async for msg in ws:
            if msg.type == WSMsgType.ERROR:
                logger.error("WebSocket error: %s", ws.exception())
                break
            if msg.type != WSMsgType.TEXT:
                continue

            try:
                payload = json.loads(msg.data)
            except json.JSONDecodeError:
                logger.warning("Ignoring non-JSON frame")
                continue

            kind = payload.get("type")
            if kind == "start_turn":
                await session.start_turn()
            elif kind == "audio":
                await session.push_audio(base64.b64decode(payload["data"]))
            elif kind == "end_turn":
                await session.end_turn()
            elif kind == "cancel_turn":
                await session.close()
            else:
                logger.warning("Unknown client frame type: %r", kind)
    finally:
        await session.close()
        request.app["sessions"].discard(session)
        logger.info("Browser disconnected — session %s", session.session_id)

    return ws


async def on_cleanup(app: web.Application) -> None:
    """Cancel live turns and close the Nova client on shutdown."""
    for session in list(app["sessions"]):
        await session.close()
    await app["client"].close()


def build_app(args: argparse.Namespace) -> web.Application:
    """Wire the ``NovaClient``, routes and shutdown hook into an app."""
    # Resolve explicit AWS credentials for Nova Sonic voice streaming.
    # The voice SDK (Pre-Alpha smithy-based) requires access key / secret key;
    # bearer tokens are not supported.  CLI flags win → env vars → None (which
    # lets BedrockConverseBase fall through to its own resolution chain).
    aws_access_key = args.aws_access_key or config.get("AWS_NOVA_SONIC_KEY_ID")
    aws_secret_key = args.aws_secret_key or config.get("AWS_NOVA_SONIC_SECRET_KEY")
    region = args.region or config.get("AWS_NOVA_SONIC_REGION")

    client = NovaClient(
        model=args.model,
        region=region,
        aws_id=args.aws_id,
        aws_access_key=aws_access_key,
        aws_secret_key=aws_secret_key,
        voice_id=args.voice,
        # Nova Sonic has no cross-region inference profiles — NovaAudio already
        # forces region_prefix=None for the voice model, this just keeps the
        # client's own default from being misleading in an audio-only example.
        region_prefix=None,
    )

    app = web.Application()
    app["client"] = client
    app["model"] = args.model
    app["voice"] = args.voice
    app["region"] = client._region
    app["system_prompt"] = args.system_prompt
    app["sessions"] = set()

    app.router.add_get("/", index_handler)
    app.router.add_get("/ws", websocket_handler)
    app.router.add_static("/static/", path=STATIC_DIR, name="static")
    app.on_cleanup.append(on_cleanup)
    return app


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    """Parse command-line options for the demo server."""
    parser = argparse.ArgumentParser(
        description="Nova 2 Sonic voice chat — aiohttp server + push-to-talk web UI",
    )
    parser.add_argument("--host", default="localhost", help="Bind host (default: localhost)")
    parser.add_argument("--port", type=int, default=8080, help="Bind port (default: 8080)")
    parser.add_argument(
        "--model",
        default="nova-2-sonic",
        help="Nova Sonic model alias (default: nova-2-sonic; also: nova-sonic)",
    )
    parser.add_argument(
        "--voice",
        default="matthew",
        help="Nova Sonic synthesis voice, e.g. matthew, tiffany, amy (default: matthew)",
    )
    parser.add_argument("--region", default=None, help="AWS region for Bedrock Runtime")
    parser.add_argument(
        "--aws-id",
        default=None,
        help="AWS_CREDENTIALS profile name resolved by BedrockConverseBase",
    )
    parser.add_argument(
        "--aws-access-key",
        default=None,
        help="AWS access key ID (default: $AWS_NOVA_SONIC_KEY_ID from env/.env)",
    )
    parser.add_argument(
        "--aws-secret-key",
        default=None,
        help="AWS secret access key (default: $AWS_NOVA_SONIC_SECRET_KEY from env/.env)",
    )
    parser.add_argument(
        "--system-prompt",
        default=DEFAULT_SYSTEM_PROMPT,
        help="System instructions sent at the start of every turn",
    )
    return parser.parse_args()


def main() -> None:
    """Run the aiohttp voice-chat server."""
    args = parse_args()
    app = build_app(args)
    logger.info(
        "Nova 2 Sonic voice chat on http://%s:%d  (model=%s, voice=%s, region=%s)",
        args.host,
        args.port,
        args.model,
        args.voice,
        app["region"],
    )
    web.run_app(app, host=args.host, port=args.port, print=None)


if __name__ == "__main__":
    main()
