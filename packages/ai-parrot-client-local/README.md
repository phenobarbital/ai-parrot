# ai-parrot-client-local

Local (Ollama/llama.cpp, OpenAI-compatible) LLM client satellite for
[AI-Parrot](https://github.com/phenobarbital/ai-parrot).

Provides `parrot.clients.local.LocalLLMClient` (built on the
OpenAI-compatible `OpenAIBaseClient`, pointed at any local
OpenAI-compatible server). Registers itself with `LLMFactory` via the
`parrot.clients` entry point group — no import of this package is
required for core AI-Parrot to know it exists once installed.

`ai-parrot-client-vllm` depends on this package (`vLLMClient` subclasses
`LocalLLMClient`).

```bash
uv pip install ai-parrot-client-local
```

See `sdd/specs/pep-420-llm-clients.spec.md` (FEAT-523) for the extraction
this package was split from.
