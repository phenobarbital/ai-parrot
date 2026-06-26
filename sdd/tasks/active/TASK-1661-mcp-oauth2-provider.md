# TASK-1661: MCPOAuth2Provider & Registry Integration

**Feature**: FEAT-262 — MCP Server OAuth2 Support
**Spec**: `sdd/specs/mcp-server-oauth2-support.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1659, TASK-1660
**Assigned-to**: unassigned

---

## Context

Creates an `MCPOAuth2Provider` that subclasses the existing `OAuth2Provider` ABC,
registering MCP OAuth2 servers in the unified `OAuth2ProviderRegistry`. This makes
MCP OAuth2 tokens visible in `IntegrationsService.list_for_user()` alongside O365/Jira.
Implements spec Module 3.

---

## Scope

- Create `parrot/auth/oauth2/mcp_provider.py` with:
  - `MCPOAuth2Provider(OAuth2Provider)` class with `provider_id = "mcp:{server_name}"`
  - `manager` property returning the MCP SDK's OAuth context (or a wrapper)
  - `toolkit_factory()` returning `None` (MCP servers expose tools via MCP protocol, not toolkits)
  - `register_mcp_oauth2_provider(server_name, config, storage)` factory function
    that creates and registers an `MCPOAuth2Provider` in the singleton registry
- Write unit tests

**NOT in scope**: Transport integration (TASK-1663), callback routes (TASK-1664),
`IntegrationsService` modifications (the existing service already iterates
`OAuth2ProviderRegistry.all()` — registering here is sufficient).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/auth/oauth2/mcp_provider.py` | CREATE | MCPOAuth2Provider class + factory |
| `tests/auth/test_mcp_oauth2_provider.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# OAuth2 provider registry (verified: parrot/auth/oauth2/registry.py:20, 69, 126)
from parrot.auth.oauth2.registry import OAuth2Provider, OAuth2ProviderRegistry
from parrot.auth.oauth2.registry import register_oauth2_provider

# Config models (from TASK-1659)
from parrot.mcp.oauth2_config import MCPOAuth2Config

# Storage adapter (from TASK-1660)
from parrot.mcp.oauth2_storage import VaultMCPTokenStorage
```

### Existing Signatures to Use
```python
# parrot/auth/oauth2/registry.py:20
class OAuth2Provider(ABC):
    provider_id: str                                # required
    display_name: str                               # required
    icon: Optional[str] = None
    default_scopes: ClassVar[List[str]] = []
    pbac_action_namespace: str = "integration"
    @property
    @abstractmethod
    def manager(self) -> Any: ...                   # line 44
    @abstractmethod
    def toolkit_factory(self, credential_resolver) -> AbstractToolkit: ...  # line 53

# parrot/auth/oauth2/registry.py:69
class OAuth2ProviderRegistry:  # singleton
    def register(self, provider: OAuth2Provider) -> None: ...   # line 96
    def get(self, provider_id: str) -> Optional[OAuth2Provider]: ...  # line 106
    def all(self) -> List[OAuth2Provider]: ...                  # line 117

# parrot/auth/oauth2/registry.py:126
def register_oauth2_provider(provider: OAuth2Provider) -> None: ...
```

### Does NOT Exist
- ~~`parrot.auth.oauth2.mcp_provider`~~ — this is the module being created
- ~~`MCPOAuth2Provider`~~ — does not exist yet
- ~~`register_mcp_oauth2_provider()`~~ — does not exist yet
- ~~`OAuth2Provider.toolkit_factory()` returning tools~~ — for MCP, it returns `None`

---

## Implementation Notes

### Pattern to Follow
```python
# Follow JiraOAuth2Provider pattern (parrot/auth/oauth2/jira_provider.py)
class MCPOAuth2Provider(OAuth2Provider):
    provider_id: str
    display_name: str
    default_scopes: ClassVar[List[str]] = []

    def __init__(self, server_name: str, config: MCPOAuth2Config,
                 storage: VaultMCPTokenStorage):
        self.provider_id = f"mcp:{server_name}"
        self.display_name = f"MCP: {server_name}"
        self.default_scopes = list(config.scopes)
        self._config = config
        self._storage = storage

    @property
    def manager(self) -> Any:
        return None  # MCP SDK manages the flow directly

    def toolkit_factory(self, credential_resolver):
        return None  # MCP tools come from the MCP protocol, not from toolkits
```

### Key Constraints
- `provider_id` format: `"mcp:{server_name}"` (e.g. `"mcp:netsuite"`)
- `toolkit_factory` returns `None` — MCP servers provide tools via MCP protocol
- Must work with the existing singleton `OAuth2ProviderRegistry`

---

## Acceptance Criteria

- [ ] `MCPOAuth2Provider` subclasses `OAuth2Provider` correctly
- [ ] `register_mcp_oauth2_provider()` registers in singleton `OAuth2ProviderRegistry`
- [ ] Registered provider appears in `OAuth2ProviderRegistry().all()`
- [ ] `provider_id` follows `"mcp:{server_name}"` format
- [ ] `toolkit_factory()` returns `None`
- [ ] All tests pass: `pytest tests/auth/test_mcp_oauth2_provider.py -v`
- [ ] Import works: `from parrot.auth.oauth2.mcp_provider import MCPOAuth2Provider`

---

## Test Specification

```python
# tests/auth/test_mcp_oauth2_provider.py
import pytest
from parrot.auth.oauth2.mcp_provider import MCPOAuth2Provider, register_mcp_oauth2_provider
from parrot.auth.oauth2.registry import OAuth2ProviderRegistry
from parrot.mcp.oauth2_config import MCPOAuth2Config


@pytest.fixture(autouse=True)
def reset_registry():
    OAuth2ProviderRegistry._reset()
    yield
    OAuth2ProviderRegistry._reset()


class TestMCPOAuth2Provider:
    def test_provider_id_format(self):
        cfg = MCPOAuth2Config(client_id="test", scopes=["read"])
        provider = MCPOAuth2Provider("my-server", cfg, storage=None)
        assert provider.provider_id == "mcp:my-server"

    def test_toolkit_factory_returns_none(self):
        cfg = MCPOAuth2Config(client_id="test")
        provider = MCPOAuth2Provider("srv", cfg, storage=None)
        assert provider.toolkit_factory(None) is None

    def test_registration(self):
        cfg = MCPOAuth2Config(client_id="test", scopes=["mcp"])
        register_mcp_oauth2_provider("netsuite", cfg, storage=None)
        registry = OAuth2ProviderRegistry()
        assert registry.get("mcp:netsuite") is not None

    def test_listed_in_all(self):
        cfg = MCPOAuth2Config(client_id="test")
        register_mcp_oauth2_provider("fireflies", cfg, storage=None)
        all_providers = OAuth2ProviderRegistry().all()
        assert any(p.provider_id == "mcp:fireflies" for p in all_providers)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-1659 and TASK-1660 are in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — confirm `OAuth2Provider` ABC at `parrot/auth/oauth2/registry.py:20`
4. **Implement** the provider and registration factory
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/`
7. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
