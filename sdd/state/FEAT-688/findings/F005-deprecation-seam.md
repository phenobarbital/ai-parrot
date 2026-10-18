---
id: F005
query_id: Q003,Q009
type: grep
intent: "Find the existing deprecation mechanism for provider model catalogues"
executed_at: 2026-10-15T17:48:00Z
parent_id: null
depth: 1
---

# F005 — A `deprecated_models` seam already exists; Google is the provider that does not use it

## Summary

`LLMFactory.list_models(provider)` returns `{"active": [...], "deprecated":
[...]}`, reading `active` from `client_class.models` (the enum) and
`deprecated` from an optional `client_class.deprecated_models` attribute via
`getattr`. **`OpenAIClient` is the only client in the workspace that defines
it**; `GoogleGenAIClient` does not, so Google's `deprecated` list is always
empty. The OpenAI module is a ready-made precedent: deprecated ids are
*removed* from the enum and re-declared in a `DEPRECATIONS` dict carrying a
`shutoff` date and an optional replacement `alias`, with helper predicates
over it.

## Citations

- path: `packages/ai-parrot/src/parrot/clients/factory.py`
  lines: 224-253
  symbol: `LLMFactory.list_models`
  excerpt: |
    def list_models(provider: str) -> Dict[str, list]:
        """Return the active/deprecated model catalogue for ``provider``."""
        return {
            "active": [m.value for m in client_class.models],
            # Not every client defines `deprecated_models` — only classes
            # with actual deprecations (e.g. OpenAIClient) declare it;
            "deprecated": list(getattr(client_class, "deprecated_models", None) or {}),
        }

- path: `packages/ai-parrot-client-openai/src/parrot/clients/openai/models.py`
  lines: 6-18
  symbol: `OpenAIModel` docstring
  excerpt: |
    - ``DEPRECATIONS`` — registry of deprecated model IDs.
    """Current OpenAI model catalog (deprecated IDs removed — see DEPRECATIONS)."""

- path: `packages/ai-parrot-client-openai/src/parrot/clients/openai/models.py`
  lines: 85-95
  symbol: `DEPRECATIONS`
  excerpt: |
    DEPRECATIONS: dict[str, DeprecationInfo] = {
        # shutoff 2026-10-23
        "gpt-4-0613": DeprecationInfo(shutoff=date(2026, 10, 23), ft_shutoff=date(2026, 10, 23), alias="gpt-4"),
        "gpt-4-turbo-2024-04-09": DeprecationInfo(shutoff=date(2026, 10, 23), alias="gpt-4-turbo"),

- path: `packages/ai-parrot-client-openai/src/parrot/clients/openai/models.py`
  lines: 172-201
  symbol: `is_deprecated` / shutoff lookup
  excerpt: |
    """Return True if ``model`` is in DEPRECATIONS or matches an alias entry.
    if s in DEPRECATIONS:
        return DEPRECATIONS[s].shutoff

- path: `packages/ai-parrot-client-openai/src/parrot/clients/openai/client.py`
  lines: 101
  symbol: `OpenAIClient.deprecated_models`
  excerpt: |
    deprecated_models: dict = DEPRECATIONS

- path: `packages/ai-parrot-server/src/parrot/handlers/studio/catalog.py`
  lines: 227-244
  symbol: `_provider_models`
  excerpt: |
    "deprecated_models": [],
    models, deprecated_models = _provider_models(provider)
    "deprecated_models": deprecated_models,

## Notes

This is the decisive structural difference between "retirar los deprecated" as
a plain deletion and as a *migration*: the OpenAI shape keeps the retired id
resolvable and tells callers what replaces it. Google today has no way to
express either.
