---
type: Wiki Overview
title: 'TASK-1662: MCPClientConfig Extension'
id: doc:sdd-tasks-completed-task-1662-mcp-client-config-extension-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Extends `MCPClientConfig` with `oauth2` and `auth_preset` fields. Updates
relates_to:
- concept: mod:parrot.mcp.client
  rel: mentions
- concept: mod:parrot.mcp.oauth2_config
  rel: mentions
---

# TASK-1662: MCPClientConfig Extension

**Feature**: FEAT-262 — MCP Server OAuth2 Support
**Spec**: `sdd/specs/mcp-server-oauth2-support.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1659
**Assigned-to**: unassigned

---

## Context

Extends `MCPClientConfig` with `oauth2` and `auth_preset` fields. Updates
`from_yaml_config()` to parse these fields — resolving presets, merging overrides,
and constructing `MCPOAuth2Config`. Implements spec Module 4.

---

## Scope

- Add `oauth2: Optional[MCPOAuth2Config] = None` field to `MCPClientConfig`
- Add `auth_preset: Optional[str] = None` field to `MCPClientConfig`
- Update `from_yaml_config()` to:
  - Parse `auth_preset:` key → look up preset → create `MCPOAuth2Config` with defaults
  - Parse `oauth2:` key → create `MCPOAuth2Config` from dict
  - When both are set: preset provides defaults, `oauth2:` fields override
  - Add `"oauth2"` and `"auth_preset"` to known fields filter
- Update `get_headers()` to skip `auth_credential` headers when `oauth2` is set
  (transport layer handles auth via MCP SDK)
- Write unit tests

**NOT in scope**: Transport-level OAuth2 injection (TASK-1663), factory method
changes (TASK-1665).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/mcp/client.py` | MODIFY | Add fields, update from_yaml_config |
| `tests/mcp/test_mcp_client_config_oauth2.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Current MCPClientConfig (verified: parrot/mcp/client.py:131)
from parrot.mcp.client import MCPClientConfig, AuthScheme, AuthCredential

# New config model (from TASK-1659)
from parrot.mcp.oauth2_config import MCPOAuth2Config, get_mcp_oauth2_preset
```

### Existing Signatures to Use
```python
# parrot/mcp/client.py:131
@dataclass
class MCPClientConfig:
    name: str                                                    # line 155
    url: Optional[str] = None                                    # line 158
    auth_credential: Optional[AuthCredential] = None             # line 167
    auth_type: Optional[AuthScheme] = None                       # line 168
    auth_config: Dict[str, Any] = field(default_factory=dict)    # line 169
    token_supplier: Optional[Callable] = None                    # line 171
    transport: str = "auto"                                      # line 174
    headers: Dict[str, str] = field(default_factory=dict)        # line 181
    # ... (other fields)
    quic_config: Any = None                                      # line 222

    async def get_headers(self, context=None) -> Dict[str, str]: ...   # line 224
    def validate_transport(self) -> None: ...                          # line 259

    @classmethod
    def from_yaml_config(cls, config_dict, config_abs_path=""):  # line 277
        # line 326: known_fields = {f.name for f in cls.__dataclass_fields__.values()}
        # line 327: filtered = {k: v for k, v in config_dict.items() if k in known_fields}
```

### Does NOT Exist
- ~~`MCPClientConfig.oauth2`~~ — field does not exist yet (being added)
- ~~`MCPClientConfig.auth_preset`~~ — field does not exist yet (being added)

---

## Implementation Notes

### Key Changes to `from_yaml_config()`
```python
# After existing validation, before constructing instance:
# 1. Resolve preset
auth_preset = config_dict.pop('auth_preset', None)
oauth2_dict = config_dict.pop('oauth2', None)

if auth_preset:
    preset = get_mcp_oauth2_preset(auth_preset)
    if not preset:
        raise ValueError(f"Unknown MCP OAuth2 preset: '{auth_preset}' in {config_abs_path}")
    base = preset.model_dump(exclude_none=True, exclude={'name', 'display_name', 'url_template', 'required_params'})
    if oauth2_dict:
        base.update(oauth2_dict)  # overrides
    config_dict['oauth2'] = MCPOAuth2Config(**base)
elif oauth2_dict:
    config_dict['oauth2'] = MCPOAuth2Config(**oauth2_dict)

config_dict['auth_preset'] = auth_preset
```

### Key Constraints
- `oauth2` and `auth_preset` must be added BEFORE the `known_fields` filter at line 326
- When `oauth2` is set, `get_headers()` should still return static `headers` and
  `header_provider` results, but skip `auth_credential` headers (MCP SDK handles auth)
- Backward compatible: existing configs without `oauth2` must work unchanged

---

## Acceptance Criteria

- [ ] `MCPClientConfig` accepts `oauth2` as `MCPOAuth2Config`
- [ ] `MCPClientConfig` accepts `auth_preset` as `str`
- [ ] `from_yaml_config()` resolves `auth_preset` to `MCPOAuth2Config`
- [ ] `from_yaml_config()` parses inline `oauth2:` dict to `MCPOAuth2Config`
- [ ] Preset defaults merged with inline `oauth2:` overrides correctly
- [ ] Unknown preset raises `ValueError`
- [ ] `get_headers()` skips `auth_credential` when `oauth2` is set
- [ ] Existing configs without `oauth2` work unchanged (backward compatible)
- [ ] All tests pass: `pytest tests/mcp/test_mcp_client_config_oauth2.py -v`

---

## Test Specification

```python
# tests/mcp/test_mcp_client_config_oauth2.py
import pytest
from parrot.mcp.client import MCPClientConfig
from parrot.mcp.oauth2_config import MCPOAuth2Config, MCPOAuth2GrantType


class TestMCPClientConfigOAuth2:
    def test_oauth2_field(self):
        cfg = MCPClientConfig(
            name="test",
            url="http://example.com/mcp",
            oauth2=MCPOAuth2Config(client_id="my-app", scopes=["read"]),
        )
        assert cfg.oauth2 is not None
        assert cfg.oauth2.client_id == "my-app"

    def test_from_yaml_with_preset(self):
        cfg = MCPClientConfig.from_yaml_config({
            "name": "ns",
            "url": "http://example.com/mcp",
            "auth_preset": "netsuite",
            "oauth2": {"client_id": "custom-id"},
        })
        assert cfg.oauth2 is not None
        assert cfg.oauth2.client_id == "custom-id"
        assert "mcp" in cfg.oauth2.scopes  # from preset

    def test_from_yaml_inline_oauth2(self):
        cfg = MCPClientConfig.from_yaml_config({
            "name": "custom",
            "url": "http://example.com/mcp",
            "oauth2": {
                "client_id": "app",
                "auth_url": "https://auth.example.com/authorize",
                "token_url": "https://auth.example.com/token",
                "scopes": ["read", "write"],
            },
        })
        assert cfg.oauth2.auth_url == "https://auth.example.com/authorize"

    def test_unknown_preset_raises(self):
        with pytest.raises(ValueError, match="Unknown MCP OAuth2 preset"):
            MCPClientConfig.from_yaml_config({
                "name": "bad",
                "url": "http://example.com",
                "auth_preset": "nonexistent",
            })

    def test_backward_compatible(self):
        cfg = MCPClientConfig.from_yaml_config({
            "name": "simple",
            "url": "http://example.com/mcp",
            "headers": {"X-API-Key": "secret"},
        })
        assert cfg.oauth2 is None
        assert cfg.auth_preset is None
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-1659 is in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — READ `parrot/mcp/client.py` to confirm
   `MCPClientConfig` structure and `from_yaml_config()` implementation
4. **Implement** field additions and YAML parsing
5. **Verify** all acceptance criteria — especially backward compatibility
6. **Move this file** to `sdd/tasks/completed/`
7. **Update index** → `"done"`

---

## Completion Note

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-06-26
**Notes**: Added oauth2 (Optional[MCPOAuth2Config]) and auth_preset (Optional[str])
fields to MCPClientConfig dataclass. Updated from_yaml_config() to parse both
fields with preset resolution and override merging. Updated get_headers() to skip
auth_credential when oauth2 is set. All 15 tests pass.

**Deviations from spec**: None.
