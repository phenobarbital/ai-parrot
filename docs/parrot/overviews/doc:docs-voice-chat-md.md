---
type: Wiki Overview
title: 🦜 AI-Parrot Voice Chat
id: doc:docs-voice-chat-md
tags:
- overview
timestamp: '2026-07-14T22:20:21+00:00'
summary: Real-time voice chat interface using **Gemini Live API** for native speech-to-speech
  interactions.
relates_to:
- concept: mod:parrot.voice
  rel: mentions
---

# 🦜 AI-Parrot Voice Chat

Real-time voice chat interface using **Gemini Live API** for native speech-to-speech interactions.

## 🎯 Features

- **Bidirectional Voice Streaming**: WebSocket-based real-time audio streaming
- **Native Speech-to-Speech**: Uses Gemini 2.5 Flash Native Audio for low-latency voice interactions
- **Multimodal Responses**: Receive both text and audio responses simultaneously
- **Voice Activity Detection**: Automatic speech detection and interruption handling
- **Modern UI**: Elegant chat interface with audio visualization

## 📐 Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         FRONTEND (HTML)                          │
│  ┌─────────────┐    ┌──────────────┐    ┌────────────────────┐  │
│  │ Microphone  │───▶│ AudioContext │───▶│ WebSocket Client   │  │
│  │ (16kHz PCM) │    │ + Processor  │    │ (Binary + JSON)    │  │
│  └─────────────┘    └──────────────┘    └────────────────────┘  │
│                                                    │             │
│  ┌─────────────┐    ┌──────────────┐              │             │
│  │ Chat Panel  │◀───│ Audio Player │◀─────────────┘             │
│  │ (Text)      │    │ (24kHz PCM)  │                            │
│  └─────────────┘    └──────────────┘                            │
└─────────────────────────────────────────────────────────────────┘
                              │ WebSocket
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      BACKEND (Python/aiohttp)                    │
│  ┌────────────────────┐                                         │
│  │ VoiceChatServer    │                                         │
│  │  - WebSocket       │     ┌──────────────────────────────┐   │
│  │  - Session Mgmt    │────▶│ Gemini Live API              │   │
│  │  - Audio Buffer    │     │ (gemini-2.5-flash-native)    │   │
│  └────────────────────┘     │  - Audio In → Audio Out      │   │
│                             │  - Text Transcription         │   │
│                             │  - Tool Calling               │   │
│                             └──────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

## 🚀 Quick Start

### 1. Install Dependencies

```bash
# Create virtual environment (recommended)
python -m venv venv
source venv/bin/activate  # Linux/Mac
# or: venv\Scripts\activate  # Windows

# Install requirements
pip install -r requirements.txt
```

### 2. Set API Key

```bash
# Linux/Mac
export GOOGLE_API_KEY=your_api_key_here

# Windows (PowerShell)
$env:GOOGLE_API_KEY="your_api_key_here"
```

Get your API key from: https://aistudio.google.com/apikey

### 3. Run the Server

```bash
python server.py
```

### 4. Open the Interface

Navigate to: **http://localhost:8765**

## 🎙️ Usage

1. **Connect**: The interface auto-connects to the WebSocket server
2. **Configure**: Click ⚙️ to select voice and language
3. **Speak**: Press and hold the microphone button to talk
4. **Listen**: Release to hear the AI's voice response
5. **Read**: See the transcribed text in the chat

## 📁 Project Structure

```
voice_poc/
├── server.py                 # Main server (WebSocket + Static files)
├── requirements.txt          # Python dependencies
├── README.md                 # This file
├── frontend/
│   └── voice_chat.html       # Web interface (HTML + JS + CSS)
└── parrot/
    └── voice/
        ├── __init__.py       # Module exports
        ├── models.py         # Data models (VoiceChunk, VoiceResponse, etc.)
        ├── session.py        # VoiceSession manager
        ├── bot.py            # VoiceBot implementation
        └── handlers.py       # WebSocket handlers
```

## 🔧 Configuration Options

### Voice Selection (Gemini)

| Voice | Description |
|-------|-------------|
| `Puck` | Friendly, approachable (default) |
| `Aoede` | Warm, expressive |
| `Charon` | Deep, authoritative |
| `Fenrir` | Strong, confident |
| `Kore` | Gentle, soft |

### Audio Formats

- **Input**: PCM 16-bit, 16kHz, mono
- **Output**: PCM 16-bit, 24kHz, mono

### WebSocket Protocol

```javascript
// Client → Server Messages
{ "type": "start_session", "config": { "voice_name": "Puck", "language": "en-US" } }
{ "type": "audio_chunk", "data": "<base64_pcm>" }
{ "type": "stop_recording" }
{ "type": "end_session" }

// Server → Client Messages
{ "type": "session_started", "session_id": "..." }
{ "type": "response_chunk", "text": "...", "audio_base64": "..." }
{ "type": "response_complete", "text": "...", "audio_base64": "..." }
{ "type": "error", "message": "..." }
```

## 🔌 Integration with AI-Parrot

To integrate with your existing AI-Parrot project:

### 1. Copy the voice module

```bash
cp -r parrot/voice /path/to/ai-parrot/parrot/
```

### 2. Add routes to your application

```python
from parrot.voice.handlers import setup_voice_routes

# In your app setup
setup_voice_routes(app)
```

### 3. Create a voice-enabled bot

```python
from parrot.voice import VoiceBot, VoiceConfig

bot = VoiceBot(
    name="My Voice Assistant",
    system_prompt="You are a helpful assistant...",
    voice_config=VoiceConfig(
        voice_name="Puck",
        language="es-ES"  # Spanish
    ),
    tools=[my_tool]  # Your existing tools work!
)

# Use in your handler
async for response in bot.ask_voice_stream(audio_bytes):
    await send_to_client(response)
```

## 🛠️ Development

### Mock Mode

If `GOOGLE_API_KEY` is not set, the server runs in mock mode for UI testing.

### Debug Logging

```bash
export LOG_LEVEL=DEBUG
python server.py
```

### Browser Console

Open DevTools to see WebSocket messages and audio processing logs.

## 📋 Requirements

- Python 3.10+
- Modern browser with Web Audio API support
- Google Cloud API key with Gemini access
- Microphone access

## 🔐 Security Notes

- API key is stored server-side only
- Audio is processed in real-time, not stored
- Use HTTPS in production
- Implement authentication for production use

## 🐛 Troubleshooting

### "Microphone access denied"
- Check browser permissions
- Use HTTPS or localhost

### "Connection error"
- Verify server is running
- Check WebSocket URL in settings
- Look for CORS errors in console

### "No audio response"
- Verify GOOGLE_API_KEY is set
- Check server logs for API errors
- Ensure google-genai is installed

### High latency
- Use wired internet connection
- Check server location vs API region
- Reduce audio chunk size

## 📚 Resources

- [Gemini Live API Documentation](https://ai.google.dev/gemini-api/docs/live)
- [Web Audio API](https://developer.mozilla.org/en-US/docs/Web/API/Web_Audio_API)
- [aiohttp WebSockets](https://docs.aiohttp.org/en/stable/web_quickstart.html#websockets)

## 📄 License

MIT License - Part of AI-Parrot project