# ai-parrot-client-grok

xAI Grok LLM client satellite for
[AI-Parrot](https://github.com/phenobarbital/ai-parrot).

Provides `parrot.clients.grok.GrokClient`, using xAI's native `xai_sdk`
(gRPC transport). Registers itself with `LLMFactory` via the
`parrot.clients` entry point group — no import of this package is
required for core AI-Parrot to know it exists once installed.

```bash
uv pip install ai-parrot-client-grok
```

See `sdd/specs/pep-420-llm-clients.spec.md` (FEAT-523) for the extraction
this package was split from.
