---
id: FEAT-560
title: "VoiceBot: paridad Nova 2 Sonic para herramientas y salida dual"
slug: voicebot-liveavatar-implementation
type: feature
mode: enrichment
status: accepted
source:
  kind: inline
  jira_key: null
  jira_url: null
  fetched_at: 2026-09-07
  summary_oneline: "Nova como proveedor intercambiable de VoiceBot con herramientas, audio y salida estructurada"
overall_confidence: medium
base_branch: dev
research_state: sdd/state/FEAT-560/
created: 2026-09-07
updated: 2026-09-07
---

# FEAT-560 — VoiceBot: paridad Nova 2 Sonic para herramientas y salida dual

## 0. Origin

> $sdd-proposal voicebot-liveavatar-implementation -- VoiceBot fue diseñado para ser usado en modo websocket con Google Gemini Live client, con la reciente incorporación de AWS Nova 2 Audio necesitamos que este cliente funcione como un drop-in replacement de Google Gemini Live Client, permitiendo tool-calling y dual output (audio + structured output) como actualmente soporta el cliente Google Gemini Live Client

Fuente exacta: [source.md](../state/FEAT-560/source.md). Identidad de investigación local; la especificación reservará su ID formal posteriormente.

## 1. Synthesis Summary

VoiceBot ya permite seleccionar Nova y comparte el contrato de streaming con Gemini [F001]. La brecha confirmada está en las herramientas: Gemini conserva el texto para voz y los datos visuales del resultado; Nova atraviesa una ruta que los descarta antes de construir la respuesta [F002, F003]. Se propone completar esa paridad y demostrarla por WebSocket, incluyendo la integración de audio existente con LiveAvatar según el alcance aceptado [F004]. La salida estructurada aceptada es la actual de herramientas; JSON del modelo validado contra un esquema queda fuera de alcance. Confianza alta en la localización y media en el alcance.

## 2. Codebase Findings

### 2.1 Localization

| Path | Symbol | Lines | Evidence |
|---|---|---|---|
| `packages/ai-parrot/src/parrot/bots/voice.py` | `VoiceBot._resolve_llm_config` | 205-220 | F001 |
| `packages/ai-parrot/src/parrot/bots/voice.py` | `VoiceBot._create_llm_client` | 296-312 | F001 |
| `packages/ai-parrot/src/parrot/bots/voice.py` | `VoiceBot.ask_stream` | 600-616 | F001 |
| `packages/ai-parrot/src/parrot/clients/protocols.py` | `VoiceCapable` | 17-23 | F001 |
| `packages/ai-parrot/src/parrot/models/voice.py` | `VoiceStreamOptions` | 175-183 | F001 |
| `packages/ai-parrot/src/parrot/models/voice.py` | `LiveVoiceResponse` | 370-379 | F001 |
| `packages/ai-parrot-client-google/src/parrot/clients/google/live.py` | `LiveToolAdapter.execute_tool` | 285-306 | F002 |
| `packages/ai-parrot-client-google/src/parrot/clients/google/live.py` | `GeminiLiveClient.stream_voice` | 1074-1089 | F002 |
| `packages/ai-parrot/src/parrot/tools/abstract.py` | `ToolResult` | 250-266 | F002 |
| `packages/ai-parrot-client-amazon/src/parrot/clients/amazon/nova/audio.py` | `NovaAudio._flush_pending_tools` | 785-798 | F003 |
| `packages/ai-parrot/src/parrot/clients/base.py` | `AbstractClient._execute_tool` | 1456-1467 | F003 |
| `packages/ai-parrot/src/parrot/tools/manager.py` | `ToolManager.execute_tool` | 1807-1820 | F003 |
| `packages/ai-parrot-integrations/src/parrot/voice/handler.py` | `_HandlerVoiceSession.build_frames` | 437-458 | F004 |
| `packages/ai-parrot-integrations/src/parrot/voice/handler.py` | `_HandlerVoiceSession._relay` | 511-545 | F004 |
| `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/voice_session.py` | `VoiceAvatarSession` | 1-7 | F004 |
| `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/voice_session.py` | `VoiceAvatarSession.speak` | 223-233 | F004 |
| `packages/ai-parrot-client-amazon/src/parrot/clients/amazon/nova/audio.py` | `NovaAudio` | 303-305 | F004 |
| `packages/ai-parrot-client-amazon/src/parrot/clients/amazon/nova/audio.py` | `NovaAudio._build_tool_configuration` | 622-631 | F005 |
| `packages/ai-parrot-client-amazon/src/parrot/clients/amazon/nova/audio.py` | `NovaAudio._build_prompt_start` | 643-665 | F005 |
| `packages/ai-parrot-client-amazon/src/parrot/clients/amazon/nova/audio.py` | `NovaAudio._send_tool_result` | 667-683 | F005 |
| `packages/ai-parrot-client-amazon/src/parrot/clients/amazon/nova/audio.py` | `NovaAudio.stream_voice` | 1087-1110 | F005 |
| `packages/ai-parrot/tests/clients/test_nova_tool_result.py` | `_run` | 32-47 | F007 |
| `packages/ai-parrot/tests/clients/test_live_tool_routing.py` | `VoiceTool` | 14-23 | F007 |
| `packages/ai-parrot/tests/voice/test_provider_conformance.py` | `TestDropInEquivalence` | 147-169 | F007 |
| `packages/ai-parrot-integrations/tests/voice/test_voicechat_avatar_integration.py` | `test_gemini_audio_to_avatar_end_to_end` | 55-67 | F007 |
| `packages/ai-parrot-client-amazon/src/parrot/clients/amazon/nova/client.py` | `NovaClient` | 30-43 | F008 |
| `packages/ai-parrot-client-amazon/pyproject.toml` | `project.dependencies` | 15-23 | F008 |

### 2.2 Constraints Discovered

- Preservar `ToolResult.voice_text` y `display_data` antes de extraer/comprimir el resultado; añadir metadata después de `_execute_tool` no recupera los campos perdidos [F002, F003].
- Mantener controles de ejecución, credenciales, hooks, tratamiento de errores y contexto de sesión confiable. Una llamada directa a la implementación privada de la herramienta eludiría el contrato público; copiar solamente el adaptador de Gemini tampoco acredita preservar todos los controles del manager [F002, F006].
- Mantener los frames `response_chunk`, `display_data`, `tool_call`, finalización y transcripciones existentes, y PCM mono de 16 bits a 24 kHz hacia LiveAvatar [F004].
- La paridad solicitada se acota a conversación con tools y salida dual; no exige voces idénticas, continuidad entre proveedores ni equivalencia nativa de STT-only. La diferencia STT-only se documenta en el cliente inspeccionado [F001, F005].
- Los proveedores viven en paquetes satélite. El SDK opcional de voz está documentado como instalación manual; este trabajo documental no añade dependencias [F008, F009].
- Nova 2 Sonic soporta herramientas y exige responder a las llamadas incluso ante errores; no se deduce de ello soporte nativo de JSON-schema junto a audio [F010; [AWS](https://docs.aws.amazon.com/nova/latest/nova2-userguide/sonic-tool-configuration.html)].

### 2.3 Recent History

La extracción de clientes aparece en `c00b575cd` (2026-09-04, Jesus); el formateo posterior en `14b548483` (2026-09-05, Jesus). HEAD investigado: `3d03bb2cdb4ef4a864fc51ec89c8dfb14781599e`. Se actualizaron las rutas de la wiki al layout real, sin atribuir la brecha a esos commits [F009].

## 3. Probable Scope

### Resultado esperado

Una herramienta puede devolver una frase breve para la conversación y un objeto visual para el frontend. Con cualquiera de los dos proveedores, la frase alimenta la respuesta hablada y el objeto llega al navegador por el contrato actual. Los bytes de audio alimentan también el avatar cuando está habilitado [F002, F004]. Esto no implica que ambos proveedores deban producir exactamente el mismo texto, audio o latencia.

### Cambios propuestos

1. Definir una ruta optativa que conserve el resultado completo de herramientas con los mismos controles del manager. Preferencia: extensión acotada en la capa de herramientas, conservando el comportamiento por defecto de sus consumidores de texto. La firma y el diseño concreto se deciden en spec; no se propone modificar globalmente `AbstractClient` [F003, F006].
2. Adaptar el recorrido de voz Nova para elegir el texto hablado, publicar `metadata["display_data"]`, conservar la correlación de cada herramienta y representar estados no exitosos como tales. No almacenar resultados en atributos globales compartidos entre sesiones [F002, F003, F005, F006].
3. Añadir una prueba con servidor simulado que no continúe hasta recibir el resultado de la herramienta. Si reproduce la espera circular, eliminar la dependencia del siguiente evento para ejecutar. Probar herramientas lentas y cierre/cancelación; paralelismo de tools no demuestra por sí solo que el receptor siga atendiendo interrupciones [F005, F010].
4. Extender los tests de conformidad y la integración WebSocket/LiveAvatar con herramientas reales sobre transportes de proveedor simulados. Los tests actuales de Nova sustituyen precisamente la llamada que pierde el resultado [F007].

### Criterios candidatos de aceptación

- Seleccionar Nova mediante configuración preserva el recorrido de VoiceBot y el formato de mensajes al navegador [F001, F004].
- Herramienta con `voice_text` y `display_data`: el resultado enviado al proveedor contiene el contenido hablado, y la salida visual llega al frontend sin ser sustituida por transcripción [F002, F003].
- Herramientas sin campos de voz siguen funcionando; errores, denegación, herramienta desconocida y argumentos inválidos producen resultados controlados y ninguna salida visual de éxito [F002, F005, F006].
- Contexto real de usuario/sesión/turno llega a las herramientas que lo aceptan sin permitir que el modelo sustituya la identidad confiable [F006].
- Cada tool call finalizada obtiene respuesta sin depender de que el proveedor envíe un evento adicional. Una prueba interactiva verifica progreso, frente a las listas precargadas actuales [F005, F007, F010].
- Herramientas secuenciales y paralelas conservan asociación entre IDs, resultados y datos visuales; el snapshot acumulado al cierre no duplica efectos visuales. La política de eventos frente al snapshot final debe quedar explícita en spec [F004, F005].
- Con avatar habilitado, audio, interrupción y final de turno alcanzan la integración existente, y un fallo del avatar mantiene operativo el WebSocket [F004].
- Los casos Gemini existentes siguen pasando, y la nueva suite falla sobre la pérdida de datos actual de Nova [F007, F011].

### Non-Goals

No crear otro proveedor, rehacer la gestión de sesiones de avatar, implementar un nuevo modo FULL/WebRTC, ni añadir dependencias en esta fase. El JSON del modelo validado por esquema queda fuera de alcance; no se afirma que sea equivalente al canal visual actual [F001–F004, F008].

### Riesgos y decisiones de diseño

La extensión debe conservar permisos, guardrails, hooks y estados completos. El cliente base actual extrae payloads, por lo que el resultado completo debe obtenerse antes de esa reducción [F003, F006]. También hay que decidir el tratamiento de `display_data={}`: Gemini y el handler usan comprobaciones de verdad y actualmente no lo publican; la propuesta no cambia silenciosamente esa semántica [F002, F004]. El posible bloqueo del stream es una inferencia, no un incidente reproducido en AWS [F005, F010].

## 4. Confidence Map

| ID | Claim | Evidence | Confidence |
|---|---|---|---|
| C1 | VoiceBot ya selecciona Nova y consume el contrato común de voz. | F001 | high |
| C2 | Gemini separa voice_text y display_data de ToolResult. | F002 | high |
| C3 | El camino de herramientas Nova no conserva los campos multimodales. | F003 | high |
| C4 | WebSocket y LiveAvatar ya consumen la envoltura y PCM de 24 kHz. | F004 | high |
| C5 | El diferimiento de herramientas Nova puede causar espera circular si AWS espera el resultado. | F005, F010 | medium |
| C6 | Hay diferencias de contexto y controles que la solución debe conservar o reconciliar. | F006 | high |
| C7 | Las pruebas leídas no cubren la paridad dual completa con herramientas reales en Nova. | F007 | high |
| C8 | Reutilizar el resultado enriquecido y los consumidores existentes es el alcance probable. | F001, F002, F003, F004 | medium |

Distribución: 6 high, 2 medium, 0 low. Global: medium. La línea base de tests no eleva a high la compatibilidad real con servicios externos.

## 5. Open Questions

Resueltas por aceptación del alcance presentado. Respuesta literal del usuario: **«continuar con este alcance»**.

- **U1, resuelta** — Paridad con `ToolResult.voice_text` + `display_data`; no añadir JSON del modelo validado contra esquema sin herramientas.
- **U2, resuelta** — Validar tanto WebSocket como LiveAvatar usando la integración de audio existente.

Gate: **aceptado**. No quedan preguntas de producto bloqueantes. La spec debe concretar el contrato optativo de ejecución enriquecida y la prueba de progreso; el posible bloqueo no se presenta como reproducido.

## 6. Recommended Next Step

`$sdd-spec voicebot-liveavatar-implementation` — alcance aceptado y localización respaldada. La spec debe definir la extensión optativa en la capa de herramientas, estados/contexto/correlación y pruebas de conformidad e integración. No saltar directamente a tareas; no se ejecutó una sesión real AWS/LiveAvatar.

## 7. Research Audit

- [Estado](../state/FEAT-560/state.json), [plan](../state/FEAT-560/research_plan.json), [síntesis](../state/FEAT-560/synthesis.json), [hallazgos](../state/FEAT-560/findings/).
- Presupuesto estándar: 17/40 archivos de investigación, 17/25 búsquedas, 3/10 consultas git, profundidad 2/2. Wiki y plantillas excluidas del cómputo.
- Tiempo transcurrido registrado: 500.4 s frente a 300 s; incluye preparación de evidencias y espera de autorización del test. Investigación cerrada por límite temporal: **truncated=true**. No se hizo investigación adicional de prototipo ni smoke externo.
- Validación: **19 passed**, 8 warnings, 1.45 s en las dos suites de herramientas existentes [F011]. Log local: `artifacts/logs/voicebot_liveavatar_proposal_pytest.log`.
- No implementación modificada. Estado documental: **accepted**; revisión y alcance confirmados por el usuario.

## 8. Provenance

La tabla 2.1 enlaza cada localización con un hallazgo persistido, con extractos y líneas. F009 preserva historia, F010 referencia oficial y F011 validación. Los cambios futuros y criterios de aceptación son propuestas basadas en esas evidencias, no capacidades ya comprobadas.
