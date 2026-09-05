# ai-parrot-client-vllm

vLLM (OpenAI-compatible) LLM client satellite for
[AI-Parrot](https://github.com/phenobarbital/ai-parrot).

Provides `parrot.clients.vllm.vLLMClient`, which subclasses
`parrot.clients.local.LocalLLMClient` (hence the dependency on
`ai-parrot-client-local`). Registers itself with `LLMFactory` via the
`parrot.clients` entry point group — no import of this package is
required for core AI-Parrot to know it exists once installed.

```bash
uv pip install ai-parrot-client-vllm
```

See `sdd/specs/pep-420-llm-clients.spec.md` (FEAT-523) for the extraction
this package was split from.
