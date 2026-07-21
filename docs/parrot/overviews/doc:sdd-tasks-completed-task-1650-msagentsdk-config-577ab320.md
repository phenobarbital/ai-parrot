---
type: Wiki Overview
title: 'TASK-1650: Config Extension — oauth_connections and obo_scopes fields'
id: doc:sdd-tasks-completed-task-1650-msagentsdk-config-extension-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements spec Module **1**. `MSAgentSDKConfig` in `models.py` currently
  has
---

# TASK-1650: Config Extension — oauth_connections and obo_scopes fields

**Feature**: FEAT-261 — Per-User Auth & OBO for MS Agents SDK Integration
**Spec**: `sdd/specs/auth-obo-msagentsdk.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (1-2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements spec Module **1**. `MSAgentSDKConfig` in `models.py` currently has
no fields for OAuth connections or OBO scopes. This task adds them with env
var fallback, enabling subsequent modules to reference the connection map.

## Scope

Add `oauth_connections: Dict[str, str]` and `obo_scopes: Dict[str, List[str]]`
to `MSAgentSDKConfig`. Update `__post_init__()` for env var fallback. Update
`from_dict()` classmethod to parse both fields from YAML data.

## Files to Create/Modify

- `packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/models.py` — MODIFY

## Implementation Notes

- Add `oauth_connections: Dict[str, str] = field(default_factory=dict)` to the
  dataclass. Maps tool name → Azure Bot OAuth connection name
  (e.g. `{"o365": "graph_sso", "jira": "jira_oauth"}`).
- Add `obo_scopes: Dict[str, List[str]] = field(default_factory=dict)` to the
  dataclass. Maps tool name → OBO target scopes
  (e.g. `{"o365": ["https://graph.microsoft.com/.default"]}`).
- In `__post_init__()`, add JSON env var fallback:
  ```python
  if not self.oauth_connections:
      raw = config.get(f"{prefix}_OAUTH_CONNECTIONS")
      if raw:
          import json
          self.oauth_connections = json.loads(raw)
  if not self.obo_scopes:
      raw = config.get(f"{prefix}_OBO_SCOPES")
      if raw:
          import json
          self.obo_scopes = json.loads(raw)
  ```
- In `from_dict()`, pass both new fields:
  ```python
  oauth_connections=data.get("oauth_connections", {}),
  obo_scopes=data.get("obo_scopes", {}),
  ```
- Existing fields must remain unchanged — pure additive change.
- The `dataclass` uses `field(default_factory=dict)` so the `import dataclasses`
  is already present (check the existing import for `dataclass` — models.py uses
  `@dataclass` so `from dataclasses import dataclass, field` is needed).

## Codebase Contract

### Verified Imports
```python
from dataclasses import dataclass          # verified: models.py:4
from typing import Dict, Any, Optional     # verified: models.py:5
from navconfig import config               # verified: models.py:6
```

### Existing Signatures
```python
@dataclass
class MSAgentSDKConfig:                    # models.py:10
    name: str
    chatbot_id: str
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    tenant_id: Optional[str] = None
    anonymous_auth: bool = False
    api_key: Optional[str] = None
    api_key_header: str = "x-api-key"
    app_type: str = "SingleTenant"
    authority: Optional[str] = None
    kind: str = "msagentsdk"
    welcome_message: Optional[str] = None
    system_prompt_override: Optional[str] = None
    endpoint: Optional[str] = None

    def __post_init__(self) -> None:       # models.py:73

    @classmethod
    def from_dict(cls, name: str, data: Dict[str, Any]) -> "MSAgentSDKConfig":  # models.py:105
```

### Does NOT Exist
- `MSAgentSDKConfig.oauth_connections` — does not exist yet; being added
- `MSAgentSDKConfig.obo_scopes` — does not exist yet; being added

## Acceptance Criteria

- [ ] `MSAgentSDKConfig` has `oauth_connections: Dict[str, str]` field with
      default empty dict.
- [ ] `MSAgentSDKConfig` has `obo_scopes: Dict[str, List[str]]` field with
      default empty dict.
- [ ] `__post_init__()` reads `{PREFIX}_OAUTH_CONNECTIONS` env var (JSON string)
      when `oauth_connections` is not set.
- [ ] `__post_init__()` reads `{PREFIX}_OBO_SCOPES` env var (JSON string) when
      `obo_scopes` is not set.
- [ ] `from_dict()` passes `oauth_connections` and `obo_scopes` from the data
      dict.
- [ ] Backward compatibility: existing code that instantiates `MSAgentSDKConfig`
      without the new fields still works (empty defaults).
- [ ] `pytest tests/integrations/test_msagentsdk/ -v` (new tests in TASK-1658)

## Test Specification

```python
def test_config_oauth_connections():
    cfg = MSAgentSDKConfig(
        name="TestBot",
        chatbot_id="test_agent",
        anonymous_auth=True,
        oauth_connections={"o365": "graph_sso", "jira": "jira_oauth"},
        obo_scopes={"o365": ["https://graph.microsoft.com/.default"]},
    )
    assert cfg.oauth_connections == {"o365": "graph_sso", "jira": "jira_oauth"}
    assert cfg.obo_scopes == {"o365": ["https://graph.microsoft.com/.default"]}


def test_config_oauth_connections_empty():
    cfg = MSAgentSDKConfig(name="Bot", chatbot_id="bot", anonymous_auth=True)
    assert cfg.oauth_connections == {}
    assert cfg.obo_scopes == {}
```

### Completion Note

Implemented as specified. Added `oauth_connections: Dict[str, str]` and
`obo_scopes: Dict[str, List[str]]` to `MSAgentSDKConfig` with
`field(default_factory=dict)` defaults. Updated `__post_init__()` with
JSON env var fallback for `{PREFIX}_OAUTH_CONNECTIONS` and
`{PREFIX}_OBO_SCOPES`. Updated `from_dict()` to pass both new fields.
Changed `from dataclasses import dataclass` to
`from dataclasses import dataclass, field` and added `List` to typing imports.
All existing fields unchanged. Backward compatible.
