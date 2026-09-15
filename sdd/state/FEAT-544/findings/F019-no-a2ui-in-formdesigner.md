---
id: F019
query_id: Q019
type: grep
intent: Prior A2UI mentions in parrot-formdesigner
executed_at: 2026-09-10T00:39:55Z
duration_ms: null
parent_id: null
depth: 0
---

# F019 — No A2UI code in parrot-formdesigner

## Summary

No matches for `a2ui` (case-insensitive) anywhere under `packages/parrot-formdesigner/src`, `docs` or README — the integration is greenfield on the FormDesigner side. `ai-parrot` is an OPTIONAL extra (`[project.optional-dependencies] ai-parrot = ["ai-parrot>=1.0.0"]`); `renderers/audio.py` already imports `parrot.voice.*` lazily inside try/except ImportError — the precedent for importing `parrot.outputs.a2ui` from a FormDesigner renderer.

## Citations

- path: `packages/parrot-formdesigner/pyproject.toml`
  lines: 48-52
  excerpt: |
    [project.optional-dependencies]
    ai-parrot = [
        "ai-parrot>=1.0.0",
    ]
- path: `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/audio.py`
  lines: 151-154
  excerpt: |
    try:
        from parrot.voice.tts.models import TTSConfig
        from parrot.voice.tts.synthesizer import VoiceSynthesizer
    except ImportError as exc:
