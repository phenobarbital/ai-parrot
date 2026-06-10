# F002 — LLMFactory provider registry

**Query**: how providers are registered and resolved.

## Summary
`SUPPORTED_CLIENTS` is a flat `dict[str, type | lazy-loader]`. The factory
parses `"provider:model"`, looks up the class (resolving callables that are not
types as lazy loaders), and instantiates with `model`, `model_args`, and kwargs.
New backends are added by inserting keys here.

## Citations
- `packages/ai-parrot/src/parrot/clients/factory.py:49-69` — `SUPPORTED_CLIENTS` dict; `"claude"`/`"anthropic"` → `AnthropicClient`
- `packages/ai-parrot/src/parrot/clients/factory.py:16-46` — `_lazy_claude_agent()` pattern: catches missing-SDK `ImportError`, re-raises with `pip install` hint
- `packages/ai-parrot/src/parrot/clients/factory.py:143-181` — `create()`: validates provider, resolves lazy loader, builds `init_params`, returns `client_class(**init_params)`

## Relevance
Adding `"bedrock"` / `"anthropic-aws"` keys (pointing at new subclasses, ideally
via the `_lazy_*` pattern so missing `anthropic[aws]`/boto deps fail with an
actionable hint) is the minimal, idiomatic wiring. No factory logic changes
needed beyond the dict entries + lazy loaders.
