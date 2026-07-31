---
type: Wiki Overview
title: 4. Interaction surface — WebSockets, audio, integrations
id: doc:docs-architecture-04-interaction-surface-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: AI-Parrot speaks to humans through a deliberately polyglot front. Every
---

# 4. Interaction surface — WebSockets, audio, integrations

> Part of the [Exposure, Interoperability & Hardening](README.md) set.
> Previous: [Toolkits](03-toolkits.md) · Next: [Hardening](05-hardening.md)

AI-Parrot speaks to humans through a deliberately polyglot front. Every
channel resolves down to the same agent / chatbot abstractions; the
channel only shapes the I/O envelope.

## 4.1 Channel topology

```mermaid
graph LR
    subgraph Users["Humans"]
        TG["Telegram"]
        SL["Slack"]
        TM["MS Teams"]
        WA["WhatsApp"]
        MX["Matrix"]
        ZM["Zoom"]
        VC["Voice client<br/>(browser / phone)"]
        BR["Browser / SPA"]
        API["Service consumers"]
    end

    subgraph Wrappers["Integrations — parrot/integrations/"]
        TGW["TelegramAgentWrapper<br/>telegram/wrapper.py:62"]
        SLW["SlackAgentWrapper<br/>slack/wrapper.py:68"]
        TMW["MSTeamsAgentWrapper<br/>msteams/wrapper.py:63"]
        WAW["WhatsAppAgentWrapper<br/>whatsapp/wrapper.py:38"]
        MXW["Matrix appservice"]
        ZMW["Zoom client"]
    end

    Mgr["IntegrationManager<br/>integrations/manager.py:60<br/>integrations_bots.yaml"]

    subgraph Voice["Voice — parrot/voice/"]
        VTrans["VoiceTranscriber<br/>transcriber.py:30"]
        FW["FasterWhisperBackend<br/>(local GPU)"]
        OAI["OpenAIWhisperBackend<br/>(API)"]
        Live["VoiceBot<br/>Gemini Live native audio<br/>server.py:66"]
        VWS["VoiceChatHandler<br/>WS /ws — handler.py"]
    end

    subgraph HTTP["aiohttp HTTP/WS — parrot/handlers/"]
        Chat["ChatHandler<br/>/api/v1/chat/{name}<br/>chat.py:41"]
        AgT["AgentTalk<br/>/api/v1/agents/chat/{id}<br/>agent.py:55"]
        Stream["Stream handler<br/>SSE · NDJSON · chunked · WS<br/>handlers/stream.py:173"]
    end

    subgraph Forms["Forms — parrot/forms/"]
        Schema["FormSchema · FormField"]
        ReqForm["RequestFormTool<br/>tools/request_form.py:74"]
        AC["AdaptiveCardRenderer (Teams)"]
        Wizard["FormOrchestrator (Teams dialogs)"]
    end

    Bots["Bots / Agents / Crews"]

    TG --> TGW
    SL --> SLW
    TM --> TMW
    WA --> WAW
    MX --> MXW
    ZM --> ZMW

    TGW --> Mgr
    SLW --> Mgr
    TMW --> Mgr
    WAW --> Mgr
    MXW --> Mgr
    ZMW --> Mgr

    VC -->|WebSocket| VWS
    BR -->|WebSocket| Stream
    BR -->|HTTP| Chat
    BR -->|HTTP| AgT
    API --> Chat
    API --> AgT

    VWS --> Live
    VWS --> VTrans
    VTrans --> FW
    VTrans --> OAI

    TGW -. voice notes .-> VTrans
    TMW -. voice notes .-> VTrans

    Mgr   --> Bots
    Chat  --> Bots
    AgT   --> Bots
    Stream--> Bots
    VWS   --> Bots
    Live  --> Bots

    Bots -.->|"emits<br/>form_requested"| ReqForm
    ReqForm --> Schema
    Schema  --> AC
    Schema  --> Wizard
    AC -. renders to .-> TMW
    Wizard -. renders to .-> TMW

    classDef ch  fill:#e3f2fd,stroke:#1976d2;
    classDef vx  fill:#fff3e0,stroke:#ef6c00;
    classDef hx  fill:#e8f5e9,stroke:#2e7d32;
    classDef fx  fill:#fce4ec,stroke:#c2185b;
    class TGW,SLW,TMW,WAW,MXW,ZMW ch;
    class VTrans,FW,OAI,Live,VWS vx;
    class Chat,AgT,Stream hx;
    class Schema,ReqForm,AC,Wizard fx;
```

## 4.2 Integrations

| Channel      | Entry point                                                            | Highlights                                                                                                                                              |
|--------------|------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------|
| Telegram     | `parrot/integrations/telegram/wrapper.py:62` — `TelegramAgentWrapper`  | Text, photos, documents, **voice notes (STT)**, inline keyboards, commands (`/ask`, `/login`, `/add_mcp` …), groups & supergroups, crew routing.        |
| Slack        | `parrot/integrations/slack/wrapper.py:68` — `SlackAgentWrapper`        | Events API + Socket Mode, files, buttons / select menus, threads, async background processing.                                                          |
| MS Teams     | `parrot/integrations/msteams/wrapper.py:63` — `MSTeamsAgentWrapper`    | Bot Framework, Adaptive Cards, **voice transcription**, multi-step **wizard dialogs** via `FormOrchestrator` (`dialogs/orchestrator.py:1`).             |
| WhatsApp     | `parrot/integrations/whatsapp/wrapper.py:38` — `WhatsAppAgentWrapper`  | Meta Cloud API, 24-hour messaging-window tracking, per-user sessions, phone allowlist.                                                                  |
| Matrix       | `parrot/integrations/matrix/appservice.py`                             | Appservice protocol, A2A transport, multi-agent crew coordinator (`matrix/crew/coordinator.py`), real-time streaming.                                   |
| Zoom         | `parrot/integrations/zoom/client.py`                                   | Proof-of-concept client wrapper.                                                                                                                        |
| Filesystem   | `parrot/transport/filesystem/{channel,transport,cli}.py`               | File-based channels for testing and local development.                                                                                                  |

Per-bot configuration lives in `integrations_bots.yaml`; the manager
(`integrations/manager.py:60`) keeps `telegram_bots`, `slack_bots`,
`msteams_bots`, `whatsapp_bots` registries.

OAuth flows initiated from chat (Jira sign-in from Telegram, etc.) go
through the centralised registry in `integrations/oauth2/` and the
provider-specific implementations in `integrations/oauth2/jira_provider.py`
and `parrot/auth/jira_oauth.py`.

## 4.3 Audio and voice

Voice uses a unified service `VoiceTranscriber` (`parrot/voice/transcriber/transcriber.py:30`)
with two pluggable backends:

- `FasterWhisperBackend` (`faster_whisper_backend.py:21`) — local GPU
  inference. Models `tiny / base / small / medium / large-v3`, devices
  `cuda / cpu / auto`, precisions `float16 / int8 / float32`. Zero API
  cost.
- `OpenAIWhisperBackend` (`openai_backend.py:23`) — Whisper API with
  exponential backoff for rate limits.

Supported audio formats (`transcriber.py:62`): `.ogg`, `.mp3`, `.wav`,
`.m4a`, `.webm`, `.mp4`, `.flac` — covering Telegram OPUS, MS Teams
attachments and arbitrary file uploads.

For real-time bidirectional audio, the **VoiceBot** stack
(`parrot/voice/server.py:66`) integrates Google Gemini Live native-audio
models (`gemini-2.5-flash-native-audio-preview`) with VAD, streaming
mode and buffered mode, all driven over WebSocket (§4.4).

## 4.4 WebSocket endpoints

Three independent WebSocket surfaces are exposed:

- **Voice chat** — `parrot/voice/handler.py:VoiceChatHandler`. Routes
  `GET /ws` (or `/api/v1/voice/ws`). JSON message protocol with frames
  `auth`, `start_session`, `audio_chunk` (base64), `send_text`,
  `start_recording`. JWT carried in `Sec-WebSocket-Protocol` or in the
  body. Supports streaming and buffered modes, VAD, **tool execution
  inside a voice turn**.
- **Slack Socket Mode** — `slack/socket_handler.py:SlackSocketHandler`.
  Outbound WebSocket to Slack's gateway for firewall-restricted
  deployments (no inbound HTTP needed).
- **Agent stream** — `handlers/stream.py:173`. `GET /bots/{bot_id}/stream/ws`
  for raw streaming of agent responses; companion endpoints `…/sse`,
  `…/ndjson`, `…/chunked` for HTTP variants.

## 4.5 HTTP API

The aiohttp surface mounted under `/api/v1/` covers:

| Endpoint                                          | Handler                              | Notes                                                                  |
|---------------------------------------------------|--------------------------------------|------------------------------------------------------------------------|
| `POST /api/v1/chat/{chatbot_name}`                | `ChatHandler` (`handlers/chat.py:41`) | RAG + vector search, model override, multipart files, custom methods.  |
| `POST /api/v1/agents/chat/{agent_id}`             | `AgentTalk` (`handlers/agent.py:55`) | Multi-format output (JSON / HTML / Markdown / Terminal), PBAC context. |
| `PATCH /api/v1/agents/chat/{agent_id}`            | `AgentTalk`                          | Configure ToolManager + MCP servers (`agent.py:1602`).                 |
| `PUT /api/v1/agents/chat/{agent_id}`              | `AgentTalk`                          | Reset / update agent state (`agent.py:1726`).                          |
| `GET /api/v1/agents/chat/`                        | `AgentTalk`                          | List available agents (`agent.py:1824`).                               |
| `POST /bots/{bot_id}/stream/{sse|ndjson|chunked}` | streaming handlers                   | Plain HTTP streaming variants.                                         |

## 4.6 Forms and interactive UI

`parrot/forms/` provides a platform-agnostic form schema:

- `schema.py:19` — `FormField`, `FormSection`, `FormSchema` (text, select,
  multi-select, date, file, group, array). Conditional visibility and
  validation are first-class.
- `tools/request_form.py:74` → `RequestFormTool` — when an agent needs
  parameters it can't infer, it emits `ToolResult(status="form_requested",
  metadata={"form": schema})`. The wrapping integration (Teams Adaptive
  Card, Telegram inline keyboard, web SPA) renders the form, validates
  the answer, and resumes the original tool call. The MS Teams adapter
  (`msteams/dialogs/`) ships ready-made simple / wizard / conversational
  presets and a `FormOrchestrator`.

This is what powers the "ask-clarifying-question" UX in chat platforms
without bolting custom dialog logic onto each integration.
