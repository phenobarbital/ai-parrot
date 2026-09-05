# ai-parrot-client-google

Google GenAI (Gemini) LLM clients satellite for
[AI-Parrot](https://github.com/phenobarbital/ai-parrot).

Provides `parrot.clients.google.GoogleGenAIClient` (Gemini text/vision/
generation) and `parrot.clients.google.GeminiLiveClient` (Gemini Live
voice API). Registers itself with `LLMFactory` via the `parrot.clients`
entry point group — no import of this package is required for core
AI-Parrot to know it exists once installed.

```bash
uv pip install ai-parrot-client-google
```

See `sdd/specs/pep-420-llm-clients.spec.md` (FEAT-523) for the extraction
this package was split from.
