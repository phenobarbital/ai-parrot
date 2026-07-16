---
type: Wiki Overview
title: Briefing — Integración de LiveAvatar (LITE Mode) con ai-parrot
id: doc:sdd-proposals-liveavatar-ai-parrot-briefing-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Dotar al `AgentChat` de ai-parrot de un **avatar parlante** (vídeo con lip-sync)
  que
---

# Briefing — Integración de LiveAvatar (LITE Mode) con ai-parrot

> Documento de exploración para handoff a Claude Code. Pensado para implementarse
> de forma interactiva contra el codebase vivo, **no** como spec cerrada.
> Las secciones "NO existe todavía" y "Preguntas abiertas" son deliberadas:
> sirven para evitar que Claude Code invente APIs o asuma comportamiento no verificado.

---

## 0. Objetivo

Dotar al `AgentChat` de ai-parrot de un **avatar parlante** (vídeo con lip-sync) que
verbalice las respuestas del agente. ai-parrot ya gestiona agente, tools, outputs y
persistencia; el avatar es una **capa de presentación de voz/vídeo**, no un segundo cerebro.

Se evalúan dos modos de integración:

- **Opción A — Avatar como "boca" del AgentChat.** Sin STT ni LLM de LiveKit. ai-parrot
  resuelve el turno completo y su texto se convierte a voz con un TTS propio que empuja PCM
  al avatar.
- **Opción C — Híbrido voz-nativo.** Pipeline de voz de LiveKit (STT + VAD + turn-detection +
  TTS + avatar), pero el "cerebro" es ai-parrot, inyectado sustituyendo el nodo LLM. La
  respuesta se bifurca: texto plano → TTS → avatar; outputs estructurados (charts, data,
  canvas) → UI del AgentChat por el WebSocket/REST actuales.

> La opción B (reemplazar solo el LLM manteniendo STT+TTS, sin bifurcar outputs) es un
> subconjunto de C y se omite aquí salvo como hito intermedio de C.

---

## 1. Hechos verificados

### 1.1 Modo del starter: LITE

El starter `heygen-com/liveavatar-starter-livekit-agent-python` usa **LITE Mode**:
LiveAvatar solo hace el vídeo/lip-sync en tiempo real; STT, LLM y TTS los pones tú.
(Existe también FULL Mode, donde LiveAvatar corre todo el pipeline — ver §6, alternativa.)

### 1.2 API HTTP de LiveAvatar (verificado en `src/liveavatar_client.py` y API reference)

Base URL: `https://api.liveavatar.com`. Auth con header `X-API-KEY: <api_key>` salvo
`start_session`, que usa `Authorization: Bearer <session_token>`.

| Endpoint | Método | Auth | Devuelve |
|---|---|---|---|
| `/v1/sessions/token` | POST | `X-API-KEY` | `session_id`, `session_token` |
| `/v1/sessions/start` | POST | `Bearer session_token` | `livekit_url`, `livekit_agent_token`, `livekit_client_token`, `ws_url`, `max_session_duration` |
| `/v1/sessions/stop` | POST | `X-API-KEY` o `Bearer` | — |
| `/v1/sessions/keep-alive` | POST | — | mantener viva la sesión |
| `/v1/sessions/{id}/transcript` | GET | — | transcript de la sesión |

Body de `create_session_token` (LITE): `{ mode: "LITE", avatar_id, is_sandbox, video_settings: {quality, encoding}, [max_session_duration], [livekit_config] }`.

- **Sin `livekit_config`** → LiveAvatar provisiona la sala (Flow 1, "hosted").
- **Con `livekit_config`** (`{livekit_url, livekit_room, livekit_client_token}`) → el avatar
  entra como participante a una sala **tuya** (Flow 2, "BYO LiveKit").

Referencia: `https://docs.liveavatar.com/llms.txt` (índice completo) y
`https://docs.liveavatar.com/api-reference/...`.

### 1.3 Protocolo WebSocket de LITE Mode — CRÍTICO (verificado en docs/lite-mode/events)

El `ws_url` que devuelve `start_session` es el canal hacia el media-server del avatar.

**Comandos que envías:**

| Evento | Payload | Nota |
|---|---|---|
| `agent.speak` | `{type, audio: <base64>}` | **PCM 16-bit, 24 kHz, mono**. Chunk ~1s. Máx 1 MB/paquete. |
| `agent.speak_end` | `{type, event_id}` | fin de una locución |
| `agent.interrupt` | `{type}` | corta y vacía lo programado (barge-in) |
| `agent.start_listening` / `agent.stop_listening` | `{type, event_id}` | estados de escucha |
| `session.keep_alive` | `{type, event_id}` | **timeout de inactividad 5 min**; enviar periódicamente |

**Eventos que recibes:** `session.state_updated` (`connected`/`connecting`/`closed`/`closing`),
`agent.speak_started`, `agent.speak_ended`.

> ⚠️ **No hay comando de "hablar texto" en LITE Mode.** El avatar solo reproduce PCM.
> Esto es lo que obliga a tener TTS propio en la opción A.
> ⚠️ Esperar a `session.state_updated == "connected"` antes de enviar comandos.

El starter ya implementa este protocolo en `src/avatar_ws.py` (clase `AvatarWebSocket`):
resampleo a 24 kHz, mixdown a mono, troceo (primer chunk 400 ms para bajar TTFB, luego 1 s),
reconexión con replay del `start`, y métodos `start_speaking` / `send_audio_frame` /
`finish_speaking` / `interrupt`. **Es reutilizable tal cual en ambas opciones.**

### 1.4 Pipeline y agente del starter (verificado en `src/`)

- `pipeline.py` → `build_session(vad)` arma `AgentSession(stt=inference.STT(deepgram/nova-3),
  llm=inference.LLM("openai/gpt-5.3-chat-latest"), tts=inference.TTS(cartesia/sonic-3),
  turn_detection=MultilingualModel(), vad=vad, preemptive_generation=True)`.
  **`llm=` es el nodo que sustituimos por ai-parrot en la opción C.**
- `agent.py` → `LiveAvatarAgent(Agent)` define `instructions` y sobreescribe `tts_node`,
  bifurcando cada frame al `avatar_ws.send_audio_frame()` antes de cederlo. **Este es el
  patrón de override que replicamos para `llm_node`.**
- `worker.py` → `AgentServer`, `prewarm` (carga Silero VAD), entrypoint `@server.rtc_session`.
  Lee `ctx.job.metadata` como JSON `{ws_url, session_id}` → **punto natural para inyectar
  `tenant_id` y `agent_id`/`agent_name` de ai-parrot.** Registra `stop_session` como shutdown callback.
- `liveavatar_hosted_demo.py` / `byo_livekit_demo.py` → orquestadores de cada flow.
- `viewer/index.html` → cliente LiveKit vanilla (referencia, no producción): se conecta con
  `livekit_client_token`, publica micro, pinta `<video>`/`<audio>`.

Facturación: STT/LLM/TTS pasan por el inference gateway de **LiveKit Cloud** (tus créditos),
incluso en el flow hosted. Avatar/minutos por **LiveAvatar**. `is_sandbox=true` no quema
créditos de avatar pero está cap-eado en duración.

### 1.5 Override de `llm_node` en LiveKit Agents 1.x (verificado en docs API)

Firma (Python, `~= 1.5`):

```python
def llm_node(
    self,
    chat_ctx: llm.ChatContext,
    tools: list[llm.Tool],
    model_settings: ModelSettings,
) -> AsyncIterable[llm.ChatChunk | str | FlushSentinel] | Coroutine[...]:
    ...
    return Agent.default.llm_node(self, chat_ctx, tools, model_settings)
```

Puntos confirmados:
- Es el reemplazo 1.x de `before_llm_cb`, pensado explícitamente para "integrar un LLM propio
  sin crear un plugin".
- **Puede hacer `yield` de `str` planos** (además de `ChatChunk`): el nodo TTS los consume.
  → la opción C puede emitir el texto de ai-parrot directamente, token a token o por bloques.
- `chat_ctx` es el historial; el último `ChatMessage` de rol `user` es el texto transcrito por STT.

### 1.6 ai-parrot — superficie verificada (project knowledge)

REST (`src/lib/api/agent.ts`, `src/lib/api/client.ts`):
- `POST /api/v1/agents/chat/{agentName}` y `POST /api/v1/agents/chat/{agentName}/{methodName}`.
- El cliente añade `output_format: 'json'`.
- `AgentChatRequest`: `{ ws_channel_id?, query, session_id?, turn_id?, data?, output_mode?, format_kwargs?, llm? }`.
- `AgentChatResponse`: `{ input, output, data, response (markdown), output_mode, code,
  metadata: {model, provider, session_id, turn_id, response_time, is_error}, sources, tool_calls }`.

WebSocket (`src/lib/services/websocket-service.ts`, `src/lib/stores/websocket.svelte.ts`):
- Endpoint `/ws/userinfo`. Auth `{type:'auth', token}` → `auth_success`.
- Suscripción por canal: `{type:'subscribe', channel}` / `unsubscribe`. Dispatch por `message.type`.
- El payload de chat manda `ws_channel_id: sessionId` (= canal de eventos del turno).

Persistencia (`src/lib/api/chatInteraction.ts`): `/api/v1/chat/interactions` (Redis + DocumentDB),
con `session_id`, `agent_id`, `turn_id`, `output`, `tool_calls`, `sources`, etc.

Multi-tenant (`src/lib/api/programs.ts`, `navauth`): `programs_user`, sesión con `programs`,
`domain`, `groups`. El `tenant_id` se hila por auth/telemetría (patrón ya establecido).

---

## 2. Opción A — Avatar como "boca" del AgentChat

### 2.1 Idea

El turno lo resuelve ai-parrot por el camino actual (texto entra por el chat o por STT de
navegador; el agente responde). Cuando llega la respuesta, su **texto plano** se sintetiza con
un TTS propio y el PCM se empuja al avatar vía el `AvatarWebSocket`. No se usa el pipeline de
voz de LiveKit (ni `AgentSession`, ni STT/LLM/TTS de LiveKit, ni el worker).

### 2.2 Flujo

```
[Navegador] texto / STT propio (Web Speech API)
     │
     ▼
[ai-parrot] POST /api/v1/agents/chat/{agent}  ──►  response (markdown) + outputs
     │                                                    │
     │ texto "hablable" (markdown aplanado)               └─►  AgentChat UI (charts, canvas)
     ▼
[TTS propio]  texto → PCM 24kHz mono 16-bit
     │
     ▼
[AvatarWebSocket]  agent.speak (PCM) → agent.speak_end
     │
     ▼
[LiveAvatar media-server]  lip-sync → vídeo
     │
     ▼
[Navegador]  sala LiveKit con livekit_client_token  →  <video>/<audio>
```

### 2.3 Cobertura — qué resuelve LiveAvatar y qué pones tú

| Pieza | Estado |
|---|---|
| Sesión + tokens + sala LiveKit | ✅ LiveAvatar (`create_session_token` sin `livekit_config` → hosted; o con → BYO) |
| WS de audio + lip-sync + vídeo | ✅ LiveAvatar + `avatar_ws.py` reutilizable |
| Cerebro (agente, tools, outputs) | ✅ ai-parrot existente |
| **TTS texto→PCM** | ❌ **lo pones tú** (LITE no tiene text-speak) |
| STT (si quieres voz de entrada) | ❌ tú (Web Speech API en navegador, ya explorado) |
| Aplanado markdown→texto hablable | ❌ no existe (ver §5) |
| keep_alive + stop_session | ❌ tú (lifecycle, ver §4) |

### 2.4 TTS — decisión necesaria

Como LITE exige PCM, necesitas un TTS que produzca 24 kHz mono 16-bit. Candidatos del
ecosistema ya explorado: Kokoro, Coqui, o un proveedor cloud (Cartesia/ElevenLabs/Deepgram).
- TTS propio local (Kokoro/Coqui) → coste marginal cero, control total, latencia según hardware.
- TTS cloud → menos infra, pero coste por carácter y otra dependencia.
- Idealmente **streaming**: trocear el texto en frases y sintetizar/emitir por chunks para bajar TTFB.

### 2.5 Archivos a crear/tocar (orientativo, confirmar en codebase)

- **Backend ai-parrot (nuevo módulo):** un orquestador de sesión de avatar que (1) llame a
  `LiveAvatarClient` (portar `liveavatar_client.py`), (2) abra `AvatarWebSocket` (portar
  `avatar_ws.py`), (3) reciba texto del agente y lo pase por TTS→PCM→WS. Reutiliza el patrón
  async del proyecto (background tasks).
- **Backend:** endpoint para "iniciar sesión de avatar" que devuelva al frontend
  `livekit_url` + `livekit_client_token` (el viewer token), manteniendo el `agent_token`/WS en backend.
- **Frontend Svelte 5:** componente viewer (cliente `livekit-client`) embebible en `AgentChat`;
  enganchar el texto de respuesta del agente al disparador de "habla esto".
- **Reutilizables tal cual:** `avatar_ws.py`, `liveavatar_client.py` (adaptar a httpx/async del proyecto).

### 2.6 Limitaciones de A

- Sin VAD/turn-detection/barge-in de LiveKit: interrupciones y detección de fin de turno las
  gestionas tú (puedes usar `agent.interrupt` del WS para cortar al avatar).
- La "conversación de voz" es menos fluida que en C salvo que montes tu propia gestión de turnos.

---

## 3. Opción C — Híbrido voz-nativo (cerebro ai-parrot)

### 3.1 Idea

Se mantiene el pipeline de voz de LiveKit del starter (STT + VAD + turn-detection + TTS +
avatar), pero `LiveAvatarAgent` **sobreescribe `llm_node`** para llamar a ai-parrot en vez del
LLM de LiveKit. La respuesta se bifurca:
- **texto plano** → se hace `yield` desde `llm_node` → TTS → avatar (lo que se habla);
- **outputs estructurados** (charts, data, `tool_calls`, Block Canvas) → se publican a la UI del
  AgentChat por el WebSocket/REST actuales, compartiendo `session_id`.

### 3.2 Flujo

```
[Navegador] micro  ─►  sala LiveKit  ─►  [AgentSession: STT (LiveKit)]  ─►  texto transcrito
                                                                                │
                                              llm_node override  ◄──────────────┘
                                                    │
                                                    ▼
                                   [ai-parrot]  /api/v1/agents/chat/{agent}
                                       │                         │
                          texto (stream o aplanado)        outputs estructurados
                                       │                         │
                            yield str ─┤                         └─►  AgentChat UI (WS /ws/userinfo)
                                       ▼
                            [TTS (LiveKit)]  ─►  tts_node tee  ─►  [avatar_ws]  ─►  lip-sync → vídeo
                                                                                          │
                                                                                          ▼
                                                                                  [Navegador] <video>
```

### 3.3 Cobertura

| Pieza | Estado |
|---|---|
| Sesión + sala + WS audio + lip-sync | ✅ LiveAvatar + starter |
| STT, VAD, turn-detection, barge-in | ✅ LiveKit (gratis con el pipeline) |
| TTS texto→audio | ✅ LiveKit `inference.TTS` (o TTS propio si quieres ahorrar créditos) |
| Cerebro | ✅ ai-parrot vía `llm_node` |
| **`llm_node` override que llama a ai-parrot** | ❌ no existe (ver §5) |
| **Aplanado markdown→hablable + filtrado de outputs** | ❌ no existe |
| **Bifurcación outputs → AgentChat UI** | ❌ no existe (puente backend→`/ws/userinfo`) |
| keep_alive + stop_session | ⚠️ `stop_session` ya en `worker.py`; keep_alive a confirmar |

### 3.4 La costura: `llm_node`

Pseudocódigo ilustrativo (a validar contra la versión fijada de `livekit-agents` y la API real
de ai-parrot — **no copiar a ciegas**):

```python
class LiveAvatarAgent(Agent):
    async def llm_node(self, chat_ctx, tools, model_settings):
        user_text = _last_user_text(chat_ctx)          # último ChatMessage role=user
        # Llamada a ai-parrot. IDEAL: consumir stream por ws_channel_id (ver §5, P1).
        async for piece in ai_parrot_stream(
            agent_name=self._agent_name,
            query=user_text,
            session_id=self._session_id,
            tenant_id=self._tenant_id,
        ):
            if piece.kind == "speakable":
                yield piece.text            # str → TTS → avatar
            elif piece.kind == "structured":
                await self._publish_to_agentchat(piece)   # charts/data/canvas → UI
```

Detalles a resolver:
- **Streaming vs bloque:** si ai-parrot solo devuelve la respuesta completa (REST), `llm_node`
  recibe todo de golpe → TTFB alto. Si emite parciales por `ws_channel_id`, se streamea (P1 en §5).
- **`tool_calls` largos:** mientras el agente ejecuta tools, el avatar puede quedar mudo;
  considerar locuciones de relleno o estados de "pensando".
- **Aplanado:** quitar markdown, code fences, tablas, y todo lo que no debe leerse en voz alta.

### 3.5 Archivos a crear/tocar (orientativo)

- `agent.py` → añadir override `llm_node` (cliente ai-parrot + aplanado + bifurcación).
- `pipeline.py` → mantener STT/TTS de LiveKit; opcionalmente sustituir TTS por uno propio.
- `worker.py` → enriquecer metadata del job con `tenant_id`, `agent_name`, `session_id` de ai-parrot.
- **Backend ai-parrot:** (a) cliente/stream consumible desde `llm_node`; (b) puente que publique
  los outputs estructurados al canal `/ws/userinfo` que ya escucha el `AgentChat`.
- **Frontend:** viewer LiveKit embebido en `AgentChat`, compartiendo `session_id` para que avatar
  y canvas sean la misma conversación.

---

## 4. Transversal a A y C

### 4.1 Ciclo de vida de sesión
- `create_session_token` → `start_session` → (conversación) → `stop_session`.
- **Timeout de inactividad: 5 min.** Enviar `session.keep_alive` por el WS periódicamente
  mientras la conversación siga viva.
- Cerrar SIEMPRE con `stop_session` (incluido en rutas de error). Como red de seguridad,
  fijar `max_session_duration` en `create_session_token` para que LiveAvatar cierre sesiones
  abandonadas (cubre SIGKILL).

### 4.2 Multi-tenancy
- Propagar `tenant_id` por la metadata del job de LiveKit (`worker.py` ya parsea JSON) y por
  cada llamada a ai-parrot, alineado con el patrón existente de auth/telemetría.
- Una sesión de avatar = un `tenant_id` + un `agent_name` + un `session_id` de ai-parrot.

### 4.3 Despliegue (de las propias docs)
- El proceso del agente es **stateful y de vida larga** (sala LiveKit + WS avatar + streams).
  No encaja en request/response clásico.
- Patrón 1: spawn por sesión (simple; cold start por sesión).
- Patrón 2: pool de workers calientes + cola (cold start amortizado; mejor para concurrencia).
- En flow hosted, `lk agent deploy` **no** aplica (la sala es de LiveAvatar); se self-hostea
  un proceso largo. En flow BYO sí aplica.

### 4.4 Telemetría
- Encaja con el `AbstractLLMClient` + `TelemetryManager` ya diseñados: la latencia STT/LLM/TTS,
  el TTFB del avatar y la duración de sesión son métricas naturales por `tenant_id`.

---

## 5. NO existe todavía / a verificar (anti-alucinación)

| # | Item | Por qué importa | Cómo resolver |
|---|---|---|---|
| P1 | **¿ai-parrot emite tokens parciales por `ws_channel_id`, o `/agents/chat` es solo request/response?** | Decide el TTFB del avatar (streaming vs esperar respuesta entera). Evidencia frontend: el cliente hace `await` de la respuesta REST completa → apunta a NO streaming, pero `ws_channel_id` sugiere que hay eventos. | Revisar el backend del endpoint de chat y el publisher del canal WS. |
| P2 | **Campo de "texto hablable".** ai-parrot devuelve `response` en markdown + outputs. No hay un texto limpio para TTS. | Sin aplanado, el avatar leería sintaxis markdown. | Construir un flattener (quitar md/code/tablas) o añadir un campo `speech` en el backend. |
| P3 | **Código de integración del avatar en ai-parrot.** | No existe nada de LiveAvatar/LiveKit en el codebase aún. | Crear módulo backend + componente viewer frontend. |
| P4 | **Puente outputs estructurados → `/ws/userinfo`** (opción C). | El AgentChat ya escucha ese WS, pero falta que el turno conducido por `llm_node` publique ahí sus charts/data/canvas. | Definir el contrato de mensajes y el canal. |
| P5 | **Firma exacta de `llm_node`** en la versión de `livekit-agents` que se fije. | La API de nodos ha cambiado entre versiones; el concepto es estable, los tipos no siempre. | Fijar versión en `pyproject.toml` y validar contra su doc/typeshed. |
| P6 | **TTS propio: formato y latencia.** | LITE exige PCM 24 kHz mono 16-bit; el TTS debe producir eso (o resamplear). | Elegir TTS (Kokoro/Coqui/cloud) y validar formato + streaming. |
| P7 | **`keep_alive`: endpoint HTTP vs evento WS.** | Hay `session.keep_alive` en el WS y `/v1/sessions/keep-alive` en HTTP. | Confirmar cuál usar en el flow elegido. |

---

## 6. Alternativa a evaluar antes de fijar rumbo: FULL Mode + Custom LLM

LiveAvatar tiene **FULL Mode**, donde LiveAvatar corre TODO el pipeline (STT + TTS + vídeo) y
llama a **tu LLM** vía su "Custom LLM Integration". Si ai-parrot pudiera exponer un endpoint de
chat **compatible con OpenAI (streaming)**, este modo podría dar "ai-parrot es el cerebro, el
avatar habla" **sin** worker de LiveKit, sin plumbing de PCM y sin TTS propio.

- Pro: mucho menos código de infra; LiveAvatar gestiona voz y vídeo.
- Contra: menos control del pipeline; requiere que ai-parrot hable "OpenAI-compatible" y
  encajar sus outputs estructurados (que no caben en el formato chat estándar) por otro canal.

> Recomendación: dedicar 30–60 min a leer `docs/full-mode/custom-llm` y decidir A/C vs FULL
> antes de escribir código. No expande el alcance pedido (A y C), pero puede ahorrar trabajo.

---

## 7. Preguntas abiertas, particionadas

### 7.1 Resolubles leyendo el codebase (para Claude Code)
- P1 (streaming por `ws_channel_id`), P2 (¿hay texto limpio?), P4 (contrato del canal WS),
  P5 (versión y firma de `llm_node`).
- ¿Cómo se obtiene hoy `agent_name`/`agent_id` y `session_id` en el frontend del AgentChat?
- ¿Dónde y cómo se inyecta `tenant_id` en las llamadas actuales (auth/telemetría)?

### 7.2 Decisiones de producto / arquitectura (para Jesús)
- A vs C vs FULL Mode (§6).
- TTS: propio (Kokoro/Coqui) vs cloud; local vs servicio.
- STT de entrada en A: Web Speech API del navegador vs STT dedicado backend.
- Patrón de despliegue (spawn-por-sesión vs pool).
- ¿El avatar es opt-in por usuario/programa (multi-tenant) o global?

---

## 8. Orden de construcción sugerido (handoff a Claude Code)

1. **Antes de nada:** instalar las Agent Skills oficiales de LiveAvatar, diseñadas justo para
   esto: `npx skills add heygen-com/liveavatar-agent-skills` (incluye `liveavatar-integrate` y
   `liveavatar-debug`). El repo del starter además trae `.claude/skills/livekit-agents`.
2. Resolver P1 y P2 leyendo el backend (deciden toda la latencia y el aplanado).
3. **Spike de C, sin bifurcación (= opción B):** override `llm_node` que llama a ai-parrot y
   hace `yield` del texto aplanado; validar conversación de voz + avatar end-to-end en sandbox.
4. Añadir bifurcación de outputs → `/ws/userinfo` (completa C) y compartir `session_id` con AgentChat.
5. Lifecycle robusto: `keep_alive`, `stop_session` en todos los caminos, `max_session_duration`.
6. Multi-tenancy: `tenant_id` en metadata del job + llamadas a ai-parrot.
7. (Si se elige A) Montar TTS propio + orquestador de sesión usando `avatar_ws.py`/`liveavatar_client.py`.

---

## 9. Referencias

- Starter: `https://github.com/heygen-com/liveavatar-starter-livekit-agent-python`
- Guía LiveKit custom agent: `https://docs.liveavatar.com/docs/guides/livekit/custom-livekit-agent`
- Índice docs (para fetch programático): `https://docs.liveavatar.com/llms.txt`
- LITE Mode events (protocolo WS): `https://docs.liveavatar.com/docs/lite-mode/events`
- LITE Mode overview / lifecycle / configuration: `https://docs.liveavatar.com/docs/lite-mode/overview`
- FULL Mode custom LLM: `https://docs.liveavatar.com/docs/full-mode/custom-llm`
- API reference sesiones: `https://docs.liveavatar.com/api-reference/sessions/create-session-token`
- LiveKit Agents — `llm_node` (Python API ref): `https://docs.livekit.io/reference/python/livekit/agents/voice/index.html`
- LiveKit Agents — migración v0→1.x (`before_llm_cb` → `llm_node`): `https://docs.livekit.io/agents/v0-migration/python/`
- Agent Skills LiveAvatar: `https://github.com/heygen-com/liveavatar-agent-skills`

> ai-parrot (verificado en project knowledge): `src/lib/api/agent.ts`, `src/lib/api/client.ts`,
> `src/lib/types/agent.ts`, `src/lib/services/websocket-service.ts`, `src/lib/api/chatInteraction.ts`.
