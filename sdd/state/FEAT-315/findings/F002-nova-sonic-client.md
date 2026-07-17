# F002 — NovaSonicClient: voice-first client with text fallback by delegation

**Query**: Q003 · **Type**: read · `packages/ai-parrot/src/parrot/clients/nova_sonic.py` (519 lines, FEAT-302/TASK-1748)

- `class NovaSonicClient(AbstractClient)`; `client_type/client_name = "nova-sonic"`,
  `_default_model = "amazon.nova-2-sonic-v1:0"` (lines 42-59).
- Voice: `stream_voice()` (lines 216-443) implements bidirectional speech-to-speech
  over `InvokeModelWithBidirectionalStream` using the **Pre-Alpha
  `aws_sdk_bedrock_runtime==0.7.0` SDK (Python ≥ 3.12 only)** — boto3/aioboto3 do
  not support this operation. Eager ImportError at `__init__` (lines 111-119).
- Thin SDK wrappers isolate the Pre-Alpha API: `_open_stream` / `_send_event` /
  `_iter_events` (lines 174-197), mirroring BedrockConverseClient's
  `_sdk_create`/`_sdk_stream` pattern.
- Sender/receiver task architecture copied from `GeminiLiveClient.stream_voice`
  (`parrot/clients/live.py`); yields the same `LiveVoiceResponse` shape so
  `VoiceChatHandler` works unchanged. 8-minute connection limit handled via
  `reconnect_required` signal frame (lines 61-63, 313-328).
- Event protocol frames: sessionStart → promptStart (audio/text output config,
  voice_id, base64 encoding) → contentStart/textInput/contentEnd (SYSTEM) →
  contentStart AUDIO → audioInput chunks (base64) → toolUse/toolResult → completionEnd.
- **Text fallback**: `ask()` / `ask_stream()` / `invoke()` (lines 487-507) delegate to a
  lazily-built internal `BedrockConverseClient` (`_get_text_client`, lines 150-167)
  sharing region/profile/guardrail config. `resume()` raises NotImplementedError.
- Credentials: only `region` + `profile` handled locally; **no `aws_id` /
  `AWS_CREDENTIALS` support** — credential resolution is inherited indirectly via
  the internal BedrockConverseClient for text only; the voice SDK client is built
  as `BedrockAgentRuntimeClient(region=...)` with no explicit credentials (line 142-143).

## Citations
- packages/ai-parrot/src/parrot/clients/nova_sonic.py:42-197,216-519
