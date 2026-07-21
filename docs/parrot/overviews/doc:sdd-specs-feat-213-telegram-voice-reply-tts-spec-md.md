---
type: Wiki Overview
title: 'Feature Specification: Telegram Voice Reply (TTS Output)'
id: doc:sdd-specs-feat-213-telegram-voice-reply-tts-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: El *agent harness* (inspirado en **aphelion**) transcribe notas de voz a
  la
relates_to:
- concept: mod:parrot.clients.google.generation
  rel: mentions
- concept: mod:parrot.integrations.telegram.wrapper
  rel: mentions
- concept: mod:parrot.models.google
  rel: mentions
- concept: mod:parrot.models.outputs
  rel: mentions
- concept: mod:parrot.voice.tts
  rel: mentions
---

---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: Telegram Voice Reply (TTS Output)

**Feature ID**: FEAT-213
**Date**: 2026-05-31
**Author**: jesuslarag (via Claude)
**Status**: approved
**Target version**: 0.x

---

## 1. Motivation & Business Requirements

> Why does this feature exist? What problem does it solve?

### Problem Statement

El *agent harness* (inspirado en **aphelion**) transcribe notas de voz a la
entrada y, opcionalmente, **responde con voz** (aphelion usa ElevenLabs). En
ai-parrot la **entrada de voz ya funciona end-to-end**, y la **generación de
audio (TTS) ya existe**, pero **no están conectadas**: cuando el usuario habla
por voz, el bot responde solo con texto.

Tras auditar el codebase:

- **Entrada (STT) ya hecha**: `TelegramAgentWrapper.handle_voice`
  (`integrations/telegram/wrapper.py:2888`) descarga, transcribe vía
  `VoiceTranscriber` (`voice/transcriber/transcriber.py`), y procesa el texto por
  el agente. Gate `voice_enabled`/`voice_config` ya presente (wrapper.py:2925).
- **Generación TTS ya existe**: `GoogleGenAIClient.generate_speech(...)`
  (`clients/google/generation.py:411`) produce audio (WAV/MP3/WebM) desde
  `SpeechGenerationPrompt`; `bots/agent.py::speech_report` (:473) es un consumidor.
- **Envío proactivo ya existe**: `NotificationMixin.send_telegram_message`
  (`notifications/__init__.py:716`) y la `bot` aiogram del wrapper pueden enviar
  audio.

**La brecha** es estrecha: falta un **wiring de salida** que, cuando la entrada
fue voz (o el chat está en "modo voz"), genere una **nota de voz** con el TTS
existente y la envíe de vuelta por Telegram — un backend TTS desacoplado
(espejo del transcriber) que permita además ElevenLabs/OpenAI a futuro.

> Nota: el usuario pospuso explícitamente el **canal voz↔voz nativo** (Gemini
> Live, `VoiceBot`). Este spec cubre el **reply de voz sobre Telegram texto**:
> entra voz → transcribe (ya) → agente responde texto → se sintetiza y se manda
> como nota de voz. NO es streaming bidireccional.

### Goals

- **G1**: Capa TTS **desacoplada** (espejo del transcriber):
  `AbstractTTSBackend.synthesize(text) -> bytes` + un `VoiceSynthesizer` con
  selección de backend lazy.
- **G2**: Backend por defecto reutilizando la **TTS ya existente**
  (`GoogleGenAIClient.generate_speech`); estructura lista para
  `elevenlabs_backend`/`openai_backend` (no obligatorios en este spec).
- **G3**: **Wiring de salida en Telegram**: si la entrada fue voz y
  `reply_in_kind` está activo (o el chat en "modo voz"), tras obtener la respuesta
  del agente, sintetizar y enviar `bot.send_voice(...)` **además** del texto.
- **G4**: Config opt-in en el modelo de Telegram (`tts_enabled`,
  `tts_backend`, `tts_voice`, `reply_in_kind`), sin romper config existente.
- **G5**: Degradación elegante: si TTS no está configurado o falla, responder
  solo texto (nunca romper el flujo de mensaje).
- **G6**: Tests verdes (synthesizer con backend mock; wiring con bot mock).

### Non-Goals (explicitly out of scope)

- **Canal voz↔voz nativo / streaming bidireccional** (Gemini Live, `VoiceBot`):
  explícitamente pospuesto por el usuario.
- **Backends ElevenLabs/OpenAI completos**: la arquitectura los deja listos
  (ABC), pero el único backend obligatorio aquí es el de Google ya existente.
- **TTS en otras integraciones** (MS Teams, Slack): solo Telegram en este spec.
- **VAD / normalización de audio / métricas de loudness**: fuera de alcance.
- **Persistir audio generado**: se envía y se descarta (temp file, como el STT).

---

## 2. Architectural Design

### Overview

Se añade `voice/tts/` (espejo de `voice/transcriber/`): un `AbstractTTSBackend`,
un `GoogleTTSBackend` que envuelve `GoogleGenAIClient.generate_speech`, y un
`VoiceSynthesizer` que elige backend de forma lazy y devuelve bytes de audio. En
`TelegramAgentWrapper`, tras producir la respuesta del agente para un mensaje que
**entró como voz** (o con `reply_in_kind`), se sintetiza y se envía como nota de
voz, reutilizando el patrón de envío existente (`bot.send_voice`).

### Component Diagram

```
handle_voice (STT, ya existe)
   │ transcribe → texto → agente → respuesta (texto)
   ▼
if (input_was_voice or chat voice-mode) and tts_enabled:
   VoiceSynthesizer.synthesize(text) ──► AbstractTTSBackend
                                            └─ GoogleTTSBackend → generate_speech() → bytes
   │
   ▼
bot.send_voice(chat_id, BufferedInputFile(bytes))   + texto (split/format existente)
   └─ degrade: si falla TTS → solo texto
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `TelegramAgentWrapper.handle_voice` (`wrapper.py:2888`) | extends | Tras la respuesta del agente, rama de salida de voz. |
| `GoogleGenAIClient.generate_speech` (`clients/google/generation.py:411`) | wraps | Backend TTS por defecto (`GoogleTTSBackend`). |
| `SpeechGenerationPrompt`/`SpeakerConfig`/`TTSVoice` (`models/outputs.py:237,229`, `models/google.py:60`) | uses | Payload para `generate_speech`. |
| `VoiceTranscriber` (`voice/transcriber/`) | mirrors | Patrón de backend lazy + temp file cleanup. |
| Telegram config model (`telegram/models.py`) | modifies | Campos `tts_*`/`reply_in_kind` (opcionales). |
| aiogram `bot.send_voice` / `BufferedInputFile` | uses | Envío de la nota de voz. |
| `NotificationMixin.send_telegram_message` (`notifications/__init__.py:716`) | reference | Patrón de envío proactivo (para notificaciones de #1/#3). |

### Data Models

```python
# packages/ai-parrot-integrations/src/parrot/voice/tts/models.py
class TTSConfig(BaseModel):
    backend: Literal["google", "elevenlabs", "openai"] = "google"
    voice: Optional[str] = None          # backend-specific voice id
    language: Optional[str] = None
    mime_format: str = "audio/ogg"       # Telegram voice notes prefer OGG/Opus

class SynthesisResult(BaseModel):
    audio: bytes
    mime_format: str
    duration_s: Optional[float] = None
```

```python
# packages/ai-parrot-integrations/src/parrot/integrations/telegram/models.py  (MODIFIED)
class TelegramAgentConfig(...):
    tts_enabled: bool = False            # NEW
    tts_backend: str = "google"          # NEW
    tts_voice: Optional[str] = None      # NEW
    reply_in_kind: bool = True           # NEW — voice in → voice out
```

### New Public Interfaces

```python
# packages/ai-parrot-integrations/src/parrot/voice/tts/backend.py
class AbstractTTSBackend(ABC):
    @abstractmethod
    async def synthesize(self, text: str, *, voice: str | None = None,
                         mime_format: str = "audio/ogg") -> SynthesisResult: ...

# packages/ai-parrot-integrations/src/parrot/voice/tts/google_backend.py
class GoogleTTSBackend(AbstractTTSBackend):
    def __init__(self, client: "GoogleGenAIClient" | None = None, **kwargs) -> None: ...
    # wraps GoogleGenAIClient.generate_speech(SpeechGenerationPrompt(...))

# packages/ai-parrot-integrations/src/parrot/voice/tts/synthesizer.py
class VoiceSynthesizer:
    def __init__(self, config: TTSConfig | None = None) -> None: ...
    async def synthesize(self, text: str) -> SynthesisResult: ...   # lazy backend create
```

---

## 3. Module Breakdown

### Module 1: TTS abstraction + models
- **Path**: `packages/ai-parrot-integrations/src/parrot/voice/tts/` (`backend.py`, `models.py`)
- **Responsibility**: `AbstractTTSBackend`, `TTSConfig`, `SynthesisResult`.
- **Depends on**: nada nuevo.

### Module 2: GoogleTTSBackend + VoiceSynthesizer
- **Path**: `voice/tts/google_backend.py`, `voice/tts/synthesizer.py`
- **Responsibility**: backend que envuelve `generate_speech`; synthesizer con
  selección lazy (espejo de `VoiceTranscriber._get_backend`).
- **Depends on**: Module 1; `GoogleGenAIClient`.

### Module 3: Telegram voice-reply wiring
- **Path**: `integrations/telegram/wrapper.py` (+ `telegram/models.py`)
- **Responsibility**: campos `tts_*`/`reply_in_kind`; en `handle_voice`, tras la
  respuesta del agente, sintetizar y `bot.send_voice` si procede; degradación.
- **Depends on**: Modules 1-2.

### Module 4: Exports
- **Path**: `voice/__init__.py` (o `voice/tts/__init__.py`)
- **Responsibility**: exportar `VoiceSynthesizer`/`AbstractTTSBackend`/`TTSConfig`.
- **Depends on**: Modules 1-3.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_tts_config_defaults` | M1 | Defaults válidos (`backend="google"`, mime ogg). |
| `test_synthesizer_lazy_backend` | M2 | `VoiceSynthesizer` crea el backend en el primer uso. |
| `test_google_backend_wraps_generate_speech` | M2 | `GoogleTTSBackend.synthesize` llama `generate_speech` y devuelve bytes (client mock). |
| `test_handle_voice_replies_with_voice` | M3 | Entrada voz + `reply_in_kind` → `bot.send_voice` llamado con bytes (synth mock). |
| `test_handle_voice_degrades_on_tts_error` | M3 | Si el synth lanza → responde solo texto, sin romper. |
| `test_tts_disabled_text_only` | M3 | `tts_enabled=False` → nunca llama al synth. |

### Integration Tests
| Test | Description |
|---|---|
| `test_voice_in_voice_out_flow` | Voice note (mock) → transcribe (mock) → agente (mock) → `send_voice` con audio del synth (mock). |
| `test_text_input_unaffected` | Mensaje de texto normal NO dispara TTS (cero regresión). |

### Test Data / Fixtures
```python
@pytest.fixture
def synth_mock():
    s = MagicMock()
    s.synthesize = AsyncMock(return_value=SynthesisResult(audio=b"OGG...", mime_format="audio/ogg"))
    return s
```

---

## 5. Acceptance Criteria

> Esta feature está completa cuando TODO lo siguiente es cierto:

- [ ] `AbstractTTSBackend` + `GoogleTTSBackend` (envuelve `generate_speech`) +
  `VoiceSynthesizer` (backend lazy) funcionan y devuelven bytes de audio.
- [ ] En Telegram, una entrada de **voz** con `tts_enabled` + `reply_in_kind`
  produce una **nota de voz** de respuesta (`bot.send_voice`) además del texto.
- [ ] **Degradación**: TTS no configurado/falla → solo texto, sin excepción.
- [ ] Config nueva es **opt-in** (`tts_enabled=False` por defecto); sin romper
  config existente.
- [ ] Mensajes de texto normales NO disparan TTS (cero regresión).
- [ ] Arquitectura lista para backends ElevenLabs/OpenAI (ABC), sin implementarlos.
- [ ] Tests: `pytest packages/ai-parrot-integrations/tests/ -k "tts or voice" -v` verde.
- [ ] Sin breaking changes en la API pública existente.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**

### Verified Imports
```python
from parrot.clients.google.generation import GoogleGenAIClient   # verified: clients/google/generation.py (generate_speech:411)
from parrot.models.outputs import SpeechGenerationPrompt, SpeakerConfig  # verified: models/outputs.py:237,229
from parrot.models.google import TTSVoice                        # verified: models/google.py:60
from parrot.integrations.telegram.wrapper import TelegramAgentWrapper   # verified (handle_voice:2888)
from aiogram.types import BufferedInputFile                      # aiogram (voice upload)
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/clients/google/generation.py
class GoogleGenAIClient:
    async def generate_speech(self, prompt_data: SpeechGenerationPrompt,
        model: Union[str, GoogleModel] = GoogleModel.GEMINI_2_5_FLASH_TTS,
        output_directory: Optional[Path] = None, system_prompt: Optional[str] = None,
        temperature: float = 0.7, mime_format: str = "audio/wav",
        user_id=None, session_id=None, max_retries: int = 3,
        retry_delay: float = 1.0) -> AIMessage:   # line 411 (returns AIMessage w/ audio)

# packages/ai-parrot/src/parrot/models/outputs.py
class SpeakerConfig(BaseModel): name; voice; gender                # line 229
class SpeechGenerationPrompt(BaseModel): speakers; model; ...      # line 237

# packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py
class TelegramAgentWrapper:
    def _get_transcriber(self) -> "VoiceTranscriber":             # line 2874 (lazy backend pattern)
    async def handle_voice(self, message: Message) -> None:       # line 2888
        # gates: _is_authorized, _check_authentication, self.config.voice_enabled (2925)
        # voice_config = self.config.voice_config (2934)

# packages/ai-parrot/src/parrot/notifications/__init__.py
class NotificationMixin:                                          # line 56
    async def send_telegram_message(self, message: str, chat, report=None,
        disable_notification=False, **kwargs) -> Dict[str, Any]:  # line 716

# packages/ai-parrot-integrations/src/parrot/voice/transcriber/  (mirror pattern)
#   transcriber.py (VoiceTranscriber), backend.py (AbstractTranscriberBackend),
#   google/openai/faster_whisper backends, models.py
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `GoogleTTSBackend.synthesize` | `GoogleGenAIClient.generate_speech` | method call | `generation.py:411` |
| voice-reply wiring | `TelegramAgentWrapper.handle_voice` | post-response branch | `wrapper.py:2888` |
| send voice note | aiogram `bot.send_voice(BufferedInputFile(...))` | API call | aiogram |
| TTS structure | `voice/transcriber/` | mirror | `voice/transcriber/backend.py` |

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot.voice.tts` / `AbstractTTSBackend` / `VoiceSynthesizer`~~ — **NO existen** hoy. Los crea esta feature.
- ~~`TelegramAgentConfig.tts_enabled` / `reply_in_kind`~~ — no existen; los añade M3.
- ~~`generate_speech` devuelve bytes directos~~ — devuelve un `AIMessage` (con el audio dentro); extraer los bytes desde ahí.
- ~~`VoiceBot` (Gemini Live) es lo que se usa aquí~~ — NO; `VoiceBot` es el canal nativo voz↔voz **pospuesto**. Este spec usa `generate_speech` + `send_voice`.
- ~~ElevenLabs ya implementado~~ — NO existe; solo se deja la ABC para futuro.

### Patterns to Follow
- Espejar `voice/transcriber/` (backend ABC + lazy create + models Pydantic).
- aiohttp para llamadas HTTP de futuros backends (NUNCA `requests`/`httpx`).
- Temp-file cleanup en `finally` (como `handle_voice` para STT).
- Degradación: try/except alrededor del synth → fallback a solo texto.
- `self.logger`; config opt-in.

### Known Risks / Gotchas
- **`generate_speech` devuelve `AIMessage`**, no bytes: localizar el campo de
  audio en el `AIMessage` para extraer los bytes (documentar en M2).
- **Formato Telegram**: las notas de voz prefieren OGG/Opus; `generate_speech`
  da WAV/MP3/WebM. Puede requerir conversión a OGG (o usar `send_audio` si OGG no
  es viable). Open Question.
- **Latencia TTS**: usar typing/record indicator; no bloquear el chat
  indefinidamente.
- **Costo**: TTS por cada respuesta de voz; `reply_in_kind` controla cuándo.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| (posible) ffmpeg/pydub | opcional | Conversión a OGG/Opus si Telegram lo exige. (Open Question) |

---

## 8. Open Questions

> Resueltas por el usuario antes de redactar este spec:

- [x] ¿Canal voz↔voz nativo ahora? — *Resuelto*: **NO**; pospuesto. Este spec es
  reply de voz sobre Telegram texto. Reflejado en Non-Goals.

> Pendientes (decidibles en implementación):

- [ ] ¿Telegram acepta el formato de `generate_speech` (WAV/MP3) vía `send_voice`,
  o hay que convertir a OGG/Opus (ffmpeg/pydub) o usar `send_audio`? — *Owner:
  implementador M3*.
- [ ] ¿Dónde extraer los bytes de audio del `AIMessage` que devuelve
  `generate_speech`? — *Owner: implementador M2*.
- [ ] ¿"modo voz" persistente por chat (toggle por comando) además de
  `reply_in_kind`? — *Owner: usuario* (preferencia: empezar con `reply_in_kind`).

---

## Worktree Strategy

- **Default isolation unit**: `per-spec` — M1→M4 secuenciales; M1-M2/M4 en
  `voice/tts/`, M3 en el wrapper. Sin paralelismo útil.
- **Cross-feature dependencies**: ninguna dura. **Sinergia** con FEAT-209/#1 y
  FEAT-208/#3 (que pueden usar `VoiceSynthesizer` + envío proactivo para
  notificar resultados por voz). Independiente y mergeable solo.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-05-31 | jesuslarag (via Claude) | Initial draft — TTS desacoplado (wraps generate_speech) + voice-reply wiring en Telegram. Canal voz↔voz nativo pospuesto. |
