# Technical Voice Guide (AgentTalk Voice) for Frontend

**Audience**: the Frontend team building the voice conversation UI
(record and send a voice note + play the agent's spoken reply)
on top of AI-Parrot.

**Scope**: FEAT-231 — *AgentTalk Voice Support* (REST round-trip:
`audio → STT → text agent → TTS → audio + content`).

**Endpoint**: `POST /api/v1/agents/voice/{agent_id}`
(handler `AgentVoiceTalk`, subclass of `AgentTalk`).

> This document is grounded in the real code of the branch
> `feat-231-agentalk-voice-support`. File paths and line numbers
> are **verification anchors** (anti-hallucination) and may move; the
> semantic contract is what matters.
>
> Verified source files:
> - `packages/ai-parrot-server/src/parrot/handlers/agent_voice.py` — voice handler
> - `packages/ai-parrot-server/src/parrot/handlers/agent.py` — `AgentTalk` (text, inherited)
> - `packages/ai-parrot-server/src/parrot/manager/manager.py:1453-1480` — route registration
> - `sdd/specs/agentalk-voice-support.spec.md` — specification (FEAT-231)

---

## 0. Table of Contents

1. [Mental model: a voice adapter over the text chat](#1-modelo-mental)
2. [The voice endpoint](#2-el-endpoint-de-voz)
3. [Sending the voice note (request)](#3-enviar-la-nota-de-voz-request)
4. [The response (envelope + audio)](#4-la-respuesta-envelope-audio)
5. [Playing the spoken reply](#5-reproducir-la-contestación-por-voz)
6. [Optional per-request selectors (STT/TTS backends, format)](#6-selectores-opcionales-por-petición)
7. [Degradation and error handling](#7-degradación-y-manejo-de-errores)
8. [Complete examples (JS/TS)](#8-ejemplos-completos-jsts)
9. [Frontend integration checklist](#9-checklist-de-integración-frontend)

---

## 1. Mental model

The voice endpoint is **not a new conversation endpoint**. It is a
**voice I/O adapter around the existing text flow** of
`AgentTalk`. It inherits *exactly* the same agent resolution, PBAC, HITL,
authentication, sessions and output negotiation as the regular chat. It only adds
two seams:

```
 POST multipart (nota de voz)
         │
         ▼
  ┌──────────────────────────────────────────────┐
  │ 1. ENTRADA (STT)                               │
  │    audio adjunto ──transcribe──▶ query: str    │
  └──────────────────────────────────────────────┘
         │
         ▼
   bot.ask(question=query, …) ──▶ AIMessage   (idéntico al chat de texto)
         │
         ▼
  ┌──────────────────────────────────────────────┐
  │ 2. SALIDA (TTS)                                │
  │    AIMessage.response (str) ──synthesize──▶    │
  │    audio_base64 + audio_format                 │
  └──────────────────────────────────────────────┘
         │
         ▼
 HTTP 200  { …envelope de AgentTalk…, audio_base64, audio_format }
```

**Practical consequences for the Frontend:**

- The **response envelope is identical** to that of `AgentTalk` (`/chat/...`) plus
  **two fields** (`audio_base64`, `audio_format`). If you already consume the text
  chat, you reuse all the parsing.
- **Only `response.response` is synthesized** (the speakable text of the reply).
  Non-speakable content (`output`, `data`, `media`, structured artifacts) keeps
  traveling as `content` and **never** goes through the synthesizer. That is:
  the user *hears* the response text and *sees* the tables/charts/data.
- If you send text (not audio) to this endpoint, it behaves like the regular chat:
  **no** `audio_base64` in the response.

---

## 2. The voice endpoint

| | |
|---|---|
| **Method** | `POST` |
| **Route** | `/api/v1/agents/voice/{agent_id}` |
| **`{agent_id}`** | agent name/slug (same as in `/chat/{agent_id}`) |
| **Auth** | `@is_authenticated()` + `@user_session()` (identical to `AgentTalk`) |
| **Input Content-Type** | `multipart/form-data` (to send the audio) |
| **Output Content-Type** | `application/json` |

> **Route availability** (`manager.py:1453-1480`): the route is registered
> under an optional integration *guard*. If the server does not have the voice
> stack installed (`ai-parrot-integrations[voice]`), the route is **not registered**
> and the server starts anyway. In that case the endpoint returns `404`. Treat it
> as *feature detection*: if you get `404` on `/voice/...`, hide the voice UI.

---

## 3. Sending the voice note (request)

To send audio you **must** use `multipart/form-data` (that is what triggers
`handle_upload()` on the server). The audio goes as a *file part*; the rest of the
chat parameters go as *form fields* (the same ones `/chat/{agent_id}` would accept).

### 3.1 The audio file part

The handler detects the audio attachment in two ways
(`agent_voice.py::_is_audio`):

1. By **MIME type**: anything starting with `audio/`, or exactly
   `video/webm` (because `MediaRecorder` in the browser usually produces
   `audio/webm` or `video/webm`).
2. By **filename extension**, if the MIME type is inconclusive.
   Supported containers (`_AUDIO_EXTS`, mirror of
   `VoiceTranscriber.SUPPORTED_FORMATS`):

   ```
   .ogg  .mp3  .wav  .m4a  .webm  .mp4  .flac
   ```

> **Recommendation**: record with `MediaRecorder` and upload `audio/webm` (Opus) or
> `audio/ogg`. Make sure the part's `filename` has a valid extension from the
> list (e.g. `nota.webm`) as a fallback to MIME detection.

The **file part's field name is free** — the handler looks for *any* audio
attachment in *any* field (`_find_audio_attachment` walks all
the fields). Use a clear name such as `audio` or `file`.

### 3.2 Form fields (all optional unless noted)

Since the text flow is inherited from `AgentTalk`, these fields behave
the same as in `/chat/{agent_id}`:

| Field | Type | Notes |
|---|---|---|
| `query` | string | **Normally NOT sent.** If you send it, **the text wins** and the audio is discarded (see below). |
| `session_id` | string | Conversation ID to keep context. Recommended. |
| `user_id` | string | Optional; normally resolved from the authenticated session. |
| `output_mode` | string | `json \| html \| markdown \| terminal \| default`. For voice you want the envelope to be JSON (default already returns structured JSON in `_format_response`). |
| `message_id` | string | Client-generated message ID (used as `turn_id` for dedup in the history). |
| `use_conversation_history` | bool | default `true`. |
| `use_vector_context` | bool | default `true`. |
| `format_kwargs` | JSON object | e.g. `{"include_sources": true}`. In multipart, send it as a JSON string. |
| **`stt_backend`** | string | **New (voice).** STT engine selector. See §6. |
| **`tts_backend`** | string | **New (voice).** TTS engine selector. See §6. |
| **`audio_format`** | string | **New (voice).** Desired output audio container. See §6. |

### 3.3 Precedence rule: audio vs. `query`

`agent_voice.py::handle_upload`:

- **Audio present and NO `query`** → the audio is transcribed and the transcript is
  injected as `query`. (`_did_transcribe = True` → the response will carry audio.)
- **Audio present AND `query` present** (explicit non-empty text) → **the text wins**:
  the audio is discarded, its tempfile is deleted, and the flow is pure text
  (the response will **not** carry `audio_base64`).
- **No audio** → behaves exactly like the text `AgentTalk`.

> UI implication: for a voice note, do **not** fill in `query`. If your UI
> allows typing AND recording at the same time, decide which one you send: if you send both, you will hear
> silence (text-only response) because text has priority.

---

## 4. The response (envelope + audio)

`HTTP 200`, `application/json`. It is the **standard `AgentTalk` envelope**
(built in `agent.py::_format_response`, `output_format == 'json'` branch) plus
the two audio fields added by `AgentVoiceTalk::_augment_with_audio`.

```jsonc
{
  // ── Envelope heredado de AgentTalk ──────────────────────────
  "input":  "Hola, ¿qué tiempo hace en Madrid?",   // el transcript (query usado)
  "output": "...",            // salida estructurada (DataFrame→records, modelos, etc.) o texto
  "data":   null,             // filas/datos crudos cuando aplica (p. ej. DatabaseAgent)
  "response": "En Madrid hace sol, 25°C.",  // ← TEXTO HABLABLE (lo que se sintetiza)
  "output_mode": "json",
  "code": null,
  "metadata": {
    "model": "gemini-2.0-...",
    "provider": "google",
    "session_id": "abc-123",
    "turn_id": "…",
    "user_id": "…",
    "response_time": 842,      // ms
    "usage": { /* tokens */ },
    "finish_reason": "stop",
    "stop_reason": null,
    "created_at": "2026-06-09T..."
  },
  "sources": [ /* documentos RAG si los hay */ ],
  "tool_calls": [ /* herramientas invocadas si las hay */ ],

  // ── Añadido por AgentVoiceTalk (solo si hubo voz de entrada y TTS tuvo éxito) ──
  "audio_base64": "<base64 de los bytes de audio>",
  "audio_format": "audio/wav"   // mime_format REAL del audio devuelto
}
```

### Key fields for voice

| Field | Meaning |
|---|---|
| `response` | The **text** of the agent's reply. It is exactly what was synthesized to speech. Show it as a caption/transcript next to the player. |
| `audio_base64` | Bytes of the reply audio, encoded in **base64** (ASCII). **Present only** when: (a) the input was a voice note, and (b) TTS succeeded. |
| `audio_format` | The **real MIME** of the audio (`SynthesisResult.mime_format`), e.g. `audio/wav`. It is *truthful* — use it as is to build the `Blob`/`data:` URI. Do not assume it. |
| `output` / `data` / artifacts | **Non-speakable** content: tables, charts, maps, files. Render it visually as in the regular chat (see the structured artifacts guide). It is **never** put into the audio. |

> **`audio_base64` absent ≠ error.** If the request was text, or TTS was not
> available/failed, the envelope arrives **without** `audio_base64` but with
> `response` (text). This is the expected degradation (§7).

---

## 5. Playing the spoken reply

`audio_base64` + `audio_format` → directly playable. Two ways:

**Way A — `data:` URI (simple):**

```ts
function playFromEnvelope(envelope: any) {
  if (!envelope.audio_base64) return;            // degradado a solo-texto
  const src = `data:${envelope.audio_format};base64,${envelope.audio_base64}`;
  const audio = new Audio(src);
  audio.play();
}
```

**Way B — `Blob` + object URL (better for long clips / memory control):**

```ts
function blobFromEnvelope(envelope: any): Blob | null {
  if (!envelope.audio_base64) return null;
  const bytes = Uint8Array.from(atob(envelope.audio_base64), c => c.charCodeAt(0));
  return new Blob([bytes], { type: envelope.audio_format });  // ← usa el mime REAL
}

const blob = blobFromEnvelope(envelope);
if (blob) {
  const url = URL.createObjectURL(blob);
  const audio = new Audio(url);
  audio.onended = () => URL.revokeObjectURL(url);   // libera memoria
  audio.play();
}
```

> The server's default format is **`audio/wav`** (spec decision U5:
> a container friendly to the web player). All modern browsers
> play WAV. If you request another format via `audio_format` (§6), honor the
> *returned* `audio_format`, not the one you requested — the server truthfully labels
> what it actually synthesized.

---

## 6. Optional per-request selectors

`agent_voice.py::_read_voice_options` reads three optional form fields. **They are not
needed for the normal case** (there are sensible defaults); use them only if the
backend has those engines installed.

| Field | Default | Values | Effect |
|---|---|---|---|
| `stt_backend` | `faster_whisper` (default of `VoiceTranscriberConfig`) | `faster_whisper`, `openai_whisper`, `moonshine` | Transcription engine (audio→text). If the value is unknown, it is ignored and the default is used. |
| `tts_backend` | `google` | `google`, `elevenlabs`, `openai`, `supertonic` | Synthesis engine (text→audio). |
| `audio_format` | `audio/wav` | e.g. `audio/wav`, `audio/ogg` | Desired output container. The server returns the real `audio_format` in the envelope. |

> **These backends are opt-in and depend on extras installed on the server**
> (`voice-supertonic`, `voice-moonshine`, etc.). If you request a backend whose extra
> is not installed, the handler degrades: STT unavailable → `503`; TTS
> unavailable → **text-only** response (see §7). For the common case, **omit
> these fields** and let the server use FasterWhisper (STT) + Google (TTS).

---

## 7. Degradation and error handling

The design prioritizes **not breaking the conversation**. Summary of behaviors:

| Situation | Code | Body | What the Frontend does |
|---|---|---|---|
| Voice OK, TTS OK | `200` | envelope + `audio_base64` + `audio_format` | Plays audio + shows `response`. |
| Voice OK, **TTS fails / unavailable** | `200` | envelope **without** `audio_base64` | Shows `response` as text; no player. *(`_augment_with_audio` catches `ValueError/RuntimeError/ImportError` and returns the text response intact.)* |
| Text (no audio) to `/voice/...` | `200` | envelope **without** `audio_base64` | Same as the regular chat. |
| **STT unavailable** (stack/extra not installed) | `503` | `{"error": "Voice transcription is unavailable; install ai-parrot-integrations[voice]."}` | Shows error; suggests retrying as text. |
| **Audio not transcribable** (invalid format, exceeds max duration, corrupt) | `400` | `{"error": "Could not transcribe audio: <detalle>"}` | Shows a recording error; allows re-recording. |
| Auth required by a tool (OAuth) | `200` | `AuthRequiredEnvelope` (inherited) | Render "Connect pill" (same as in chat). |
| HITL suspend (pause for human interaction) | `200` | `PausedEnvelope` (inherited) | Render HITL UI (same as in chat). |
| Agent not found | `404` | `{"error": "Agent '…' not found."}` | Configuration error. |
| Voice route not registered (no voice stack) | `404` | — | Hide the voice UI (feature detection). |

**Audio duration limit**: the transcriber applies
`max_audio_duration_seconds` (default **60s**, `VoiceTranscriberConfig`). Longer
voice notes return `400`. Consider limiting recording on the client.

**Mental rule**: always treat `audio_base64` as *optional*. Your UI must
work perfectly with just `response` (text). The audio is an *enhancement*.

---

## 8. Complete examples (JS/TS)

### 8.1 Record and send a voice note

```ts
// 1. Grabar con MediaRecorder
async function recordVoiceNote(): Promise<Blob> {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  const recorder = new MediaRecorder(stream, { mimeType: "audio/webm" });
  const chunks: BlobPart[] = [];
  recorder.ondataavailable = (e) => chunks.push(e.data);
  recorder.start();
  // … parar tras la interacción del usuario …
  await new Promise<void>((res) => (recorder.onstop = () => res()));
  stream.getTracks().forEach((t) => t.stop());
  return new Blob(chunks, { type: "audio/webm" });
}

// 2. Enviar al endpoint de voz
async function sendVoiceNote(agentId: string, audio: Blob, sessionId?: string) {
  const form = new FormData();
  // nombre de archivo CON extensión válida como respaldo a la detección MIME
  form.append("audio", audio, "nota.webm");
  if (sessionId) form.append("session_id", sessionId);
  // NO envíes 'query' — gana el texto y descarta el audio
  // selectores opcionales:
  // form.append("tts_backend", "supertonic");
  // form.append("audio_format", "audio/wav");

  const res = await fetch(`/api/v1/agents/voice/${agentId}`, {
    method: "POST",
    body: form,                 // el navegador pone el boundary de multipart
    credentials: "include",     // cookies de sesión / auth
  });

  if (res.status === 404) throw new Error("Voz no disponible en este servidor");
  const envelope = await res.json();
  if (!res.ok) throw new Error(envelope.error ?? `HTTP ${res.status}`);
  return envelope;
}
```

### 8.2 Consume the response (audio + text + artifacts)

```ts
const envelope = await sendVoiceNote("weather-bot", audioBlob, sessionId);

// (a) Subtítulo / transcript de la contestación
renderAssistantText(envelope.response);

// (b) Reproducir la voz si vino
if (envelope.audio_base64) {
  const bytes = Uint8Array.from(atob(envelope.audio_base64), c => c.charCodeAt(0));
  const url = URL.createObjectURL(new Blob([bytes], { type: envelope.audio_format }));
  const player = new Audio(url);
  player.onended = () => URL.revokeObjectURL(url);
  await player.play();
} else {
  // degradación a solo-texto — perfectamente válido
}

// (c) Render de artefactos NO hablables (tablas/gráficos/mapas/datos)
//     igual que en el chat normal — ver structured-artifacts-frontend-guide.md
if (envelope.output_mode?.startsWith("structured_")) {
  renderStructuredArtifact(envelope);   // usa envelope.response.artifacts + envelope.data
}
```

---

## 9. Frontend integration checklist

- [ ] Record with `MediaRecorder` (`audio/webm` or `audio/ogg`) and upload as
      `multipart/form-data`, with a `filename` that has a valid extension
      (`.webm`, `.ogg`, `.wav`, …).
- [ ] Do **not** send `query` in a voice note (text takes priority over audio).
- [ ] Send `session_id` to keep the conversation thread.
- [ ] Play `audio_base64` using **the returned `audio_format`** (do not assume WAV).
- [ ] Always show `response` (text) as the voice transcript/caption.
- [ ] Treat `audio_base64` as **optional**: the UI must work in text-only mode.
- [ ] Render `output`/`data`/artifacts as in the regular chat (they do not go into the audio).
- [ ] Handle `503` (STT unavailable) and `400` (audio not transcribable) with clear messages.
- [ ] Feature detection: `404` on `/voice/...` → hide the voice UI.
- [ ] (Optional) Limit the recording duration on the client (server: 60s by default).
- [ ] (Optional) Expose `stt_backend` / `tts_backend` / `audio_format` selectors
      only if the server has those engines installed.

---

## Appendix — Verification anchors (real code)

| Concept | File:line |
|---|---|
| Voice handler | `packages/ai-parrot-server/src/parrot/handlers/agent_voice.py` |
| Audio detection (MIME/extension) | `agent_voice.py::_is_audio`, `_AUDIO_EXTS` |
| Transcript injection / audio vs query precedence | `agent_voice.py::handle_upload` |
| STT/TTS/format selectors | `agent_voice.py::_read_voice_options` |
| Attaches `audio_base64` + `audio_format` | `agent_voice.py::_augment_with_audio`, `_synthesize` |
| TTS degradation (try/except) | `agent_voice.py::_augment_with_audio` |
| Default `audio/wav` | `agent_voice.py::_DEFAULT_AUDIO_FORMAT` |
| Inherited JSON envelope | `agent.py::_format_response` (`output_format == 'json'` branch) |
| `response` field (speakable text) | `agent.py::_format_response` → `obj_response["response"]` |
| Route registration under optional guard | `manager/manager.py:1453-1480` |
| Full specification | `sdd/specs/agentalk-voice-support.spec.md` (FEAT-231) |

> FEAT-231 status: implemented and verified on the branch
> `feat-231-agentalk-voice-support` (4 tasks: Supertonic TTS, Moonshine STT,
> `AgentVoiceTalk` handler, route registration). Pending merge to `dev` at the
> time this guide was written.
