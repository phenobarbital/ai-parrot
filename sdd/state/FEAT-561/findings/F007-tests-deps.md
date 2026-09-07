---
id: F007
query_id: Q014
type: read
intent: Mock coverage and dependencies exist; combined live validation does not follow from them
executed_at: 2026-09-07T05:42:49.930842+00:00
parent_id: null
depth: 1
---

# F007 — Mock coverage and dependencies exist; combined live validation does not follow from them

## Summary

Existing avatar tests cover PCM identity, interruption and lifecycle with mocked transports. Viewer tests assert distinct identities and response shape, but their fake token factory returns the same viewer-jwt string, so they do not prove unique JWT subjects or simultaneous media delivery. livekit-api and livekit already exist in the optional liveavatar extra; the UI declares livekit-client. The Amazon satellite deliberately leaves the pre-alpha voice SDK undeclared and documents manual installation. No dependencies were installed and no runtime tests were run during proposal research.

## Citations

- path: `packages/ai-parrot-integrations/tests/voice/test_voicechat_avatar_integration.py`
  lines: 1-149
  symbol: `test_gemini_audio_to_avatar_end_to_end`

- path: `packages/ai-parrot-integrations/tests/voice/test_voice_avatar_session.py`
  lines: 20-84
  symbol: `test_viewer_credentials_no_agent_token`

- path: `packages/ai-parrot-server/tests/handlers/test_avatar_viewers.py`
  lines: 35-91,176-200
  symbol: `test_mint_viewer_tokens_returns_n_tokens`

- path: `packages/ai-parrot-integrations/pyproject.toml`
  lines: 91-97
  symbol: `liveavatar`

- path: `packages/ai-parrot-client-amazon/pyproject.toml`
  lines: 17-25
  symbol: `dependencies`

- path: `packages/ai-parrot-server/ui/package.json`
  lines: 45
  symbol: `livekit-client`
