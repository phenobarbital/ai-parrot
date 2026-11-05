---
id: FC-016
query_id: Q025
type: grep
intent: "Model deprecation sweep precedent (FEAT-719): how deprecated ids were handled last time (deprecated_models map vs pure deletion)."
executed_at: 2026-11-04T01:42:07Z
duration_ms: 300
parent_id: null
depth: 0
---

# FC-016 — The Google client defines no deprecated_models; LLMFactory supports the attribute optionally, so retirement today means deletion

## Summary

Neither `ai-parrot-client-google/src` nor `parrot/clients/` defines `deprecated_models` or any deprecation map; the only mention is `clients/factory.py:248-253`, which `getattr`s an optional `deprecated_models` on the client class (comment: "only classes with actual deprecations (e.g. OpenAIClient) declare it"). Consequently `LLMFactory.list_models("google")["deprecated"]` is empty and a retired id simply stops resolving — consistent with FEAT-688's "pure deletion" decision. No alias/redirect machinery exists to map `gemini-2.5-flash` → a successor at runtime.

## Citations

- path: `packages/ai-parrot/src/parrot/clients/factory.py`
  lines: 247-253
  symbol: `LLMFactory.list_models`
  excerpt: |
    "active": [m.value for m in client_class.models],
    # Not every client defines `deprecated_models` — only classes
    # with actual deprecations (e.g. OpenAIClient) declare it;
    # AbstractClient carries no base default (base.py is out of
    # scope for this feature), so this must getattr rather than
    # rely on the attribute always existing.
    "deprecated": list(getattr(client_class, "deprecated_models", None) or {}),

## Notes

- Grep for `deprecated_models|DEPRECATED_MODELS|_deprecated` over `ai-parrot-client-google/src` returned nothing (proves absence).
- `[cross-lane: type=git_log, intent=how FEAT-719 (PR #1773) removed ids — pure deletion or deprecated_models map — to keep the retirement shape consistent]`
