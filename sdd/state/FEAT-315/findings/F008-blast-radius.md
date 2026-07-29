# F008 — Refactor blast radius: voice bot, voice integration package, tests

**Query**: Q010/Q016 · **Type**: grep + tree

Import sites of `parrot.clients.nova_sonic.NovaSonicClient`:
- `packages/ai-parrot/src/parrot/bots/voice.py:164-225` — provider key
  `'nova_sonic'` lazily imports and instantiates NovaSonicClient (two sites).
- `packages/ai-parrot-integrations/src/parrot/voice/models.py:30-34` —
  `VoiceProvider.NOVA_SONIC = "nova_sonic"` enum member.
- `packages/ai-parrot-integrations/src/parrot/voice/handler.py:77,98,332` —
  lazy import in the voice handler.
- `packages/ai-parrot/src/parrot/models/voice.py` — voice config references.

Tests that pin the current shape:
- `packages/ai-parrot/tests/clients/test_nova_sonic.py`
- `packages/ai-parrot/tests/bots/test_voicebot_nova_sonic_wiring.py`
- `packages/ai-parrot/tests/models/test_voice_config.py`
- `packages/ai-parrot/tests/models/test_bedrock_models.py`
- `packages/ai-parrot-integrations/tests/voice/test_nova_sonic_provider.py`
- Bedrock suite: test_bedrock_{advanced,converse,errors,integration}.py,
  test_factory_bedrock.py; Google suite: test_google_models.py,
  test_google_computer_use.py.

Note: the integrations package is a **separate distribution** — renaming or
moving `parrot.clients.nova_sonic` without a shim breaks it independently of
the core package's release cadence.

## Citations
- packages/ai-parrot/src/parrot/bots/voice.py:164-225
- packages/ai-parrot-integrations/src/parrot/voice/{models.py:30-34,handler.py:77-98}
- packages/ai-parrot/tests/clients/ (ls)
