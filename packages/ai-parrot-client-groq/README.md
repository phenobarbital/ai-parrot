# ai-parrot-client-groq

Groq LLM client satellite for
[AI-Parrot](https://github.com/phenobarbital/ai-parrot).

Provides `parrot.clients.groq.GroqClient` (built on the OpenAI-compatible
`OpenAIBaseClient`, using Groq's native `groq.AsyncGroq` SDK behind the
scenes). Registers itself with `LLMFactory` via the `parrot.clients` entry
point group — no import of this package is required for core AI-Parrot to
know it exists once installed.

```bash
uv pip install ai-parrot-client-groq
```

See `sdd/specs/pep-420-llm-clients.spec.md` (FEAT-523) for the extraction
this package was split from.
