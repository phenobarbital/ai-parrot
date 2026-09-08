# ai-parrot-client-hf

HuggingFace `transformers` micro-LLM client satellite for
[AI-Parrot](https://github.com/phenobarbital/ai-parrot).

Provides `parrot.clients.hf.TransformersClient`, for small local
HuggingFace causal-LM models. Registers itself with `LLMFactory` via the
`parrot.clients` entry point group — no import of this package is
required for core AI-Parrot to know it exists once installed.

Requires a local PyTorch install (`torch`) at runtime — not declared as a
hard dependency here (see `pyproject.toml`); install it separately.

```bash
uv pip install ai-parrot-client-hf
```

See `sdd/specs/pep-420-llm-clients.spec.md` (FEAT-523) for the extraction
this package was split from.
