# ai-parrot-client-gemma4

Google Gemma 4 (local, `transformers`) LLM client satellite for
[AI-Parrot](https://github.com/phenobarbital/ai-parrot).

Provides `parrot.clients.gemma4.Gemma4Client`, a local multimodal client
for the Gemma 4 model family (processor-based architecture). Registers
itself with `LLMFactory` via the `parrot.clients` entry point group — no
import of this package is required for core AI-Parrot to know it exists
once installed.

Requires a local PyTorch install (`torch`) at runtime — not declared as a
hard dependency here (see `pyproject.toml`); install it separately.

```bash
uv pip install ai-parrot-client-gemma4
```

See `sdd/specs/pep-420-llm-clients.spec.md` (FEAT-523) for the extraction
this package was split from.
