---
id: F009
query_id: Q028
type: read
intent: "Registry: read the integrations-side OAuth2 provider registry."
executed_at: 2026-10-30T12:24:35Z
duration_ms: 0
parent_id: null
depth: 0
merged_from: [FC-009]
---

# F009 — integrations/core/auth/oauth2_providers.py is a tiny LOGIN-provider catalog (google only) for channel sign-in, unrelated to per-user 3LO tool credentials

## Summary

`parrot/integrations/core/auth/oauth2_providers.py` (67 lines): frozen dataclass `OAuth2ProviderConfig(name, authorization_url, token_url, userinfo_url, default_scopes)` and dict `OAUTH2_PROVIDERS` with one entry (`google`). `get_provider(name)` raises ValueError when unknown. Docstring: lifted from telegram so Telegram/Slack/Teams share it for *login* flows.

## Citations

- path: `packages/ai-parrot-integrations/src/parrot/integrations/core/auth/oauth2_providers.py`
  lines: 16-44
  symbol: `OAuth2ProviderConfig`
  excerpt: |
    @dataclass(frozen=True)
    class OAuth2ProviderConfig: name; authorization_url; token_url; userinfo_url; default_scopes
    OAUTH2_PROVIDERS = {"google": OAuth2ProviderConfig(...)}

## Notes

Two different 'provider registries' exist: this login catalog (integrations) and `parrot.auth.oauth2.registry.OAuth2ProviderRegistry` (core, for 3LO tool credentials). The proposal must not conflate them.
