// Push-to-talk voice-chat UI — extracted from examples/clients/nova/audio.py
// (FEAT-418, TASK-2177) into a standalone static asset so it can be served
// unmodified by every example that drives a VoiceSession-shaped WebSocket
// protocol (turn_started / text / audio / tool_call / interrupted /
// turn_complete / error, canonical lowercase "user"/"assistant" roles —
// see docs/nova_voice_protocol.md and VoiceSession.build_frames()).
//
// Provider-specific labels come entirely from window.__CONFIG__ (set by the
// server's templated index.html) — this file itself has no per-provider
// branches, so a second example (TASK-2178) can serve it as-is.

const CONFIG = window.__CONFIG__;

const logEl = document.getElementById("log");
const ptt = document.getElementById("ptt");
const pttLabel = document.getElementById("pttLabel");
const statusEl = document.getElementById("status");
const dot = document.getElementById("dot");
const appTitle = document.getElementById("appTitle");

const PROVIDER_LABEL = CONFIG.providerLabel || CONFIG.model || "Assistant";

appTitle.textContent = PROVIDER_LABEL + " · Voice Chat";
document.title = PROVIDER_LABEL + " Voice Chat";
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
  // A role change (e.g. "user" transcription -> "assistant" reply) must
  // start a new bubble; consecutive same-role chunks keep streaming into
  // one. Roles are the canonical lowercase "user"/"assistant" envelope
  // (FEAT-418) — never the legacy uppercase Nova wire values.
  if (streamBubble && role !== streamRole) closeStream();
  if (!streamBubble) {
    // role is null for providers that do not report one — fall back to
    // the assistant bubble in that case.
    streamBubble = role === "user"
      ? addBubble("you", "", "You")
      : addBubble("assistant", "", PROVIDER_LABEL);
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
  // Request the context at the provider's input rate — the browser resamples for us.
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
      "instead of " + CONFIG.inputSampleRate + " Hz. " + PROVIDER_LABEL + " expects " +
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
const KEEPALIVE_INTERVAL_MS = 25000;  // send silence periodically to avoid idle timeouts
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
        // Re-enable the button as soon as the assistant starts replying —
        // the user can see the reply is streaming and should be able to
        // start a new turn (barge-in) without waiting for turn_complete.
        if (awaitingReply && msg.role !== "user") {
          awaitingReply = false;
          setPhase("idle", PROVIDER_LABEL + " is replying… hold to talk again.");
        }
        appendStream(msg.text, msg.role);
        break;
      case "audio":
        if (awaitingReply) {
          awaitingReply = false;
          setPhase("idle", PROVIDER_LABEL + " is replying… hold to talk again.");
        }
        playPCM(base64ToBytes(msg.audio_base64), msg.sample_rate || CONFIG.outputSampleRate);
        break;
      case "tool_call":
        addBubble("system", "tool " + msg.name + "(" + JSON.stringify(msg.arguments) + ")" +
                            (msg.error ? " failed: " + msg.error : " → " + msg.result));
        break;
      case "capability_notice":
        addBubble("system", msg.message);
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
          note += " " + PROVIDER_LABEL + "'s session limit was reached — the next press opens a fresh stream.";
        }
        setPhase("idle", note + " Hold to talk again.");
        break;
      }
      case "error":
        awaitingReply = false;
        clearTimeout(thinkingTimeout);
        closeStream();
        if (msg.message && msg.message.includes("Timed out waiting for audio")) {
          addBubble("system", "Session timed out — " + PROVIDER_LABEL + " received no speech. Press and hold to try again.");
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
  // No placeholder bubble here — the real user transcription now arrives
  // via the "text" frame's role, rendered by appendStream().
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
  setPhase("thinking", "Sent — waiting for " + PROVIDER_LABEL + "…");
  // Safety: force-reset if turn_complete never arrives.
  clearTimeout(thinkingTimeout);
  thinkingTimeout = setTimeout(() => {
    if (awaitingReply) {
      awaitingReply = false;
      closeStream();
      addBubble("system", "No reply from " + PROVIDER_LABEL + " within 60 s — resetting.");
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
// Some providers time out after a short window of no audio/interaction.
// While a turn is open and recording, the AudioWorklet already pushes
// frames continuously. This keepalive covers the edge case where the
// worklet stalls or the mic produces no data — it sends a short silence
// frame periodically.

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
