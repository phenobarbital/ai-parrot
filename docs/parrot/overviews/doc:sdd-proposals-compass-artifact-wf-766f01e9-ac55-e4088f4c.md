---
type: Wiki Overview
title: 'Cliente Bedrock async-first para Claude y Nova Sonic en ai-parrot: guía de
  diseño y patrones de código (mediados de 2026)'
id: doc:sdd-proposals-compass-artifact-wf-766f01e9-ac55-5ac0-86a0-78dd7870fc59-text-markdown-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: ai-parrot ya es async-first (aiohttp/navigator-api), monorepo uv, con clientes
  que implementan `AbstractClient` como async context managers (`GoogleGenAIClient`,
  `OpenAIClient`, `AnthropicClient`) y un `@tool`/`AbstractToolkit` que autogenera
  schemas desde docstrings y type hints
relates_to:
- concept: mod:parrot.clients.bedrock
  rel: mentions
---

# Cliente Bedrock async-first para Claude y Nova Sonic en ai-parrot: guía de diseño y patrones de código (mediados de 2026)

## TL;DR
- **Usa la Converse API (`converse`/`converse_stream`) como ruta primaria** para Claude en Bedrock: en 2026 tiene paridad de features con la Messages API nativa (tool use, `reasoningContent`/extended thinking, prompt caching con `cachePoint`, structured outputs GA desde el 4 de febrero de 2026, guardrails). Solo necesitas caer a `invoke_model` con payload Anthropic nativo para features de vanguardia que aún no expone Converse (adaptive thinking/effort, o modelos sin ARN-versioned ID como Opus 4.8/Fable 5, o cuando aparece un bug puntual de ConverseStream).
- **Para async, usa aioboto3/aiobotocore** (que envuelven boto3/botocore): soportan `converse`, `converse_stream`, `invoke_model` e `invoke_model_with_response_stream`. Para **Nova Sonic (bidireccional HTTP/2) boto3 NO sirve**: debes usar el SDK experimental `aws_sdk_bedrock_runtime` (Smithy, **Pre-Alpha, v0.7.0 del 23 jun 2026, Python ≥3.12**), que AWS advierte que "no debe usarse en producción" sin pinning estricto.
- **PII en voz**: los guardrails de Bedrock (sensitive information filters, ANONYMIZE/BLOCK) solo aplican a **texto**; para Nova Sonic aplica guardrails/`ApplyGuardrail` sobre las **transcripciones** (`textOutput`/ASR) en un pipeline propio, nunca sobre el audio en sí.

## Key Findings

### 1. Converse vs invoke_model para Claude (2026)
- **Recomendación de AWS y de la industria**: "Default to Converse API. Move to InvokeModel only if you need a provider-specific feature Converse does not expose." Converse da una interfaz uniforme sobre todos los modelos (Claude, Nova, Llama, Mistral, DeepSeek, etc.) con el mismo IAM role, KMS, VPC endpoints y logging.
- **Paridad de features en Converse (2026)**:
  - **Tool use / function calling**: `toolConfig` con `toolSpec` (name, description, `inputSchema.json`) y `toolChoice` (`auto`/`any`/`tool`). El modelo devuelve bloques `toolUse` con `stopReason=tool_use`; tú devuelves `toolResult`.
  - **Structured output**: GA desde el 4 de febrero de 2026. Según el anuncio de AWS "Structured outputs now available in Amazon Bedrock": *"Structured outputs is generally available for Anthropic Claude 4.5 models and select open-weight models across the Converse, ConverseStream, InvokeModel, and InvokeModelWithResponseStream APIs in all commercial AWS Regions where Amazon Bedrock is supported."* En Converse se usa `outputConfig.textFormat` con un JSON schema (requiere campo `name` y `additionalProperties: false` explícito); también `strict: true` en `toolSpec` para strict tool use. Ambos mecanismos pueden combinarse.
  - **Extended thinking / reasoning**: bloque `reasoningContent` (`reasoningText.text` + `signature`, o `redactedContent`). Debes reenviar el bloque con su `signature` sin modificar en turnos posteriores o Bedrock lanza `ValidationException` (bug común en frameworks que reconstruyen el turno assistant sin el bloque de reasoning). El thinking se pasa vía `additionalModelRequestFields={"thinking": {...}}` con `temperature=1.0`. Adaptive thinking (`{"thinking":{"type":"adaptive"}}` + `output_config.effort`) para Opus 4.6+ también se pasa por `additionalModelRequestFields`.
  - **Prompt caching**: bloque `cachePoint` (`{"type":"default"}` con `ttl` opcional `"5m"`/`"1h"`) en tools, system y messages (orden de proceso tools→system→messages). La respuesta devuelve `cacheReadInputTokens`/`cacheWriteInputTokens`/`cacheDetails`. TTL de 1h soportado en Claude Opus/Sonnet/Haiku 4.5. Límite de 4 breakpoints; lookback de ~20 content blocks (cuenta bloques, no tokens). No pongas `cachePoint` después de un `reasoningContent`.
  - **Guardrails**: `guardrailConfig` (guardrailIdentifier, guardrailVersion, trace) y bloques `guardContent`. Guardrails NO evalúa reasoning content blocks.
  - **Streaming**: ConverseStream emite `messageStart`, `contentBlockStart`, `contentBlockDelta` (text, `reasoningContent` parcial, `toolUse` parcial JSON), `contentBlockStop`, `messageStop`, `metadata` (usage/metrics).
  - **Latency-optimized / service tiers**: `performanceConfig.latency` y `serviceTier` (Standard/Priority/Flex) están en la firma de converse/invoke_model.
- **Solo vía invoke_model (payload nativo Anthropic, `anthropic_version: bedrock-2023-05-31`)**: los modelos Claude más nuevos **sin ARN-versioned ID** (Claude Fable 5, Opus 4.8, Opus 4.7) son alcanzables por InvokeModel pero "are omitted from the model table … because they do not have ARN-versioned model IDs". **Claude Sonnet 5 NO está disponible** en la superficie legacy de Bedrock; usa "Claude in Amazon Bedrock" (Messages API en `/anthropic/v1/messages` con SSE) o Claude Platform on AWS. En general, features de vanguardia de Anthropic llegan primero a la Messages API nativa que a Converse.
- **Contexto y modelos 2026**: Claude Fable 5, Opus 4.8, Opus 4.7, Opus 4.6 y Sonnet 4.6 tienen ventana de 1M tokens en Bedrock; otros (Sonnet 4.5, Sonnet 4) 200k. Bedrock limita payloads a 20 MB.
- **Cross-region inference (CRIS)**: usa inference profiles con prefijos geográficos `us.`, `eu.`, `apac.`, `jp.` (p.ej. `us.anthropic.claude-sonnet-4-5-20250929-v1:0`) o `global.`. Desde Sonnet 4.5, endpoints Global (routing dinámico, ~10% de ahorro en Sonnet 4.5) vs Regional (10% premium, data residency garantizada). Overhead de re-routing: milisegundos de uno o dos dígitos. Convención de model ID: los IDs antiguos usan sufijo `:0`; los nuevos usan alias sin versión (p.ej. `anthropic.claude-sonnet-4-6`).

### 2. Async: aioboto3 / aiobotocore vs SDK experimental Smithy
- **aioboto3/aiobotocore soportan bedrock-runtime**: `converse`, `converse_stream`, `invoke_model`, `invoke_model_with_response_stream`. `await client.converse(...)` funciona; para streaming se itera async sobre `response["stream"]`. Hubo un issue histórico (terricain/aioboto3 #341) por falta de bump de botocore, ya resuelto en versiones recientes.
- **EventStream async**: en aiobotocore el EventStream soporta iteración async (`async for event in response["stream"]`). Si dejas de consumir el stream antes de tiempo, ciérralo explícitamente. Bugs conocidos en boto3 sync: converse_stream con `citations` + `guardrailConfig` simultáneos puede dar `internalServerException`; y reportes de que converse_stream no continuaba tras `toolResult` (mitigación: usar `converse` no-stream para el loop de tools).
- **SDK experimental async (Smithy) para bidireccional**: `aws_sdk_bedrock_runtime` (import `aws_sdk_bedrock_runtime`), versión actual **0.7.0 (23 jun 2026)**, clasificado en PyPI **"Development Status :: 2 - Pre-Alpha"**, **Requires: Python >=3.12**. Dependencias: `smithy-core`, `smithy-aws-core` (SigV4, `EnvironmentCredentialsResolver`), `smithy-http` (clientes async aiohttp/awscrt), `smithy-aws-event-stream`, `awscrt`. Es el **único** camino Python para `invoke_model_with_bidirectional_stream` (Nova Sonic). **No es para producción**: el repo awslabs/aws-sdk-python (clients/aws-sdk-bedrock-runtime) advierte *"The aws_sdk_bedrock_runtime client is still under active developement. Changes may result in breaking changes prior to the release of version 1.0.0"*, y recomienda pinning estricto. Smithy-Java y Smithy-Kotlin ya son GA (marzo 2026), pero el generador Python sigue en desarrollo.
- **AsyncAnthropicBedrock (anthropic SDK)**: `pip install "anthropic[bedrock]"`, usa botocore internamente para auth (soporta credenciales por defecto, roles, session tokens). Da acceso a la **Messages API nativa** (thinking, tools, streaming) con tipos Pydantic. **Limitaciones**: no expone guardrails de Bedrock (`guardrailConfig`/`ApplyGuardrail` no son parte de la Messages API), ni Nova ni otros proveedores, ni el envelope normalizado de Converse; su cliente async puede envolver I/O sync salvo con `DefaultAioHttpClient`. Por eso un cliente bedrock-native (aioboto3) sigue siendo necesario si quieres guardrails, multi-proveedor y features Bedrock-específicas.

### 3. Nova Sonic / Nova 2 Sonic (speech-to-speech)
- **Modelos**: `amazon.nova-sonic-v1:0` (v1, abril 2025) y `amazon.nova-2-sonic-v1:0` (Nova 2, anunciado 2 dic 2025). Según el AWS News Blog "Introducing Amazon Nova 2 Sonic": *"Beyond the original English, French, Italian, German, and Spanish languages, Nova 2 Sonic now supports Portuguese and Hindi... The Tiffany voice, for example, can now speak all supported languages fluidly in a single interaction."* Nova 2 añade voces poliglotas, turn-taking controllability, cross-modal (voz+texto) y async tool calling.
- **Regiones Nova 2 (jun 2026)**: per AWS "Release notes for Amazon Nova 2": *"generally available in the US East (N. Virginia), US West (Oregon), Asia Pacific (Tokyo), and Europe (Stockholm) Regions. In addition, it is available through Amazon Connect in the following Regions: Asia Pacific (Singapore), Europe (London), Asia Pacific (Seoul), and Europe (Frankfurt)."* Sin cross-region inference y solo service tier Standard para Nova 2 Sonic.
- **API bidireccional**: `InvokeModelWithBidirectionalStream` sobre HTTP/2; boto3 NO la soporta (el propio blog de AWS dice: *"Python developers can use this new experimental SDK … We're working to add support to the other AWS SDKs"*). Ciclo de eventos de **entrada**: `sessionStart` (inferenceConfiguration + `turnDetectionConfiguration.endpointingSensitivity` HIGH/MEDIUM/LOW en Nova 2) → `promptStart` (textOutputConfiguration, audioOutputConfiguration `{mediaType audio/lpcm, sampleRateHertz, sampleSizeBits 16, channelCount 1, voiceId, encoding base64}`, toolConfiguration) → `contentStart` (SYSTEM text) → `textInput` → `contentEnd` → `contentStart` (AUDIO, audioInputConfiguration) → `audioInput` (base64 PCM, repetido) → `contentEnd` → [toolResult flow: `contentStart` TOOL → `toolResult` → `contentEnd`] → `promptEnd` → `sessionEnd`. Eventos de **salida**: `completionStart` → `contentStart` (generationStage FINAL/SPECULATIVE) → `textOutput` (ASR transcript o respuesta) → `audioOutput` (base64 PCM) → `toolUse` → `contentEnd` (stopReason PARTIAL_TURN/END_TURN) → `completionEnd` + `usageEvent`.
- **Audio**: entrada 16000 Hz, 16-bit PCM, mono, base64; salida 24000 Hz (config acepta 8000/16000/24000). voiceIds incluyen matthew, tiffany, amy, lupe, carlos, etc. (Nova 2 amplía la lista con olivia, tina, carolina, leo, kiara, arjun…). Límite de conexión 8 minutos (renovar pasando historial). **Barge-in** soportado nativamente.
- **Tool use mid-conversation**: se declara `toolConfiguration` en `promptStart`; el modelo emite `toolUse`; ejecutas y devuelves `toolResult` vía la secuencia `contentStart(TOOL)`/`toolResult`/`contentEnd` sin interrumpir el audio (async tool calling en Nova 2).
- **Integraciones**: Nova 2 Sonic integra con Amazon Connect, Twilio, Vonage, AudioCodes, LiveKit y Pipecat. Los samples oficiales (aws-samples/amazon-nova-samples) incluyen WebSocket server Python + React (optimizado para Chrome, requiere 16kHz), patrón WebRTC con Kinesis Video Streams, y un paquete CDK deployable con load testing.
- **Coste/latencia (fuentes de terceros, no docs primarias AWS)**: rywalker.com cita *"$3 per million speech input tokens and $12 per million speech output tokens... approximately 80% cheaper than OpenAI's GPT-4o Realtime"*; adwaitx.com menciona respuestas *"in under 700 milliseconds"*. Trátalos como estimaciones no verificadas.
- **Limitaciones operativas** (reportadas por builder externo, no confirmadas en docs primarias): no hay métricas CloudWatch, ni model invocation logging, ni application inference profiles para `InvokeModelWithBidirectionalStream`.

### 4. PII / Guardrails en voz
- **Sensitive information filters**: PII entities predefinidas (NAME, EMAIL, PHONE, ADDRESS, US_SOCIAL_SECURITY_NUMBER, CREDIT_DEBIT_CARD_NUMBER, AWS_ACCESS_KEY, PASSWORD… 50+ tipos) + regex custom (`regexesConfig`). Acciones: BLOCK, ANONYMIZE (reemplaza con tags tipo `{EMAIL}`) o NONE. Configurable por dirección (`inputAction`/`outputAction`).
- **Limitación clave** (docs AWS): *"This filter supports only text output and will not detect PII information when models respond with tool_use output parameters."* El masking aplica solo a input prompts y model responses de inferencia; NO a los model invocation logs (que guardan el request original sin modificar). Guardrails NO evalúa reasoning content blocks.
- **Nova Sonic + Guardrails**: los guardrails de Bedrock son de texto, así que no filtran el audio en tiempo real. Para redactar PII en conversaciones de voz, aplica **`ApplyGuardrail`** (standalone, permiso `bedrock:ApplyGuardrail`) sobre las transcripciones `textOutput`/ASR en tu propio pipeline. `ApplyGuardrail` evalúa texto arbitrario sin invocar el FM.
- **Converse + guardrails**: `guardrailConfig` en converse/converse_stream aplica a input y output; usa bloques `guardContent` para evaluar selectivamente.

## Details

### Matriz de recomendación Converse vs invoke_model

| Feature (Claude, 2026) | Converse | invoke_model (nativo) | Recomendación |
|---|---|---|---|
| Tool use / function calling | ✅ `toolConfig`/`toolChoice` | ✅ tools nativos | **Converse** |
| Structured output (JSON schema) | ✅ `outputConfig.textFormat` + strict tool | ✅ `output_config.format` | **Converse** |
| Streaming | ✅ ConverseStream | ✅ InvokeModelWithResponseStream | **Converse** |
| Extended thinking / `reasoningContent` | ✅ (additionalModelRequestFields + reasoningContent) | ✅ thinking blocks | **Converse** (cuidar signature) |
| Adaptive thinking / effort (Opus 4.6+) | ✅ additionalModelRequestFields | ✅ | **Converse** |
| Prompt caching | ✅ `cachePoint` | ✅ `cache_control` | **Converse** |
| Guardrails | ✅ `guardrailConfig` | ✅ `guardrailIdentifier` | **Converse** |
| Citations + structured outputs | ❌ incompatibles (400 error) | ❌ incompatibles | Elige uno; si necesitas citations, no uses structured output |
| Citations + guardrails en stream | ⚠️ bug (internalServerException) | ✅ | invoke_model si hay conflicto |
| Modelos sin ARN-versioned ID (Opus 4.8, Fable 5) | ❌ | ✅ InvokeModel | **invoke_model / Messages API** |
| Claude Sonnet 5 | ❌ (legacy) | ❌ (legacy) | "Claude in Amazon Bedrock" Messages API |
| Multi-proveedor uniforme | ✅ | ❌ | **Converse** |

> **Nota sobre citations**: según los docs de Bedrock, *"Structured outputs is incompatible with citations for Anthropic models. If you enable citations while using structured outputs, the model will return a 400 error."* No combines ambos.

**Veredicto**: Converse como ruta primaria en ai-parrot; invoke_model (payload Anthropic nativo) como fallback para (a) modelos sin ARN-versioned ID, (b) features Anthropic de vanguardia aún no en Converse, (c) workarounds ante bugs puntuales de ConverseStream.

### Arquitectura propuesta para ai-parrot

ai-parrot ya es async-first (aiohttp/navigator-api), monorepo uv, con clientes que implementan `AbstractClient` como async context managers (`GoogleGenAIClient`, `OpenAIClient`, `AnthropicClient`) y un `@tool`/`AbstractToolkit` que autogenera schemas desde docstrings y type hints. El `BedrockClient` debe:
1. Implementar `AbstractClient` con `__aenter__/__aexit__` que abren/cierran un `aioboto3.Session().client("bedrock-runtime")`.
2. Exponer `converse()` y `converse_stream()` async; un `invoke_native()` de fallback.
3. Reutilizar el tool schema de ai-parrot mapeándolo a `toolConfig.toolSpec` (name/description/inputSchema.json).
4. Manejar `reasoningContent` (preservar signature en el loop de tools).
5. Un `NovaSonicClient` separado (en `ai-parrot-integrations[voice]`) usando el SDK experimental, gated a Python ≥3.12 con lazy import (coherente con la guía del repo de usar lazy imports para dependencias pesadas).

#### Código: BedrockClient async con aioboto3 (converse + converse_stream + tools + thinking + caching)

```python
import asyncio
import json
from contextlib import AsyncExitStack
import aioboto3
from botocore.config import Config

class BedrockClient:
    """Cliente Bedrock async-first para Claude (Converse API)."""

    def __init__(self, region="us-east-1",
                 model_id="us.anthropic.claude-sonnet-4-5-20250929-v1:0",
                 profile=None, max_retries=4, read_timeout=120):
        self.region = region
        self.model_id = model_id
        self._session = aioboto3.Session(profile_name=profile, region_name=region)
        self._cfg = Config(
            retries={"max_attempts": max_retries, "mode": "adaptive"},
            read_timeout=read_timeout, connect_timeout=10,
        )
        self._stack = AsyncExitStack()
        self.client = None

    async def __aenter__(self):
        self.client = await self._stack.enter_async_context(
            self._session.client("bedrock-runtime", config=self._cfg)
        )
        return self

    async def __aexit__(self, *exc):
        await self._stack.aclose()

    def _tool_config(self, tools):
        # tools: lista de dicts de ai-parrot (name, description, json_schema)
        specs = [{"toolSpec": {"name": t["name"], "description": t["description"],
                               "inputSchema": {"json": t["json_schema"]}}} for t in tools]
        specs.append({"cachePoint": {"type": "default"}})  # cache de tool defs
        return {"tools": specs, "toolChoice": {"auto": {}}}

    async def converse(self, messages, system=None, tools=None, thinking=None,
                       max_tokens=2048, temperature=0.7, guardrail=None, output_schema=None):
        kwargs = {
            "modelId": self.model_id,
            "messages": messages,
            "inferenceConfig": {"maxTokens": max_tokens, "temperature": temperature},
        }
        if system:
            kwargs["system"] = [{"text": system}, {"cachePoint": {"type": "default"}}]
        if tools:
            kwargs["toolConfig"] = self._tool_config(tools)
        if thinking:  # {"type":"enabled","budget_tokens":2048} o {"type":"adaptive"}
            kwargs["additionalModelRequestFields"] = {"thinking": thinking}
            kwargs["inferenceConfig"]["temperature"] = 1.0  # requerido con thinking
        if output_schema:  # structured output (GA feb 2026); requiere name + additionalProperties:false
            kwargs["outputConfig"] = {"textFormat": {"type": "json_schema",
                                                     "structure": output_schema}}
        if guardrail:
            kwargs["guardrailConfig"] = {"guardrailIdentifier": guardrail["id"],
                                         "guardrailVersion": guardrail["version"],
                                         "trace": "enabled"}
        return await self.client.converse(**kwargs)

    async def converse_stream(self, messages, **kw):
        kwargs = {"modelId": self.model_id, "messages": messages,
                  "inferenceConfig": {"maxTokens": kw.get("max_tokens", 2048)}}
        if kw.get("system"):
            kwargs["system"] = [{"text": kw["system"]}]
        if kw.get("tools"):
            kwargs["toolConfig"] = self._tool_config(kw["tools"])
        resp = await self.client.converse_stream(**kwargs)
        async for event in resp["stream"]:
            yield event  # messageStart / contentBlockDelta / messageStop / metadata

    async def run_tool_loop(self, messages, tools, tool_impls, system=None, thinking=None):
        """Loop de tool use preservando reasoningContent.signature."""
        while True:
            resp = await self.converse(messages, system=system, tools=tools, thinking=thinking)
            out_msg = resp["output"]["message"]
            messages.append(out_msg)  # incluye reasoningContent + toolUse SIN modificar
            if resp["stopReason"] != "tool_use":
                return resp
            tool_results = []
            for block in out_msg["content"]:
                if "toolUse" in block:
                    tu = block["toolUse"]
                    result = await tool_impls[tu["name"]](**tu["input"])
                    tool_results.append({"toolResult": {
                        "toolUseId": tu["toolUseId"],
                        "content": [{"json": result}]}})
            messages.append({"role": "user", "content": tool_results})
```

#### Código: fallback invoke_model (payload Anthropic nativo)

```python
    async def invoke_native(self, messages, system=None, max_tokens=2048,
                            thinking=None, tools=None,
                            anthropic_version="bedrock-2023-05-31"):
        body = {"anthropic_version": anthropic_version, "max_tokens": max_tokens,
                "messages": messages}
        if system:
            body["system"] = [{"type": "text", "text": system,
                               "cache_control": {"type": "ephemeral"}}]
        if thinking:
            body["thinking"] = thinking
        if tools:
            body["tools"] = tools  # formato nativo Anthropic
        resp = await self.client.invoke_model(
            modelId=self.model_id, body=json.dumps(body),
            contentType="application/json", accept="application/json")
        payload = await resp["body"].read()
        return json.loads(payload)

    async def invoke_native_stream(self, messages, **kw):
        body = {"anthropic_version": "bedrock-2023-05-31",
                "max_tokens": kw.get("max_tokens", 2048), "messages": messages}
        resp = await self.client.invoke_model_with_response_stream(
            modelId=self.model_id, body=json.dumps(body))
        async for event in resp["body"]:
            chunk = json.loads(event["chunk"]["bytes"])
            yield chunk  # content_block_delta, message_delta, etc.
```

#### Código: Nova Sonic bidireccional (SDK experimental) — NO producción

```python
# Requiere Python >=3.12 y: pip install aws_sdk_bedrock_runtime smithy-aws-core
# ADVERTENCIA: Pre-Alpha (v0.7.0), breaking changes entre minors.
# Pin estricto: aws_sdk_bedrock_runtime==0.7.0
import asyncio, json, base64, uuid
from aws_sdk_bedrock_runtime.client import (
    BedrockRuntimeClient, InvokeModelWithBidirectionalStreamOperationInput)
from aws_sdk_bedrock_runtime.models import (
    InvokeModelWithBidirectionalStreamInputChunk, BidirectionalInputPayloadPart)
from aws_sdk_bedrock_runtime.config import Config, HTTPAuthSchemeResolver, SigV4AuthScheme
from smithy_aws_core.identity import EnvironmentCredentialsResolver

class NovaSonicClient:
    def __init__(self, region="us-east-1", model_id="amazon.nova-2-sonic-v1:0",
                 voice="matthew"):
        self.region, self.model_id, self.voice = region, model_id, voice
        self.prompt_name = str(uuid.uuid4())
        self.audio_out = asyncio.Queue()

    def _init_client(self):
        cfg = Config(
            endpoint_uri=f"https://bedrock-runtime.{self.region}.amazonaws.com",
            region=self.region,
            aws_credentials_identity_resolver=EnvironmentCredentialsResolver(),
            # OJO: la doc Nova 2 usa auth_scheme_resolver / auth_schemes /
            # SigV4AuthScheme(service="bedrock"); la doc v1 usa http_auth_scheme_resolver /
            # http_auth_schemes / SigV4AuthScheme(). Verifica contra la versión instalada.
            http_auth_scheme_resolver=HTTPAuthSchemeResolver(),
            http_auth_schemes={"aws.auth#sigv4": SigV4AuthScheme()})
        self.client = BedrockRuntimeClient(config=cfg)

    async def _send(self, event: dict):
        chunk = InvokeModelWithBidirectionalStreamInputChunk(
            value=BidirectionalInputPayloadPart(bytes_=json.dumps(event).encode()))
        await self.stream.input_stream.send(chunk)

    async def start(self, system_prompt, tools=None):
        self._init_client()
        self.stream = await self.client.invoke_model_with_bidirectional_stream(
            InvokeModelWithBidirectionalStreamOperationInput(model_id=self.model_id))
        await self._send({"event": {"sessionStart": {"inferenceConfiguration":
            {"maxTokens": 1024, "topP": 0.9, "temperature": 0.7},

…(truncated)…
