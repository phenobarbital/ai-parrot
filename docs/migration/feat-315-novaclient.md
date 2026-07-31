# Migration — FEAT-315: Unified NovaClient for all Amazon Nova models

**Feature**: FEAT-315
**Status**: in progress (target: next minor)
**Affects**: anyone using `NovaSonicClient`, the `'nova_sonic'` voice
provider key, or `VoiceProvider.NOVA_SONIC` (`ai-parrot-integrations`).

## What changed

`parrot.clients.nova_sonic.NovaSonicClient` (voice-only, FEAT-302) is
**deleted**. It is replaced by a single unified client,
`parrot.clients.nova.NovaClient`, covering ALL Amazon Nova modalities:

- **Text** (Nova 2 Lite, Micro, Pro, Premier): `ask()`/`ask_stream()`/
  `invoke()`/`resume()` — inherited directly from the shared Bedrock
  Converse engine (`BedrockConverseBase`), no internal delegate client.
- **Voice** (Nova Sonic / Nova 2 Sonic): `stream_voice()` — same event
  protocol, base64 audio handling, tool-use loop, and 8-minute
  `reconnect_required` behavior as before.
- **Generation** (Nova Canvas / Nova Reel): `generate_image()` /
  `video_generation()` — new capabilities, not available in
  `NovaSonicClient`.

This is an **intentional breaking change** — there is no compatibility
shim and no deprecated alias. `ai-parrot` and `ai-parrot-integrations`
must be upgraded together (lockstep release).

## Breaking renames

| Old | New |
|---|---|
| `parrot.clients.nova_sonic.NovaSonicClient` | `parrot.clients.nova.NovaClient` |
| `VoiceConfig(provider="nova_sonic")` (core `ai-parrot`) | `VoiceConfig(provider="nova")` |
| `VoiceProvider.NOVA_SONIC` / `.value == "nova_sonic"` (`ai-parrot-integrations`) | `VoiceProvider.NOVA` / `.value == "nova"` |

### Before

```python
# core ai-parrot — VoiceBot
bot = VoiceBot(voice_config=VoiceConfig(provider="nova_sonic", voice_name="matthew"))

# ai-parrot-integrations
from parrot.voice.models import VoiceProvider
config = VoiceConfig(provider=VoiceProvider.NOVA_SONIC)
```

### After

```python
# core ai-parrot — VoiceBot
bot = VoiceBot(voice_config=VoiceConfig(provider="nova", voice_name="matthew"))

# ai-parrot-integrations
from parrot.voice.models import VoiceProvider
config = VoiceConfig(provider=VoiceProvider.NOVA)
```

## New capability: factory + text/image/video

`NovaClient` is now registered in `LLMFactory` under the `'nova'` key
(this key did not exist before — `NovaSonicClient` was never
factory-registered):

```python
from parrot.clients.factory import LLMFactory

client = LLMFactory.create("nova")              # text, nova-2-lite, region_prefix="us"
client = LLMFactory.create("nova:nova-micro")   # text, explicit model

await client.generate_image("a red panda")                  # Nova Canvas
await client.video_generation("a dancing robot", ...)       # Nova Reel
```

## Code changes required

1. Replace any `from parrot.clients.nova_sonic import NovaSonicClient` with
   `from parrot.clients.nova import NovaClient`.
2. Replace `provider="nova_sonic"` / `VoiceProvider.NOVA_SONIC` with
   `provider="nova"` / `VoiceProvider.NOVA` everywhere (`VoiceConfig`,
   config files, environment-driven provider selection).
3. If you constructed `NovaSonicClient` directly with `text_fallback_model`
   or relied on its internal `BedrockConverseClient` text-fallback delegate,
   note that `NovaClient` has NO delegate — text methods are inherited
   directly; pass `model=` as you would for any other client.
4. `NovaClient(region_prefix="us")` is the default (Nova 2 Lite/Premier
   require a geo/global inference profile) — override for EU/JP
   deployments, or pass `region_prefix=None` for in-region custom
   deployments.

## Lockstep release requirement

`ai-parrot-integrations`' `voice/handler.py` and `voice/models.py` resolve
`VoiceProvider.NOVA` to `parrot.clients.nova.NovaClient` — both packages
must be released together. Upgrading only one will break voice-provider
resolution for Nova.

## What did NOT change

- `BedrockConverseClient` (Claude/Llama/Mistral/... on Bedrock) — public
  surface is byte-compatible; only its internal engine was extracted into
  `BedrockConverseBase` (FEAT-315 Module 1).
- `GeminiLiveClient` / the `'google_live'` voice provider — untouched.
- `AnthropicClient`'s Bedrock backend (`'bedrock'` / `'anthropic-aws'`
  factory keys, FEAT-232) — untouched.
