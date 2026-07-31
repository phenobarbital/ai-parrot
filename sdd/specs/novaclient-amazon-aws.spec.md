---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Feature Specification: Unified NovaClient for all Amazon Nova models

**Feature ID**: FEAT-315
**Date**: 2026-07-17
**Author**: Jesus (jlara@trocglobal.com)
**Status**: approved
**Target version**: next minor
**Proposal**: `sdd/proposals/novaclient-amazon-aws.proposal.md` (research audit: `sdd/state/FEAT-315/`)

---

## 1. Motivation & Business Requirements

### Problem Statement

`NovaSonicClient` (`packages/ai-parrot/src/parrot/clients/nova_sonic.py`,
FEAT-302) is a voice-only client: its `ask()`/`ask_stream()`/`invoke()` are
thin fallbacks that delegate to an internally-managed `BedrockConverseClient`.
Covering the full Amazon Nova family (text: Nova 2 Lite, Micro, Pro, Premier;
voice: Nova Sonic / Nova 2 Sonic; image: Nova Canvas; video: Nova Reel) with
that design would require multiple separate clients. The Google client already
solved this problem with a single multimodal client
(`GoogleGenAIClient(AbstractClient, GoogleGeneration, GoogleAnalysis)`);
Nova should mirror that architecture so one `NovaClient` serves all modes.

Additionally, the in-flight `aws_id` credential resolution added to
`BedrockConverseClient` (commit `3672eb2f4`) has a latent bug: it reads
`access_key`/`secret_key`/`region` from `AWS_CREDENTIALS` profiles whose
actual keys are `aws_key`/`aws_secret`/`region_name`, and leaves credential
attributes unbound when the profile is missing.

### Goals

- One `NovaClient` (subpackage `parrot/clients/nova/`) covering all Nova
  modalities, mirroring the Google client layout:
  - `nova/client.py` — `ask()` / `ask_stream()` / `invoke()` for the Nova
    text models (Nova 2 Lite, Micro, Pro, Premier) over the Bedrock Converse API.
  - `nova/audio.py` — bidirectional voice streaming (`stream_voice()`) via
    `InvokeModelWithBidirectionalStream` (Nova Sonic / Nova 2 Sonic).
  - `nova/generation.py` — `generate_image()` (Nova Canvas) and
    `video_generation()` (Nova Reel), minimal parity with `GoogleGeneration`
    method names.
- Credential resolution: explicit kwargs → `aws_id` profile in
  `parrot.conf::AWS_CREDENTIALS` (correct keys, `'default'` fallback) → env
  (`AWS_ACCESS_KEY`/`AWS_SECRET_KEY`) → SDK chain, same UX as the Bedrock client.
- Fix the `AWS_CREDENTIALS` key-mismatch / unbound-attribute bug in
  `BedrockConverseClient.__init__` as part of the shared refactor.
- Register provider key `'nova'` in `LLMFactory` (default model `nova-2-lite`).
- Migrate ALL `nova_sonic` call sites now (core, `ai-parrot-integrations`,
  tests) and delete `parrot/clients/nova_sonic.py` — no compatibility shim
  (resolved in proposal Q&A).

### Non-Goals (explicitly out of scope)

- `AnthropicClient`'s Bedrock backend (`'bedrock'` / `'anthropic-aws'` factory
  keys, FEAT-232) — untouched.
- Any change to `GoogleGenAIClient` and its mixins — reference only.
- Batch generation, reel assembly, music/speech-synthesis parity with
  `GoogleGeneration` (resolved U4: minimal parity; extras deferred).
- Redesign of the `parrot.conf::AWS_CREDENTIALS` schema — consumed as-is.
- A `nova_sonic` deprecation shim (rejected in proposal Q&A — full migration
  instead; see `sdd/proposals/novaclient-amazon-aws.proposal.md` §5).
- Embeddings (Nova Multimodal Embeddings) — separate concern
  (`parrot/embeddings/` lives partly in the satellite package, FEAT-201).

---

## 2. Architectural Design

### Overview

Mirror the Google subpackage pattern. The Converse text engine is **extracted
inside `bedrock.py`** (resolved at spec time: base stays in `bedrock.py`, no
new module): `bedrock.py` is refactored into a `BedrockConverseBase` class
carrying the engine (session/client management, `_sdk_create`/`_sdk_stream`,
message/tool conversion, tool-use loop, streaming, guardrails, structured
output, `_invoke_native`, credential resolution) plus a thin
`BedrockConverseClient(BedrockConverseBase)` that keeps today's public surface
byte-compatible for non-Nova Bedrock families (Claude, Llama, Mistral, ...).

```python
# parrot/clients/nova/client.py (composition — mirrors GoogleGenAIClient)
class NovaClient(BedrockConverseBase, NovaAudio, NovaGeneration):
    client_type: str = "nova"
    client_name: str = "nova"
    _default_model: str = "nova-2-lite"   # translated via bedrock_models.translate()
```

Key behaviors:

- **Text** (`ask`/`ask_stream`/`invoke`/`resume`): inherited from
  `BedrockConverseBase` — no delegation object, no reimplementation.
- **Voice** (`stream_voice`): `NovaAudio` mixin, ported from
  `nova_sonic.py` with the wire protocol, sender/receiver task architecture,
  base64 audio encoding, `LiveVoiceResponse` yield shape, tool-use handling,
  and the 8-minute `reconnect_required` convention all preserved. The
  Pre-Alpha `aws_sdk_bedrock_runtime` import guard moves from `__init__` to
  first voice use (`stream_voice`) so that text/generation-only usage of
  NovaClient does NOT require the experimental SDK or Python ≥ 3.12.
- **Generation**: `NovaGeneration` mixin using `aioboto3` (same client as the
  text engine):
  - `generate_image()` → `invoke_model` with `taskType: "TEXT_IMAGE"`
    payload (Nova Canvas, synchronous, base64 images out).
  - `video_generation()` → `start_async_invoke` + `get_async_invoke` polling
    (Nova Reel has NO synchronous API), with a **mandatory S3 output bucket**
    (`s3OutputDataConfig.s3Uri`) resolved from: explicit kwarg →
    `AWS_CREDENTIALS[aws_id]["bucket_name"]`; the finished MP4 is downloaded
    to `output_directory`.
- **Credentials** (`aws_id`): resolution logic lives in `BedrockConverseBase`
  and uses the CORRECT profile keys (`aws_key`/`aws_secret`/`region_name`,
  matching `interfaces/aws.py:53-64`), falls back to the `'default'` profile,
  and never leaves `_aws_access_key`/`_aws_secret_key`/`_aws_session_token`/
  `_region` unbound.
- **Region prefix**: Nova 2 Lite and Nova Premier have NO in-region model
  access — they require geo/global inference-profile IDs (`us.`/`eu.`/`jp.`/
  `global.` prefix; verified against AWS model cards 2026-07). `NovaClient`
  defaults `region_prefix="us"` (overridable) so the default model resolves
  to `us.amazon.nova-2-lite-v1:0` out of the box.
- **Voice provider key**: renamed `'nova_sonic'` → `'nova'`
  (`VoiceProvider.NOVA = "nova"`); **intentional breaking change** for
  deployed voice configs (resolved at spec time; no alias kept).

### Component Diagram

```
LLMFactory("nova:<model>")                bots/voice.py (provider="nova")
        │                                          │
        ▼                                          ▼
   parrot/clients/nova/__init__.py  ──exports──  NovaClient
        │
        ▼
NovaClient(BedrockConverseBase, NovaAudio, NovaGeneration)
   │             │                  │
   │             │                  ├─ generate_image()  ─→ invoke_model (Canvas)
   │             │                  └─ video_generation() ─→ start_async_invoke/
   │             │                                            get_async_invoke (Reel) → S3 → local file
   │             └─ stream_voice() ─→ aws_sdk_bedrock_runtime (Pre-Alpha)
   │                                   InvokeModelWithBidirectionalStream (Sonic)
   └─ ask()/ask_stream()/invoke()/resume() ─→ aioboto3 converse/converse_stream
                    │
                    └─ models/bedrock_models.translate(model, region_prefix)

BedrockConverseClient(BedrockConverseBase)   ← unchanged public surface,
   (Claude/Llama/Mistral/... on Bedrock)       non-Nova families keep working
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AbstractClient` (`clients/base.py`) | extends (via `BedrockConverseBase`) | implements `get_client`, `ask`, `ask_stream`, `resume`, `invoke` |
| `BedrockConverseClient` (`clients/bedrock.py`) | refactored | split into `BedrockConverseBase` + thin subclass; public surface unchanged |
| `LLMFactory` (`clients/factory.py`) | registers | `'nova'` key via lazy loader (pattern: `_lazy_bedrock_converse`, line 21) |
| `bedrock_models.translate` (`models/bedrock_models.py`) | extends map | add `nova-premier`, `nova-canvas`, `nova-reel` |
| `LiveVoiceResponse` et al. (`clients/live.py`) | uses | voice yield shape unchanged (lines 61, 117, 138, 156) |
| `bots/voice.py` | migrates | provider `'nova_sonic'` → `'nova'`, imports `NovaClient` |
| `ai-parrot-integrations` `voice/{models,handler}.py` | migrates | `VoiceProvider.NOVA = "nova"`; handler imports `parrot.clients.nova` |
| `parrot.conf::AWS_CREDENTIALS` | consumes | `aws_id` profile lookup with corrected keys |
| `parrot/tools/manager.ToolFormat` | uses | tool conversion already handled by the Converse engine |

### Data Models

No new Pydantic models required. Reused (all verified):

```python
from parrot.models.responses import AIMessage, AIMessageFactory, InvokeResult  # bedrock.py:40
from parrot.models.outputs import StructuredOutputConfig                        # bedrock.py:41
from parrot.models.basic import CompletionUsage, ToolCall                       # bedrock.py:39
from parrot.clients.live import (                                               # nova_sonic.py:36
    LiveCompletionUsage, LiveToolCall, LiveVoiceResponse, VoiceTurnMetadata,
)
# Generation prompts (same models GoogleGeneration consumes — google/generation.py imports):
from parrot.models import ImageGenerationPrompt, VideoGenerationPrompt
```

### New Public Interfaces

```python
# parrot/clients/nova/client.py
class NovaClient(BedrockConverseBase, NovaAudio, NovaGeneration):
    """Unified client for all Amazon Nova models on Bedrock."""
    def __init__(
        self,
        aws_id: Optional[str] = None,          # AWS_CREDENTIALS profile name
        region: Optional[str] = None,
        profile: Optional[str] = None,          # named AWS profile (boto3)
        region_prefix: Optional[str] = "us",   # Nova 2 Lite/Premier need inference profiles
        guardrail_id: Optional[str] = None,
        guardrail_version: Optional[str] = None,
        voice_id: str = "matthew",
        aws_access_key: Optional[str] = None,
        aws_secret_key: Optional[str] = None,
        aws_session_token: Optional[str] = None,
        **kwargs,
    ): ...

# parrot/clients/nova/audio.py  (mixin — signature preserved from nova_sonic.py:216)
class NovaAudio:
    async def stream_voice(
        self, audio_iterator: AsyncIterator[bytes],
        system_prompt: Optional[str] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None, **kwargs,
    ) -> AsyncIterator[LiveVoiceResponse]: ...

# parrot/clients/nova/generation.py  (mixin — names mirror GoogleGeneration)
class NovaGeneration:
    async def generate_image(
        self, prompt: str, *, model: Optional[str] = None,   # default nova-canvas
        negative_prompt: Optional[str] = None,
        number_of_images: int = 1, width: int = 1024, height: int = 1024,
        seed: Optional[int] = None, output_directory: Optional[Path] = None,
        as_base64: bool = False, **kwargs,
    ) -> AIMessage: ...
    async def video_generation(
        self, prompt: str, *, model: Optional[str] = None,   # default nova-reel
        reference_image: Optional[Union[str, Path]] = None,
        duration: int = 6, output_directory: Optional[Path] = None,
        s3_output_uri: Optional[str] = None,   # fallback: AWS_CREDENTIALS[aws_id]["bucket_name"]
        poll_interval: float = 10.0, timeout: float = 900.0, **kwargs,
    ) -> AIMessage: ...

# parrot/clients/nova/__init__.py  (mirrors google/__init__.py:1-6)
from .client import NovaClient
__all__ = ["NovaClient"]
```

---

## 3. Module Breakdown

### Module 1: BedrockConverseBase extraction + credential fix
- **Path**: `packages/ai-parrot/src/parrot/clients/bedrock.py`
- **Responsibility**: Split `BedrockConverseClient` into `BedrockConverseBase`
  (engine: init/credentials, `get_client`, `_translate_model`, `_sdk_create`,
  `_sdk_stream`, message/tool conversion, `ask`, `ask_stream`, `resume`,
  `invoke`, guardrails, `_invoke_native`) and a thin
  `BedrockConverseClient(BedrockConverseBase)` keeping `client_type`,
  `_default_model`, `_fallback_model` and ALL current public behavior.
  Fix the `aws_id` branch: read `aws_key`/`aws_secret`/`region_name`
  (+ tolerate `aws_access_key_id`/`aws_secret_access_key` like
  `interfaces/aws.py:53-54`), fall back to the `'default'` profile when the
  named profile is missing, and always bind the credential attributes.
- **Depends on**: — (first module)

### Module 2: NovaClient core (`nova/client.py` + `nova/__init__.py`)
- **Path**: `packages/ai-parrot/src/parrot/clients/nova/{__init__,client}.py`
- **Responsibility**: `NovaClient(BedrockConverseBase, NovaAudio, NovaGeneration)`
  with `client_type="nova"`, `_default_model="nova-2-lite"`,
  `region_prefix` defaulting to `"us"`, `voice_id` kwarg. Inherits all text
  methods; no delegation object. Subpackage `__init__` exports `NovaClient`.
- **Depends on**: Module 1, Module 3, Module 4

### Module 3: NovaAudio mixin (`nova/audio.py`)
- **Path**: `packages/ai-parrot/src/parrot/clients/nova/audio.py`
- **Responsibility**: Port `stream_voice`, `_audio_sender`, `_open_stream`,
  `_send_event`, `_iter_events`, `_apply_pii_guardrail` (now calls
  `self.apply_guardrail_text` directly — no `_get_text_client`) from
  `nova_sonic.py` verbatim in behavior. Lazy Pre-Alpha SDK guard at first
  voice use (actionable ImportError naming `aws_sdk_bedrock_runtime==0.7.0`,
  Python ≥ 3.12).
- **Depends on**: Module 1 (guardrail method on the base)

### Module 4: NovaGeneration mixin (`nova/generation.py`)
- **Path**: `packages/ai-parrot/src/parrot/clients/nova/generation.py`
- **Responsibility**: `generate_image()` (Canvas `invoke_model`,
  `taskType: TEXT_IMAGE`, decode base64 images, optional save to
  `output_directory`); `video_generation()` (Reel `start_async_invoke` →
  `get_async_invoke` polling → download MP4 from S3 to `output_directory`).
  S3 URI resolution: kwarg → `AWS_CREDENTIALS[aws_id]["bucket_name"]` →
  raise actionable `ValueError`.
- **Depends on**: Module 1 (client/session plumbing)

### Module 5: Model catalog + factory registration
- **Paths**: `packages/ai-parrot/src/parrot/models/bedrock_models.py`,
  `packages/ai-parrot/src/parrot/clients/factory.py`
- **Responsibility**: Add map entries `nova-premier → amazon.nova-premier-v1:0`,
  `nova-canvas → amazon.nova-canvas-v1:0`, `nova-reel → amazon.nova-reel-v1:0`
  (IDs verified against AWS model cards 2026-07). Add `_lazy_nova()` loader
  and `"nova"` key to `SUPPORTED_CLIENTS`.
- **Depends on**: Module 2

### Module 6: Call-site migration + delete nova_sonic.py
- **Paths**: `packages/ai-parrot/src/parrot/bots/voice.py`,
  `packages/ai-parrot/src/parrot/models/voice.py`,
  `packages/ai-parrot-integrations/src/parrot/voice/{models,handler}.py`,
  delete `packages/ai-parrot/src/parrot/clients/nova_sonic.py`
- **Responsibility**: Rename provider key `'nova_sonic'` → `'nova'`
  (`VoiceProvider.NOVA = "nova"`), point all imports at
  `parrot.clients.nova.NovaClient`, delete the old module. Breaking change —
  documented in changelog/migration note.
- **Depends on**: Modules 2–5

### Module 7: Test migration + new coverage
- **Paths**: `packages/ai-parrot/tests/clients/test_nova.py` (from
  `test_nova_sonic.py`), `packages/ai-parrot/tests/bots/test_voicebot_nova_wiring.py`
  (from `..._nova_sonic_wiring.py`), `packages/ai-parrot/tests/models/test_voice_config.py`,
  `packages/ai-parrot/tests/models/test_bedrock_models.py`,
  `packages/ai-parrot-integrations/tests/voice/test_nova_provider.py`
- **Responsibility**: Migrate existing suites to the new paths/keys; add
  unit tests per §4. Full bedrock suite must stay green (base extraction is
  behavior-preserving).
- **Depends on**: Module 6

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_converse_base_public_surface_unchanged` | 1 | `BedrockConverseClient` attrs/methods identical pre/post split (existing `test_bedrock_*.py` green) |
| `test_aws_id_resolves_correct_keys` | 1 | `aws_id='monitoring'` reads `aws_key`/`aws_secret`/`region_name` |
| `test_aws_id_missing_falls_back_to_default` | 1 | unknown `aws_id` → `'default'` profile, attributes always bound |
| `test_nova_client_mro_and_defaults` | 2 | `client_type=='nova'`, default model translates to `us.amazon.nova-2-lite-v1:0` |
| `test_nova_ask_inherited_not_delegated` | 2 | no internal second client object; `ask()` runs the inherited engine (mocked `_sdk_create`) |
| `test_stream_voice_event_protocol` | 3 | sessionStart/promptStart/contentStart frames + base64 audio (port of existing test_nova_sonic tests) |
| `test_stream_voice_lazy_sdk_guard` | 3 | missing `aws_sdk_bedrock_runtime` → ImportError at `stream_voice`, NOT at `__init__` |
| `test_generate_image_payload_and_decode` | 4 | Canvas `TEXT_IMAGE` payload; base64 → bytes; saves to output_directory (mocked invoke_model) |
| `test_video_generation_polls_and_downloads` | 4 | Reel start/poll/complete flow; S3 URI from kwarg or profile `bucket_name`; ValueError when absent |
| `test_translate_new_nova_ids` | 5 | `nova-premier`/`nova-canvas`/`nova-reel` map entries (+ region_prefix behavior) |
| `test_factory_nova_key` | 5 | `LLMFactory.create('nova:nova-micro')` returns NovaClient with model set |
| `test_voice_provider_renamed` | 6 | `VoiceProvider.NOVA == "nova"`; `'nova_sonic'` no longer accepted |
| `test_no_nova_sonic_module` | 6 | `import parrot.clients.nova_sonic` raises ImportError |

### Integration Tests

| Test | Description |
|---|---|
| `test_voicebot_nova_wiring` | `bots/voice.py` provider `'nova'` builds a NovaClient with voice params (port of existing wiring test) |
| `test_bedrock_suite_regression` | full existing `tests/clients/test_bedrock_*.py` pass unmodified |
| `test_nova_ask_live` (marked `@pytest.mark.integration`, skipped in CI) | real `ask()` against `us.amazon.nova-2-lite-v1:0` |

### Test Data / Fixtures

```python
@pytest.fixture
def aws_credentials_profiles(monkeypatch):
    """Patch parrot.conf.AWS_CREDENTIALS with default + named test profiles."""
    ...

@pytest.fixture
def fake_bidi_stream():
    """Stub bidirectional stream: input_stream.send() recorder + scripted output events
    (reuse the existing stub from tests/clients/test_nova_sonic.py)."""
    ...
```

---

## 5. Acceptance Criteria

- [ ] `parrot/clients/nova/` exists with `client.py`, `audio.py`,
      `generation.py`, `__init__.py`; `from parrot.clients.nova import NovaClient` works.
- [ ] `NovaClient.ask/ask_stream/invoke/resume` are inherited from
      `BedrockConverseBase` — no internal delegate client object exists.
- [ ] `LLMFactory.create("nova")` returns a NovaClient defaulting to
      `nova-2-lite` with `region_prefix="us"` (resolves
      `us.amazon.nova-2-lite-v1:0`).
- [ ] `NovaClient(aws_id=...)` resolves credentials from
      `AWS_CREDENTIALS[aws_id]` using keys `aws_key`/`aws_secret`/`region_name`,
      falling back to the `'default'` profile; explicit kwargs and env vars
      still work; `BedrockConverseClient` gets the same fix.
- [ ] `stream_voice()` yields `LiveVoiceResponse` objects with the same event
      protocol, base64 audio handling, tool-use loop, and 8-minute
      `reconnect_required` behavior as `nova_sonic.py` today (ported tests pass).
- [ ] Text/generation use of NovaClient does NOT require
      `aws_sdk_bedrock_runtime` — the Pre-Alpha SDK guard fires only at
      `stream_voice()`.
- [ ] `generate_image()` produces images via Canvas `invoke_model`
      (`taskType: TEXT_IMAGE`); `video_generation()` runs the Reel
      `start_async_invoke`/`get_async_invoke` cycle and downloads the MP4;
      missing S3 output config raises an actionable error.
- [ ] `PUBLIC_TO_BEDROCK` contains `nova-premier`, `nova-canvas`, `nova-reel`.
- [ ] Provider key `'nova'` works end-to-end in `bots/voice.py` and the
      integrations voice package; `'nova_sonic'` is fully removed
      (intentional breaking change, documented in a migration note).
- [ ] `parrot/clients/nova_sonic.py` is deleted; no references remain
      (`grep -r nova_sonic packages/` → only historical docs/specs).
- [ ] Existing Bedrock suite passes unmodified
      (`pytest packages/ai-parrot/tests/clients/test_bedrock_*.py -v`).
- [ ] All new/migrated tests pass (`pytest packages/ai-parrot/tests/ packages/ai-parrot-integrations/tests/ -v`).

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor.** Verified 2026-07-17 on `dev`
> (post-`3672eb2f4`). The repo is a **monorepo**: all core paths below are
> under `packages/ai-parrot/src/`. Top-level `parrot/clients/` contains only
> stale `__pycache__` — never edit there.

### Verified Imports

```python
from parrot.clients.base import AbstractClient            # clients/base.py:244
from parrot.clients.bedrock import BedrockConverseClient  # clients/bedrock.py:45
from parrot.clients.live import (                         # clients/live.py:61,117,138,156
    LiveCompletionUsage, LiveToolCall, LiveVoiceResponse, VoiceTurnMetadata,
)
from parrot.conf import (                                 # conf.py
    AWS_CREDENTIALS,        # conf.py:490 (dict of profiles)
    AWS_ACCESS_KEY, AWS_SECRET_KEY, AWS_SESSION_TOKEN,
    AWS_REGION_NAME, BEDROCK_AWS_REGION,                  # conf.py:480 (fallback=None)
)
from parrot.models.bedrock_models import translate        # models/bedrock_models.py:100
from parrot.models.responses import AIMessage, AIMessageFactory, InvokeResult
from parrot.models.outputs import StructuredOutputConfig
from parrot.models.basic import CompletionUsage, ToolCall
from parrot.tools.manager import ToolFormat               # used by bedrock.py:42
from parrot.models import ImageGenerationPrompt, VideoGenerationPrompt  # as imported by google/generation.py
```

### Existing Class Signatures

```python
# clients/base.py — AbstractClient(EventEmitterMixin, ABC), line 244
@abstractmethod
async def get_client(self) -> Any: ...                    # line 845-846
@abstractmethod
async def ask(self, prompt: str, model: str, max_tokens: int = 4096,
    temperature: float = 0.7, files=None, system_prompt=None,
    structured_output=None, user_id=None, session_id=None, tools=None,
    use_tools=None, deep_research=False, background=False,
    lazy_loading=False) -> MessageResponse: ...           # line 1525-1542
@abstractmethod
async def ask_stream(...) -> AsyncIterator: ...           # line 1563
@abstractmethod
async def resume(self, session_id: str, user_input: str,
    state: Dict[str, Any]) -> MessageResponse: ...        # line 1592-1598
@abstractmethod
async def invoke(self, prompt: str, *, output_type=None,
    structured_output=None, model=None, system_prompt=None,
    max_tokens: int = 4096, temperature: float = 0.0,
    use_tools: bool = False, tools=None) -> InvokeResult: ...  # line 1614-1626
# GOTCHA: AbstractClient.__init__ does self._fallback_model = kwargs.get('fallback_model', None)
# — shadows class attributes; bedrock.py:135 works around with kwargs.setdefault.

# clients/bedrock.py — BedrockConverseClient(AbstractClient), line 45
def __init__(self, aws_id=None, region=None, profile=None, region_prefix=None,
    guardrail_id=None, guardrail_version=None, max_retries: int = 4,
    read_timeout: int = 120, aws_access_key=None, aws_secret_key=None,
    aws_session_token=None, **kwargs): ...                # line 64-140
async def get_client(self) -> Any: ...                    # line 143 (lazy aioboto3)
def _translate_model(self, model) -> str: ...             # line 179
async def _sdk_create(self, payload: dict) -> Dict[str, Any]: ...        # line 217
async def _sdk_stream(self, payload: dict) -> AsyncIterator[...]: ...    # line 221
def _prepare_tools(self, filter_names=None) -> List[Dict[str, Any]]: ... # line 330
async def apply_guardrail_text(self, text: str, source: str = "OUTPUT") -> str:  # line 400
async def _invoke_native(self, messages, model, max_tokens, temperature, system_prompt):  # line 439
async def ask(...): ...                                   # line 494
async def ask_stream(...): ...                            # line 780
async def resume(...): ...                                # line 916
async def invoke(...): ...                                # line 1046
# ⚠ BUG (lines 109-120): reads credentials.get("access_key")/("secret_key")/
#   ("session_token")/("region") — AWS_CREDENTIALS uses aws_key/aws_secret/
#   region_name; and the else-branch attrs are unbound when aws_id lookup misses.

# clients/nova_sonic.py — NovaSonicClient(AbstractClient), line 42 (TO BE DELETED)
client_type = client_name = "nova-sonic"; _default_model = "amazon.nova-2-sonic-v1:0"  # 57-59
_CONNECTION_LIMIT_SECONDS = 8*60 - 15                     # line 63
INPUT_SAMPLE_RATE_HZ = 16000; OUTPUT_SAMPLE_RATE_HZ = 24000  # 66-67
async def _open_stream(self, model_id) -> Any: ...        # line 174 (InvokeModelWithBidirectionalStreamOperationInput)
async def _send_event(self, stream, event) -> None: ...   # line 191
def _iter_events(self, stream) -> AsyncIterator: ...      # line 195
async def stream_voice(self, audio_iterator, system_prompt=None,
    session_id=None, user_id=None, **kwargs) -> AsyncIterator[LiveVoiceResponse]:  # line 216
async def _audio_sender(self, stream, audio_iterator, prompt_name, content_name):  # line 445

# conf.py — AWS_CREDENTIALS, lines 490-531: dict with profiles
# 'default'|'monitoring'|'cloudwatch'|'backend'|'security'|'security_bucket';
# each: use_credentials, aws_key, aws_secret, region_name (+optional bucket_name).

# interfaces/aws.py — canonical resolver, lines 52-64:
# AWS_CREDENTIALS.get(aws_id, {}) → fallback 'default' → keys:
# credentials.get('aws_key') or credentials.get('aws_access_key_id'), etc.

# models/bedrock_models.py — PUBLIC_TO_BEDROCK (lines 38-76) currently has:
# nova-sonic, nova-pro, nova-lite, nova-micro, nova-2-sonic, nova-2-lite.
# translate(public_id, region_prefix=None) at line 100; warn+passthrough for unknown.

# clients/factory.py — SUPPORTED_CLIENTS dict (lines 65-94);
# lazy-loader precedent _lazy_bedrock_converse (line 21); LLMFactory.create (line 138).

# clients/google/__init__.py (lines 1-6) — export pattern to mirror:
# from .client import GoogleGenAIClient; GoogleClient = GoogleGenAIClient; __all__.

# bots/voice.py — provider dispatch: 'nova_sonic' at lines 164-177 and 211-225,
# lazily imports parrot.clients.nova_sonic.NovaSonicClient.

# ai-parrot-integrations voice package:
# voice/models.py:34 — VoiceProvider.NOVA_SONIC = "nova_sonic"
# voice/handler.py:77,98,332 — lazy imports of parrot.clients.nova_sonic.
```

### Verified AWS Facts (model cards, docs.aws.amazon.com, fetched 2026-07-17)

| Model | Bedrock ID | Inference access | API |
|---|---|---|---|
| Nova 2 Lite | `amazon.nova-2-lite-v1:0` | **geo/global only**: `us.`/`eu.`/`jp.`/`global.` prefixes; NO in-region | Converse + Invoke (streaming) |
| Nova Premier | `amazon.nova-premier-v1:0` | **geo only**: `us.` prefix; NO in-region; **Legacy, EOL 2026-09-14** | Converse + Invoke |
| Nova Canvas | `amazon.nova-canvas-v1:0` | in-region only (us-east-1, eu-west-1, ap-northeast-1); **EOL 2026-09-30** | Invoke only (`taskType: TEXT_IMAGE`) |
| Nova Reel | `amazon.nova-reel-v1:0` | in-region only (same 3 regions); **EOL 2026-09-30** | **StartAsyncInvoke only** + `GetAsyncInvoke`; requires `outputDataConfig.s3OutputDataConfig.s3Uri` |
| Nova Micro / Lite / Pro | already in map (`amazon.nova-{micro,lite,pro}-v1:0`) | — | Converse + Invoke |
| Nova 2 Sonic | `amazon.nova-2-sonic-v1:0` (already in map) | — | InvokeModelWithBidirectionalStream |

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `BedrockConverseBase` | `AbstractClient.__init__` | `super().__init__(**kwargs)` + `kwargs.setdefault('fallback_model', ...)` | `clients/bedrock.py:135-140` |
| `NovaClient` text path | `BedrockConverseBase.ask/_sdk_create` | inheritance | `clients/bedrock.py:494,217` |
| `NovaAudio._apply_pii_guardrail` | `BedrockConverseBase.apply_guardrail_text` | `self.` call (no delegate) | `clients/bedrock.py:400` |
| `NovaGeneration` | aioboto3 bedrock-runtime client | `self._ensure_client()` (per-loop cache) | `clients/base.py` `_ensure_client` (used at `bedrock.py:186`) |
| `_lazy_nova` | `SUPPORTED_CLIENTS["nova"]` | lazy loader | `clients/factory.py:65-94` |
| `bots/voice.py` | `parrot.clients.nova.NovaClient` | lazy import (replaces lines 174, 224) | `bots/voice.py:164-225` |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot/clients/nova/`~~ — subpackage does not exist yet (created by this feature).
- ~~`NovaClient`~~, ~~`BedrockConverseBase`~~, ~~`NovaAudio`~~, ~~`NovaGeneration`~~,
  ~~`_lazy_nova`~~ — created by this feature.
- ~~`PUBLIC_TO_BEDROCK["nova-premier" | "nova-canvas" | "nova-reel"]`~~ — not in the map yet.
- ~~Nova 2 Pro / Nova 2 Micro / Nova 2 Premier / Nova 2 Omni~~ — **do not exist
  on Bedrock** (July 2026): the Nova 2 generation is Lite + Sonic only. Do not
  invent `nova-2-pro` etc. model IDs.
- ~~`parrot.conf.AWS_ID`~~ — no such config variable (the bedrock.py docstring
  mentions "AWS_ID" but nothing reads it).
- ~~`amazon.nova-reel-v1:1`~~ — the current model card lists `v1:0` only; do not
  hard-code `v1:1`.
- ~~`invoke_model` / `converse` for Nova Reel~~ — Reel supports ONLY
  `start_async_invoke`/`get_async_invoke`.
- ~~top-level `parrot/clients/*.py`~~ — only stale `__pycache__`; real code is
  under `packages/ai-parrot/src/parrot/clients/`.
- ~~`SUPPORTED_CLIENTS["nova-sonic"]`~~ — NovaSonicClient was never
  factory-registered; there is no key to migrate, only one to add.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Capability mixins**: `GoogleGenAIClient(AbstractClient, GoogleGeneration, GoogleAnalysis)`
  (`clients/google/client.py`) — same composition for NovaClient.
- **Lazy SDK guards**: module import must never fail on missing optional deps
  (`google/client.py` header pattern; `aws_sdk_bedrock_runtime` guard moves to
  first `stream_voice()` call).
- **Thin SDK wrappers**: keep `_open_stream`/`_send_event`/`_iter_events`
  (Pre-Alpha isolation, `nova_sonic.py:174-197`) and `_sdk_create`/`_sdk_stream`
  (`bedrock.py:217-221`).
- **Lazy factory loaders**: `_lazy_bedrock_converse` (`factory.py:21-34`).
- **Model translation**: always via `bedrock_models.translate(model, region_prefix)`.
- **Async-first, `self.logger`, Google-style docstrings, type hints** (CLAUDE.md).

### Known Risks / Gotchas

- **`AbstractClient.__init__` attribute shadowing**: it unconditionally sets
  `self._fallback_model = kwargs.get('fallback_model', None)` — the MRO of
  `NovaClient` must preserve the `kwargs.setdefault('fallback_model', ...)`
  workaround (`bedrock.py:121-135`) or the capacity-fallback path silently dies.
- **MRO order matters**: `BedrockConverseBase` must come first so its concrete
  `ask/ask_stream/invoke/resume/get_client` satisfy the ABC; mixins must not
  define competing `__init__`s.
- **Pre-Alpha voice SDK**: `aws_sdk_bedrock_runtime==0.7.0`, Python ≥ 3.12
  only; API may change before GA. Never import it at module scope.
- **Cross-distribution lockstep**: deleting `nova_sonic.py` while
  `ai-parrot-integrations` ships separately — both packages must release
  together (no shim was approved).
- **Breaking config change**: `'nova_sonic'` provider key removed in favor of
  `'nova'` — needs a migration note in the changelog.
- **Nova 1 EOL horizon**: Premier (2026-09-14), Canvas/Reel (2026-09-30) are
  Legacy on Bedrock. Keep the catalog trivially extensible; expect successor
  IDs shortly after this feature lands.
- **Reel requires S3**: `video_generation()` cannot work without an S3 output
  location; the error message must tell the user to pass `s3_output_uri` or
  configure `bucket_name` in their `AWS_CREDENTIALS` profile.
- **Geo-only text models**: with `region_prefix=None` the default model would
  resolve to `amazon.nova-2-lite-v1:0`, which is NOT invokable in-region —
  hence the `"us"` default; document the override for EU/JP deployments.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `aioboto3` | existing dep | Converse API + Canvas invoke + Reel async invoke + S3 download |
| `aws_sdk_bedrock_runtime` | `==0.7.0` (optional extra, Python ≥ 3.12) | Nova Sonic bidirectional voice only |

---

## 8. Open Questions

### Resolved (during proposal + spec Q&A)

- [x] **Text engine strategy** — *Resolved in proposal*: "Migrate
  BedrockConverseClient into new NovaClient, NovaClient will be the unique
  client for multi-modal"; follow-up: **keep both** — shared engine, with
  `BedrockConverseClient` surviving for non-Nova families.
- [x] **Where the shared engine lives** — *Resolved in spec Q&A*: **base stays
  in `bedrock.py`** (`BedrockConverseBase` + thin `BedrockConverseClient`);
  no new module.
- [x] **Back-compat for `nova_sonic`** — *Resolved in proposal*: **migrate
  everything now**; delete `nova_sonic.py`; no shim.
- [x] **Voice provider key** — *Resolved in spec Q&A*: **rename to `'nova'`**
  (`VoiceProvider.NOVA = "nova"`); intentional breaking change; no alias.
- [x] **Factory key + default model** — *Resolved in proposal*: key `'nova'`,
  default `nova-2-lite` (with `region_prefix="us"` per AWS geo-only access).
- [x] **Generation scope** — *Resolved in proposal*: minimal parity —
  `generate_image()` (Canvas) + `video_generation()` (Reel); batch deferred.
- [x] **Exact Bedrock IDs** — *Resolved by AWS docs research (2026-07-17)*:
  see §6 Verified AWS Facts table.

### Unresolved (defer to implementation)

- [x] Reel S3 housekeeping: should `video_generation()` delete the S3 object
  after downloading it locally? — *Owner: implementer* (default: keep; add a
  `cleanup_s3: bool = False` kwarg if trivial): keep
- [x] Whether `NovaClient` should expose `voice_id` per-call in
  `stream_voice(**kwargs)` in addition to the constructor — *Owner:
  implementer* (nova_sonic.py only supports constructor today): yes, expose voice_id per-call

---

## Worktree Strategy

- **Isolation unit**: `per-spec` — one worktree, tasks run sequentially.
  Modules 1→7 form a dependency chain (base extraction → subpackage → catalog/
  factory → migration → tests); parallelizing them would conflict on
  `bedrock.py` and the test tree.
- **Worktree**: `git worktree add -b feat-315-novaclient-amazon-aws .claude/worktrees/feat-315-novaclient-amazon-aws HEAD` (from `dev`).
- **Cross-feature dependencies**: none pending — FEAT-302 (bedrock-client-llm)
  is merged; commit `3672eb2f4` (wip: nova model) is already on `dev` and is
  superseded/fixed by Module 1.
- **Cross-package note**: Module 6 touches `packages/ai-parrot-integrations`
  in the same worktree/branch; release both distributions together.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-07-17 | Jesus + Claude (Fable 5) | Initial draft from proposal FEAT-315 |
