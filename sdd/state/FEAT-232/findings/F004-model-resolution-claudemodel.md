# F004 — Model resolution & ClaudeModel enum (translation surface)

**Query**: how model IDs are resolved before SDK calls; ClaudeModel enum shape.

## Summary
Models are plain Anthropic public IDs (`claude-sonnet-4-6`, etc.) resolved from
the `ClaudeModel` enum or `self.model`/`self.default_model` at each call site.
There is **no** abstraction translating public IDs to Bedrock IDs today. Bedrock
requires IDs like `anthropic.claude-sonnet-4-5-20250929-v1:0` or cross-region
inference-profile IDs (`us.anthropic.claude-...`); AWS-workspace uses the plain
public IDs unchanged.

## Citations
- `packages/ai-parrot/src/parrot/models/claude.py:4-28` — `class ClaudeModel(Enum)` with public IDs + aliases (OPUS_4_6, SONNET_4_6, HAIKU_4_5, ...)
- `packages/ai-parrot/src/parrot/clients/claude.py:227` — `model = (model.value if isinstance(model, ClaudeModel) else model) or (self.model or self.default_model)`
- `packages/ai-parrot/src/parrot/clients/claude.py:499,638,662` — three more sites resolving `model` the same way (batch, structured, vision paths)

## Relevance
The Bedrock subclass needs a single `_translate_model(public_id) -> bedrock_id`
hook applied where the resolved string is handed to the SDK. Because the model
string is resolved at **4 call sites**, the cleanest seam is to override a small
helper that every site already funnels through, or to translate inside
`get_client()`-adjacent request building. This is the main implementation risk:
the 4 sites must all route through the translation, or Bedrock calls will 404.
