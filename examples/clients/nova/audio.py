"""End-to-end Nova 2 Sonic voice chat — aiohttp server + push-to-talk web UI.

A single-file, self-contained demo of
:meth:`parrot.clients.nova.audio.NovaAudio.stream_voice` (``NovaClient``)
driven straight from a browser microphone. No ``VoiceBot``, no
``VoiceChatHandler`` — the WebSocket handler talks to the raw client so the
client contract is visible end to end::

    browser mic (PCM 16-bit / 16 kHz / mono)
        │  WebSocket JSON  {"type": "audio", "data": "<base64>"}
        ▼
    NovaVoiceSession  ──►  asyncio.Queue[bytes | None]  ──►  audio_iterator
        │                                                        │
        │                          NovaClient.stream_voice(audio_iterator)
        │                                                        │
        │                                LiveVoiceResponse(text=…, audio_data=…)
        ▼
    WebSocket JSON  {"type": "text"|"audio", …}
        │
        ▼
    browser: chat bubbles + Web Audio playback (PCM 16-bit / 24 kHz / mono)

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
import asyncio
import base64
import contextlib
import json
import logging
import os
import uuid
from pathlib import Path
from typing import AsyncIterator, Optional

from aiohttp import WSMsgType, web
from navconfig import config
from parrot.clients.live import LiveVoiceResponse
from parrot.clients.nova import NovaClient

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
    "smithy_core", "smithy_http", "smithy_aws", "smithy_aws_event_stream",
    "awscrt", "botocore",
):
    logging.getLogger(_noisy).setLevel(logging.WARNING)
logger = logging.getLogger("nova.audio.example")

DEFAULT_SYSTEM_PROMPT = (
    "You are a friendly voice assistant. Keep every answer short, "
    "conversational and easy to listen to — two or three sentences at most."
)


# ---------------------------------------------------------------------------
# Voice session — one browser WebSocket <-> one Nova Sonic turn at a time
# ---------------------------------------------------------------------------

class NovaVoiceSession:
    """Bridge one browser WebSocket to ``NovaClient.stream_voice()``.

    Owns the per-turn audio queue and the task that consumes
    ``stream_voice()`` and relays each :class:`LiveVoiceResponse` back to the
    browser as a JSON frame. A single session serves many sequential turns;
    only one turn is ever in flight.

    Args:
        client: The ``NovaClient`` configured for a Nova Sonic model.
        ws: The aiohttp server-side WebSocket for this browser.
        system_prompt: System instructions sent at the start of every turn.
        session_id: Stable identifier reported back to the browser and passed
            to ``stream_voice()`` for tracking.
    """

    def __init__(
        self,
        client: NovaClient,
        ws: web.WebSocketResponse,
        system_prompt: str,
        session_id: Optional[str] = None,
    ) -> None:
        self.client = client
        self.ws = ws
        self.system_prompt = system_prompt
        self.session_id = session_id or str(uuid.uuid4())
        self.logger = logger.getChild("session")

        self._queue: Optional[asyncio.Queue[Optional[bytes]]] = None
        self._task: Optional[asyncio.Task] = None
        self._turn_no = 0

    # -- turn lifecycle ---------------------------------------------------

    async def start_turn(self) -> None:
        """Open a new Nova Sonic turn, cancelling any turn still running."""
        await self._cancel_turn()

        self._turn_no += 1
        self._queue = asyncio.Queue()
        self._task = asyncio.create_task(self._run_turn(self._turn_no))

        await self._send({
            "type": "turn_started",
            "turn": self._turn_no,
            "session_id": self.session_id,
        })

    async def push_audio(self, pcm: bytes) -> None:
        """Forward one PCM 16-bit / 16 kHz / mono chunk to the current turn."""
        if self._queue is None:
            self.logger.debug("Dropping %d audio bytes — no turn open", len(pcm))
            return
        await self._queue.put(pcm)

    async def end_turn(self) -> None:
        """Signal end-of-turn so Nova Sonic starts responding.

        Nova Sonic's VAD (voice-activity detection) ends the user turn on
        detected end-of-speech — audio that stops abruptly after the last
        spoken word gives ``userSpeechStart`` but the model never replies.
        Inject ~1.5 s of trailing silence so the VAD detects end-of-speech
        before we push the ``None`` sentinel that ``NovaAudio._audio_sender``
        turns into a ``contentEnd`` frame. The turn task keeps running until
        Nova finishes its reply.
        """
        if self._queue is not None:
            # ~1.5 s of silence at 16 kHz, 16-bit mono = 48000 bytes.
            # Sent as 1024-sample frames (~64 ms each) to match the
            # browser's AudioWorklet frame size.
            #
            # CRITICAL: pace the silence so Nova's VAD has time to detect
            # end-of-speech. Dumping all frames in a burst (~6 ms total)
            # causes the VAD to miss end-of-speech entirely — Nova sees
            # userSpeechStart but never fires end-of-speech, so it never
            # replies (confirmed by 55 s idle timeout with 0 output
            # tokens). The working sonic_e2e_demo.py paces every frame at
            # 20 ms; we use the same rate here (~3× real-time for 64 ms
            # frames). Total wall-clock cost: ~460 ms.
            silence_frame = b"\x00\x00" * 1024
            num_frames = int(NovaClient.INPUT_SAMPLE_RATE_HZ * 1.5 / 1024)
            qsize_before = self._queue.qsize()
            for _ in range(num_frames):
                await self._queue.put(silence_frame)
                await asyncio.sleep(0.02)
            await self._queue.put(None)
            self.logger.info(
                "end_turn: pushed %d silence frames + None "
                "(queue was %d, now %d)",
                num_frames, qsize_before, self._queue.qsize(),
            )
        else:
            self.logger.warning("end_turn: _queue is None — nothing pushed")

    async def close(self) -> None:
        """Tear down any in-flight turn (browser disconnected)."""
        await self._cancel_turn()

    async def _cancel_turn(self) -> None:
        if self._task is not None and not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        self._task = None
        self._queue = None

    # -- Nova Sonic plumbing ---------------------------------------------

    async def _audio_iterator(
        self,
        queue: asyncio.Queue[Optional[bytes]],
    ) -> AsyncIterator[bytes]:
        """Yield queued PCM chunks forever, until the turn task is cancelled.

        Deliberately does **not** stop on the ``None`` sentinel: ``None`` marks
        end-of-*turn* (``contentEnd``), not end-of-stream, and the sender task
        must stay alive while Nova streams its reply back.
        ``stream_voice()``'s ``finally`` block cancels the sender for us.
        """
        while True:
            yield await queue.get()

    async def _run_turn(self, turn_no: int) -> None:
        """Consume ``stream_voice()`` for one turn and relay it to the browser."""
        queue = self._queue
        assert queue is not None  # set by start_turn() before the task starts

        self.logger.info(
            "Turn %d starting (session=%s, model=%s, voice=%s)",
            turn_no, self.session_id, self.client.model, self.client.voice_id,
        )
        try:
            async for resp in self.client.stream_voice(
                self._audio_iterator(queue),
                system_prompt=self.system_prompt,
                session_id=self.session_id,
            ):
                await self._relay(resp, turn_no)
        except asyncio.CancelledError:
            self.logger.info("Turn %d cancelled", turn_no)
            raise
        except Exception as exc:  # surface any failure to the UI
            self.logger.exception("Turn %d failed", turn_no)
            await self._send({
                "type": "error",
                "turn": turn_no,
                "message": f"{type(exc).__name__}: {exc}",
            })
        finally:
            if self._task is asyncio.current_task():
                self._queue = None

    async def _relay(self, resp: LiveVoiceResponse, turn_no: int) -> None:
        """Translate one :class:`LiveVoiceResponse` into browser JSON frames."""
        # Membership, not truthiness: a modelled AWS service error can carry an
        # empty message, and treating that as "no error" silently reports the
        # turn as complete.
        if "error" in resp.metadata:
            await self._send({
                "type": "error",
                "turn": turn_no,
                "message": resp.metadata["error"] or "Unknown Nova Sonic error",
            })
            return

        if resp.text:
            await self._send({
                "type": "text",
                "turn": turn_no,
                "text": resp.text,
                "role": resp.role,
            })

        if resp.audio_data:
            await self._send({
                "type": "audio",
                "turn": turn_no,
                "audio_base64": base64.b64encode(resp.audio_data).decode("ascii"),
                "audio_format": resp.audio_format,
                "sample_rate": self.client.OUTPUT_SAMPLE_RATE_HZ,
            })

        for call in resp.tool_calls:
            await self._send({
                "type": "tool_call",
                "turn": turn_no,
                "name": call.name,
                "arguments": call.arguments,
                "result": str(call.result) if call.result is not None else None,
                "error": call.error,
            })

        if resp.is_interrupted:
            await self._send({"type": "interrupted", "turn": turn_no})

        if resp.is_complete:
            usage = resp.usage
            if usage:
                self.logger.info(
                    "Turn %d usage: %d input / %d output / %d total tokens%s",
                    turn_no, usage.prompt_tokens, usage.completion_tokens,
                    usage.total_tokens,
                    f" ({usage.tool_calls_executed} tool call(s))"
                    if usage.tool_calls_executed else "",
                )
            await self._send({
                "type": "turn_complete",
                "turn": turn_no,
                "reconnect_required": bool(resp.metadata.get("reconnect_required")),
                "usage": {
                    "prompt_tokens": usage.prompt_tokens,
                    "completion_tokens": usage.completion_tokens,
                    "total_tokens": usage.total_tokens,
                    "tool_calls_executed": usage.tool_calls_executed,
                } if usage else None,
            })

    async def _send(self, payload: dict) -> None:
        if self.ws.closed:
            return
        with contextlib.suppress(ConnectionResetError):
            await self.ws.send_json(payload)


# ---------------------------------------------------------------------------
# aiohttp handlers
# ---------------------------------------------------------------------------

async def index_handler(request: web.Request) -> web.Response:
    """Serve the single-page push-to-talk UI."""
    cfg = {
        "model": request.app["model"],
        "voice": request.app["voice"],
        "region": request.app["region"],
        "inputSampleRate": NovaClient.INPUT_SAMPLE_RATE_HZ,
        "outputSampleRate": NovaClient.OUTPUT_SAMPLE_RATE_HZ,
    }
    html = INDEX_HTML.replace("__CONFIG__", json.dumps(cfg))
    return web.Response(text=html, content_type="text/html")


async def websocket_handler(request: web.Request) -> web.WebSocketResponse:
    """Bridge one browser WebSocket to a :class:`NovaVoiceSession`."""
    ws = web.WebSocketResponse(heartbeat=30.0, max_msg_size=8 * 1024 * 1024)
    await ws.prepare(request)

    session = NovaVoiceSession(
        client=request.app["client"],
        ws=ws,
        system_prompt=request.app["system_prompt"],
    )
    request.app["sessions"].add(session)
    logger.info("Browser connected — session %s", session.session_id)

    await ws.send_json({
        "type": "ready",
        "session_id": session.session_id,
        "model": request.app["model"],
        "voice": request.app["voice"],
    })

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
    app.on_cleanup.append(on_cleanup)
    return app


# ---------------------------------------------------------------------------
# Web UI — push-to-talk, chat transcript, PCM capture + playback
# ---------------------------------------------------------------------------

INDEX_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Nova 2 Sonic — Voice Chat</title>
<style>
  :root {
    --bg: #0b1020; --panel: #141a2e; --panel-2: #1c2440; --line: #2a3454;
    --text: #e8ecf8; --muted: #8b96b8; --accent: #6c8cff; --accent-2: #40d6b0;
    --danger: #ff6b81;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; min-height: 100vh; background: var(--bg); color: var(--text);
    font: 15px/1.5 ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
    display: flex; align-items: center; justify-content: center; padding: 20px;
  }
  .app {
    width: 100%; max-width: 720px; background: var(--panel);
    border: 1px solid var(--line); border-radius: 18px; overflow: hidden;
    display: flex; flex-direction: column; height: min(88vh, 780px);
    box-shadow: 0 24px 60px rgba(0,0,0,.45);
  }
  header {
    padding: 16px 20px; border-bottom: 1px solid var(--line);
    display: flex; align-items: center; gap: 12px; background: var(--panel-2);
  }
  header h1 { margin: 0; font-size: 16px; font-weight: 650; letter-spacing: .2px; }
  .meta { margin-left: auto; display: flex; gap: 8px; flex-wrap: wrap; }
  .tag {
    font-size: 11px; padding: 3px 9px; border-radius: 999px;
    background: rgba(108,140,255,.14); color: #b9c6ff; border: 1px solid rgba(108,140,255,.3);
    font-variant-numeric: tabular-nums;
  }
  .dot { width: 9px; height: 9px; border-radius: 50%; background: var(--danger); flex: 0 0 auto; }
  .dot.on { background: var(--accent-2); box-shadow: 0 0 10px var(--accent-2); }

  #log {
    flex: 1; overflow-y: auto; padding: 20px; display: flex;
    flex-direction: column; gap: 12px; scroll-behavior: smooth;
  }
  .bubble {
    max-width: 78%; padding: 10px 14px; border-radius: 14px;
    white-space: pre-wrap; word-wrap: break-word; animation: rise .18s ease-out;
  }
  @keyframes rise { from { opacity: 0; transform: translateY(6px); } }
  .bubble.assistant { align-self: flex-start; background: var(--panel-2); border: 1px solid var(--line); }
  .bubble.you { align-self: flex-end; background: rgba(108,140,255,.18); border: 1px solid rgba(108,140,255,.36); }
  .bubble.system {
    align-self: center; max-width: 92%; background: transparent; color: var(--muted);
    font-size: 12.5px; text-align: center; padding: 4px 8px;
  }
  .bubble.error {
    align-self: center; max-width: 92%; color: var(--danger); font-size: 13px;
    background: rgba(255,107,129,.1); border: 1px solid rgba(255,107,129,.32);
  }
  .bubble .who { display: block; font-size: 10.5px; letter-spacing: .6px; text-transform: uppercase; color: var(--muted); margin-bottom: 4px; }

  footer {
    padding: 18px 20px 22px; border-top: 1px solid var(--line); background: var(--panel-2);
    display: flex; flex-direction: column; align-items: center; gap: 10px;
  }
  #ptt {
    width: 106px; height: 106px; border-radius: 50%; border: none; cursor: pointer;
    background: linear-gradient(160deg, var(--accent), #4a63d8); color: #fff;
    font-size: 12px; font-weight: 650; letter-spacing: .5px; text-transform: uppercase;
    display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 6px;
    transition: transform .12s ease, box-shadow .12s ease, background .12s ease;
    box-shadow: 0 8px 26px rgba(108,140,255,.35); user-select: none; -webkit-user-select: none;
    touch-action: none;
  }
  #ptt svg { width: 26px; height: 26px; }
  #ptt:disabled { background: #39415e; box-shadow: none; cursor: not-allowed; color: var(--muted); }
  #ptt.recording {
    background: linear-gradient(160deg, var(--danger), #d8425a);
    transform: scale(1.06); box-shadow: 0 0 0 10px rgba(255,107,129,.16), 0 8px 30px rgba(255,107,129,.45);
  }
  #ptt.thinking { background: linear-gradient(160deg, var(--accent-2), #2ba98b); box-shadow: 0 8px 26px rgba(64,214,176,.35); }
  #status { font-size: 12.5px; color: var(--muted); min-height: 18px; text-align: center; }
  kbd {
    font: inherit; font-size: 11px; padding: 1px 5px; border-radius: 4px;
    border: 1px solid var(--line); background: var(--panel); color: var(--muted);
  }
  #disconnectBtn {
    font: inherit; font-size: 11px; font-weight: 600; padding: 5px 14px;
    border-radius: 999px; border: 1px solid rgba(255,107,129,.4); cursor: pointer;
    background: rgba(255,107,129,.12); color: var(--danger);
    transition: background .15s, border-color .15s;
  }
  #disconnectBtn:hover { background: rgba(255,107,129,.22); border-color: var(--danger); }
  #disconnectBtn.off {
    border-color: rgba(64,214,176,.4); background: rgba(64,214,176,.12);
    color: var(--accent-2);
  }
  #disconnectBtn.off:hover { background: rgba(64,214,176,.22); border-color: var(--accent-2); }
</style>
</head>
<body>
<div class="app">
  <header>
    <span class="dot" id="dot"></span>
    <h1>Nova 2 Sonic · Voice Chat</h1>
    <div class="meta">
      <span class="tag" id="tagModel"></span>
      <span class="tag" id="tagVoice"></span>
      <span class="tag" id="tagRate"></span>
      <button id="disconnectBtn">Disconnect</button>
    </div>
  </header>

  <div id="log"></div>

  <footer>
    <button id="ptt" disabled>
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
           stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/>
        <path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/>
      </svg>
      <span id="pttLabel">Connecting</span>
    </button>
    <div id="status">Hold the button or <kbd>space</kbd> to talk.</div>
  </footer>
</div>

<script>
const CONFIG = __CONFIG__;

const logEl = document.getElementById("log");
const ptt = document.getElementById("ptt");
const pttLabel = document.getElementById("pttLabel");
const statusEl = document.getElementById("status");
const dot = document.getElementById("dot");

document.getElementById("tagModel").textContent = CONFIG.model;
document.getElementById("tagVoice").textContent = "voice: " + CONFIG.voice;
document.getElementById("tagRate").textContent =
  (CONFIG.inputSampleRate / 1000) + "k in / " + (CONFIG.outputSampleRate / 1000) + "k out";

// ---------------------------------------------------------------- transcript

function addBubble(kind, text, who) {
  const el = document.createElement("div");
  el.className = "bubble " + kind;
  if (who) {
    const label = document.createElement("span");
    label.className = "who";
    label.textContent = who;
    el.appendChild(label);
  }
  el.appendChild(document.createTextNode(text || ""));
  logEl.appendChild(el);
  logEl.scrollTop = logEl.scrollHeight;
  return el;
}

let streamBubble = null;    // bubble currently being appended to
let streamText = "";
let streamRole = null;      // role of the speaker currently being streamed

function appendStream(chunk, role) {
  // A role change (e.g. USER transcription -> ASSISTANT reply) must start a
  // new bubble; consecutive same-role chunks keep streaming into one.
  if (streamBubble && role !== streamRole) closeStream();
  if (!streamBubble) {
    // role is null for providers that do not report one (spec FEAT-408) —
    // fall back to the assistant bubble in that case.
    streamBubble = role === "USER"
      ? addBubble("you", "", "You")
      : addBubble("assistant", "", "Nova");
    streamText = "";
    streamRole = role;
  }
  streamText += chunk;
  streamBubble.lastChild.nodeValue = streamText;
  logEl.scrollTop = logEl.scrollHeight;
}

function closeStream() {
  if (streamBubble && !streamText.trim()) streamBubble.remove();
  streamBubble = null;
  streamText = "";
  streamRole = null;
}

// ------------------------------------------------------------------ playback

let playCtx = null;
let playCursor = 0;          // next free slot on the playback timeline
const queuedSources = new Set(); // scheduled-but-unfinished chunks, for barge-in

function playPCM(bytes, sampleRate) {
  if (!playCtx) playCtx = new AudioContext();
  if (playCtx.state === "suspended") playCtx.resume();

  const pcm = new Int16Array(bytes.buffer, bytes.byteOffset, bytes.byteLength >> 1);
  const f32 = new Float32Array(pcm.length);
  for (let i = 0; i < pcm.length; i++) f32[i] = pcm[i] / 32768;

  const buffer = playCtx.createBuffer(1, f32.length, sampleRate);
  buffer.copyToChannel(f32, 0);
  const src = playCtx.createBufferSource();
  src.buffer = buffer;
  src.connect(playCtx.destination);

  // Schedule back-to-back so consecutive chunks neither overlap nor gap.
  const now = playCtx.currentTime;
  if (playCursor < now) playCursor = now + 0.04;
  src.start(playCursor);
  playCursor += buffer.duration;

  queuedSources.add(src);
  src.onended = () => queuedSources.delete(src);
}

function stopPlayback() {
  // Chunks are scheduled ahead of the clock, so resetting the cursor is not
  // enough — already-queued sources must be stopped for barge-in to be audible.
  for (const src of queuedSources) {
    try { src.stop(); } catch (_) { /* already finished */ }
  }
  queuedSources.clear();
  if (playCtx) playCursor = playCtx.currentTime;
}

// ------------------------------------------------------------------- capture
// AudioWorklet: downmix to mono Float32 -> Int16 PCM, batched to ~64 ms frames.

const WORKLET_SRC = `
class PCMCapture extends AudioWorkletProcessor {
  constructor() {
    super();
    this.frame = new Int16Array(1024);
    this.filled = 0;
  }
  process(inputs) {
    const channel = inputs[0] && inputs[0][0];
    if (!channel) return true;
    for (let i = 0; i < channel.length; i++) {
      const s = Math.max(-1, Math.min(1, channel[i]));
      this.frame[this.filled++] = s < 0 ? s * 0x8000 : s * 0x7fff;
      if (this.filled === this.frame.length) {
        const out = this.frame.slice();
        this.port.postMessage(out.buffer, [out.buffer]);
        this.filled = 0;
      }
    }
    return true;
  }
}
registerProcessor("pcm-capture", PCMCapture);
`;

let micCtx = null, micStream = null, micNode = null, micSource = null;

async function initMic() {
  micStream = await navigator.mediaDevices.getUserMedia({
    audio: {
      channelCount: 1,
      echoCancellation: true,
      noiseSuppression: true,
      autoGainControl: true,
    },
  });
  // Request the context at Nova's input rate — the browser resamples for us.
  micCtx = new AudioContext({ sampleRate: CONFIG.inputSampleRate });
  const url = URL.createObjectURL(new Blob([WORKLET_SRC], { type: "text/javascript" }));
  await micCtx.audioWorklet.addModule(url);
  URL.revokeObjectURL(url);

  micSource = micCtx.createMediaStreamSource(micStream);
  micNode = new AudioWorkletNode(micCtx, "pcm-capture");
  micNode.port.onmessage = (ev) => {
    if (!recording || !ws || ws.readyState !== WebSocket.OPEN) return;
    ws.send(JSON.stringify({ type: "audio", data: toBase64(new Uint8Array(ev.data)) }));
  };
  micSource.connect(micNode);
  // The worklet only gets pulled while it is wired to the destination, but a
  // straight connection would echo the microphone to the speakers — route it
  // through a muted gain node instead.
  const mute = micCtx.createGain();
  mute.gain.value = 0;
  micNode.connect(mute);
  mute.connect(micCtx.destination);

  if (micCtx.sampleRate !== CONFIG.inputSampleRate) {
    addBubble("system",
      "Heads-up: this browser gave a " + micCtx.sampleRate + " Hz capture context " +
      "instead of " + CONFIG.inputSampleRate + " Hz. Nova expects " +
      CONFIG.inputSampleRate + " Hz PCM, so audio may sound sped up or slowed down.");
  }
}

function toBase64(u8) {
  let s = "";
  for (let i = 0; i < u8.length; i += 0x8000) {
    s += String.fromCharCode.apply(null, u8.subarray(i, i + 0x8000));
  }
  return btoa(s);
}

// ----------------------------------------------------------------- websocket

let ws = null;
let recording = false;
let awaitingReply = false;
let manualDisconnect = false;
let keepaliveId = null;
let thinkingTimeout = null;
const KEEPALIVE_INTERVAL_MS = 25000;  // send silence every 25s (Nova times out at 55s)
const THINKING_TIMEOUT_MS = 60000;    // force-reset button after 60s stuck in "thinking"

function setPhase(phase, text) {
  ptt.classList.toggle("recording", phase === "recording");
  ptt.classList.toggle("thinking", phase === "thinking");
  pttLabel.textContent =
    phase === "recording" ? "Listening" :
    phase === "thinking" ? "Thinking" :
    phase === "idle" ? "Hold to talk" : "Connecting";
  ptt.disabled = phase === "offline" || phase === "thinking";
  if (text !== undefined) statusEl.textContent = text;
}

function connect() {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  ws = new WebSocket(proto + "//" + location.host + "/ws");

  ws.onopen = () => {
    dot.classList.add("on");
    setPhase("idle", "Hold the button or press space to talk.");
  };

  ws.onclose = () => {
    dot.classList.remove("on");
    recording = false;
    stopKeepAlive();
    if (manualDisconnect) {
      setPhase("offline", "Disconnected.");
    } else {
      setPhase("offline", "Disconnected — reconnecting in 2 s…");
      setTimeout(connect, 2000);
    }
  };

  ws.onerror = () => statusEl.textContent = "WebSocket error — see the browser console.";

  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    switch (msg.type) {
      case "ready":
        addBubble("system", "Session " + msg.session_id.slice(0, 8) +
                            " ready · " + msg.model + " · voice " + msg.voice);
        break;
      case "turn_started":
        statusEl.textContent = "Turn " + msg.turn + " open — speak now.";
        break;
      case "text":
        // Re-enable the button as soon as Nova starts replying — the user
        // can see the reply is streaming and should be able to start a new
        // turn (barge-in) without waiting for the full turn_complete.
        if (awaitingReply && msg.role !== "USER") {
          awaitingReply = false;
          setPhase("idle", "Nova is replying… hold to talk again.");
        }
        appendStream(msg.text, msg.role);
        break;
      case "audio":
        if (awaitingReply) {
          awaitingReply = false;
          setPhase("idle", "Nova is replying… hold to talk again.");
        }
        playPCM(base64ToBytes(msg.audio_base64), msg.sample_rate || CONFIG.outputSampleRate);
        break;
      case "tool_call":
        addBubble("system", "tool " + msg.name + "(" + JSON.stringify(msg.arguments) + ")" +
                            (msg.error ? " failed: " + msg.error : " → " + msg.result));
        break;
      case "interrupted":
        addBubble("system", "Interrupted (barge-in).");
        stopPlayback();
        closeStream();
        break;
      case "turn_complete": {
        closeStream();
        awaitingReply = false;
        clearTimeout(thinkingTimeout);
        const u = msg.usage;
        let note = "Turn " + msg.turn + " complete.";
        if (u && u.total_tokens) {
          note += " " + u.prompt_tokens + " in / " + u.completion_tokens + " out / " + u.total_tokens + " total tokens.";
          if (u.tool_calls_executed) note += " " + u.tool_calls_executed + " tool call(s).";
          addBubble("system",
            "\u{1f4ca} " + u.prompt_tokens + " input · " +
            u.completion_tokens + " output · " +
            u.total_tokens + " total tokens" +
            (u.tool_calls_executed ? " · " + u.tool_calls_executed + " tool call(s)" : ""));
        }
        if (msg.reconnect_required) {
          note += " Nova's 8-minute stream limit was reached — the next press opens a fresh stream.";
        }
        setPhase("idle", note + " Hold to talk again.");
        break;
      }
      case "error":
        awaitingReply = false;
        clearTimeout(thinkingTimeout);
        closeStream();
        if (msg.message && msg.message.includes("Timed out waiting for audio")) {
          addBubble("system", "Session timed out — Nova received no speech. Press and hold to try again.");
          setPhase("idle", "Idle timeout. Hold to talk.");
        } else {
          addBubble("error", msg.message);
          setPhase("idle", "Turn failed — see the message above.");
        }
        break;
    }
  };
}

function base64ToBytes(b64) {
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

// ------------------------------------------------------------ push-to-talk

let pendingStop = false;

async function startTalking() {
  if (recording || awaitingReply || !ws || ws.readyState !== WebSocket.OPEN) return;
  // Set recording BEFORE any await — pointerup can fire during mic init
  // and must see recording===true so stopTalking() is not a no-op.
  recording = true;
  pendingStop = false;
  setPhase("recording", "Initialising mic…");
  try {
    if (!micCtx) await initMic();
    if (micCtx.state === "suspended") await micCtx.resume();
  } catch (err) {
    recording = false;
    pendingStop = false;
    addBubble("error", "Microphone unavailable: " + err.message);
    setPhase("idle", "Hold the button or press space to talk.");
    return;
  }
  if (pendingStop) {
    // User released the button while we were initialising the mic.
    recording = false;
    pendingStop = false;
    setPhase("idle", "Hold the button or press space to talk.");
    return;
  }
  stopPlayback();
  closeStream();
  ws.send(JSON.stringify({ type: "start_turn" }));
  startKeepAlive();
  setPhase("recording", "Listening… release to send.");
  // No placeholder bubble here — the real USER transcription now arrives
  // from Nova via the "text" frame's role, rendered by appendStream().
}

function stopTalking() {
  if (!recording) return;
  pendingStop = true;
  recording = false;
  stopKeepAlive();
  if (!ws || ws.readyState !== WebSocket.OPEN) {
    setPhase("offline", "Connection dropped mid-turn.");
    return;
  }
  awaitingReply = true;
  ws.send(JSON.stringify({ type: "end_turn" }));
  setPhase("thinking", "Sent — waiting for Nova…");
  // Safety: force-reset if turn_complete never arrives.
  clearTimeout(thinkingTimeout);
  thinkingTimeout = setTimeout(() => {
    if (awaitingReply) {
      awaitingReply = false;
      closeStream();
      addBubble("system", "No reply from Nova within 60 s — resetting.");
      setPhase("idle", "Hold to talk again.");
    }
  }, THINKING_TIMEOUT_MS);
}

ptt.addEventListener("pointerdown", (e) => { e.preventDefault(); startTalking(); });
ptt.addEventListener("pointerup", () => { stopTalking(); ptt.blur(); });
ptt.addEventListener("pointercancel", stopTalking);
ptt.addEventListener("pointerleave", stopTalking);
// A focused <button> turns Space into a synthetic click, which fires neither
// pointerdown nor pointerup — always preventDefault so the key path stays ours.
ptt.addEventListener("click", (e) => e.preventDefault());

document.addEventListener("keydown", (e) => {
  if (e.code === "Space" && !e.repeat) {
    e.preventDefault();
    startTalking();
  }
});
document.addEventListener("keyup", (e) => {
  if (e.code === "Space") { e.preventDefault(); stopTalking(); }
});

// -------------------------------------------------------- keepalive (silence)
// Nova Sonic times out after 55s of no audio/interaction.  While a turn is
// open and recording, the AudioWorklet already pushes frames continuously.
// This keepalive covers the edge case where the worklet stalls or the mic
// produces no data — it sends a short silence frame every 25s.

function startKeepAlive() {
  stopKeepAlive();
  keepaliveId = setInterval(() => {
    if (!recording || !ws || ws.readyState !== WebSocket.OPEN) return;
    // 512 zero samples = 32 ms of silence at 16 kHz
    const silence = new ArrayBuffer(1024);
    const b64 = btoa(String.fromCharCode(...new Uint8Array(silence)));
    ws.send(JSON.stringify({ type: "audio", data: b64 }));
  }, KEEPALIVE_INTERVAL_MS);
}

function stopKeepAlive() {
  if (keepaliveId !== null) { clearInterval(keepaliveId); keepaliveId = null; }
}

// ---------------------------------------------------------- disconnect button

const disconnectBtn = document.getElementById("disconnectBtn");

function doDisconnect() {
  manualDisconnect = true;
  if (ws && ws.readyState <= WebSocket.OPEN) ws.close();
  stopKeepAlive();
  disconnectBtn.textContent = "Connect";
  disconnectBtn.classList.add("off");
}

function doConnect() {
  manualDisconnect = false;
  disconnectBtn.textContent = "Disconnect";
  disconnectBtn.classList.remove("off");
  connect();
}

disconnectBtn.addEventListener("click", () => {
  if (manualDisconnect) doConnect(); else doDisconnect();
});

connect();
</script>
</body>
</html>
"""


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
        args.host, args.port, args.model, args.voice, app["region"],
    )
    web.run_app(app, host=args.host, port=args.port, print=None)


if __name__ == "__main__":
    main()
