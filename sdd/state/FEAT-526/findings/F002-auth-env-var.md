# F002 — Official auth env var is `MODEL_API_KEY`, not `META_API_KEY`

**Source**: `dev.meta.ai/docs/authentication.md`, `/docs/sdks.md`

- Bearer token in `Authorization: Bearer $MODEL_API_KEY`.
- Key format: `LLM|607358788850350|nx9.....LJY` (pipe-delimited, NOT `sk-`).
- Docs: *"The official SDKs read `MODEL_API_KEY` automatically when you don't
  pass a key to the client."*
- Docs also warn: *"The OpenAI SDK looks for `OPENAI_API_KEY` by default, not
  `MODEL_API_KEY`. Pass your Model API key explicitly."*

**Divergence from brief**: the user asked for `META_API_KEY` as the default env
var. That is a parrot-side naming choice, not what the vendor documents.
**Implication**: resolve a chain rather than picking one —
`api_key` kwarg → `META_API_KEY` (user's stated preference, first) →
`MODEL_API_KEY` (vendor default). Never fall back to `OPENAI_API_KEY`.
