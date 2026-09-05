# ai-parrot-client-openai

OpenAI LLM client satellite for [AI-Parrot](https://github.com/phenobarbital/ai-parrot).

Provides `parrot.clients.openai.OpenAIClient` (Chat Completions / Responses
API) and `parrot.clients.openai.OpenAICodexClient` (the OpenAI Codex CLI/SDK
agent). Registers itself with `LLMFactory` via the `parrot.clients` entry
point group — no import of this package is required for core AI-Parrot to
know it exists once installed.

```bash
uv pip install ai-parrot-client-openai
```

See `sdd/specs/pep-420-llm-clients.spec.md` (FEAT-523) for the extraction
this package was split from.
