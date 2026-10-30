---
id: F037
query_id: Q026-F2
type: read
intent: "Follow-up: read parrot/auth/oauth2/registry.py — OAuth2Provider ABC and the singleton registry."
executed_at: 2026-10-30T12:24:35Z
duration_ms: 0
parent_id: FC-007
depth: 1
merged_from: [FC-038]
---

# F037 — OAuth2Provider ABC (provider_id, display_name, icon, default_scopes, pbac_action_namespace, manager property, toolkit_factory) + OAuth2ProviderRegistry singleton (register/get/all) + register_oauth2_provider()

## Summary

136 lines. `OAuth2Provider(ABC)` class-level metadata + abstract `manager` property + abstract `toolkit_factory(credential_resolver) -> AbstractToolkit`. `OAuth2ProviderRegistry` is a `__new__` singleton with `register(provider)`, `get(provider_id)`, `all()` and a test-only `_reset`. Module-level `register_oauth2_provider(provider)`.

## Citations

- path: `packages/ai-parrot/src/parrot/auth/oauth2/registry.py`
  lines: 20-67
  symbol: `OAuth2Provider`
  excerpt: |
    class OAuth2Provider(ABC):
        provider_id: str; display_name: str; icon: Optional[str] = None
        default_scopes: ClassVar[List[str]] = []
        pbac_action_namespace: str = "integration"
        @property @abstractmethod def manager(self) -> Any
        @abstractmethod def toolkit_factory(self, credential_resolver) -> AbstractToolkit
- path: `packages/ai-parrot/src/parrot/auth/oauth2/registry.py`
  lines: 69-126
  symbol: `OAuth2ProviderRegistry`
  excerpt: |
    class OAuth2ProviderRegistry:
        def __new__(cls) -> singleton
        def register(self, provider: OAuth2Provider) -> None
        def get(self, provider_id: str) -> Optional[OAuth2Provider]
        def all(self) -> List[OAuth2Provider]
    def register_oauth2_provider(provider: OAuth2Provider) -> None

## Notes

The 'provider descriptor as data' the brainstorm wants is split today: UI/PBAC metadata on `OAuth2Provider` subclasses (code), protocol behaviour on `AbstractOAuth2Manager` subclasses (code), MCP presets as Pydantic data (`MCPOAuth2Preset`). No YAML/config loading of providers.
