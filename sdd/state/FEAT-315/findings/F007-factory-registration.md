# F007 — Factory registration: no "nova" key today; lazy-loader pattern established

**Query**: Q011/Q014 · **Type**: read · `packages/ai-parrot/src/parrot/clients/factory.py` (221 lines)

- `SUPPORTED_CLIENTS` maps provider keys → client class or lazy loader.
  Optional-dependency clients use module-level lazy loaders that raise
  actionable ImportErrors: `_lazy_bedrock_converse` ("bedrock-converse"),
  `_lazy_claude_agent`, `_lazy_gemma4` (lines 16-94).
- **NovaSonicClient is NOT registered in the factory at all** — it is only
  reachable via `bots/voice.py` provider dispatch and direct import.
- `LLMFactory.create("provider:model")` parses provider/model, resolves lazy
  loaders, injects model_args and `PROVIDER_BACKEND` backend kwarg (FEAT-232).
- Sibling inventory (Q014): 18 client classes; Google is the only one using
  the subpackage + mixins layout — the pattern FEAT-315 mirrors.
- `parrot/clients/__init__.py` exports only AbstractClient, LLM_PRESETS,
  StreamingRetryConfig, ZaiClient — clients are imported from their modules
  or via the factory, so a new `nova/` subpackage needs no top-level export
  change (though google/__init__ alias style applies inside the subpackage).

## Citations
- packages/ai-parrot/src/parrot/clients/factory.py:16-103,137-221
- packages/ai-parrot/src/parrot/clients/__init__.py:1-19
