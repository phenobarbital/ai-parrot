# ai-parrot-client-amazon

Amazon Bedrock LLM clients satellite for
[AI-Parrot](https://github.com/phenobarbital/ai-parrot).

Provides `parrot.clients.amazon.BedrockConverseClient` (native Bedrock
Converse API), `parrot.clients.amazon.NovaClient` (unified Amazon Nova
text/voice/image/video client), and
`parrot.clients.amazon.BedrockMantleClient` (OpenAI-compatible Bedrock
Mantle API). Registers itself with `LLMFactory` via the `parrot.clients`
entry point group — no import of this package is required for core
AI-Parrot to know it exists once installed.

```bash
uv pip install ai-parrot-client-amazon
```

See `sdd/specs/pep-420-llm-clients.spec.md` (FEAT-523) for the extraction
this package was split from.
