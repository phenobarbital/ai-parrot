---
type: Wiki Overview
title: 'TASK-1713: AgentCard v1.0 Structure'
id: doc:sdd-tasks-completed-task-1713-a2a-v1-agent-card-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The A2A v1.0.0 spec replaces the flat `url` + `preferredTransport` AgentCard
relates_to:
- concept: mod:parrot.a2a
  rel: mentions
- concept: mod:parrot.a2a.models
  rel: mentions
---

# TASK-1713: AgentCard v1.0 Structure

**Feature**: FEAT-272 — A2A Protocol v1.0.0 Compatibility
**Spec**: `sdd/specs/a2a-protocol-compatibility.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1712
**Assigned-to**: unassigned

---

## Context

The A2A v1.0.0 spec replaces the flat `url` + `preferredTransport` AgentCard
shape (used by v0.3/Copilot Studio) with a structured `supportedInterfaces`
array of `AgentInterface` objects. The AgentCard also gains `provider`,
`documentationUrl`, `securitySchemes`, `securityRequirements`, and `signatures`
fields.

This task restructures the `AgentCard` dataclass and its serialization to
produce v1.0.0-compliant cards while preserving v0.3 output via a `version`
parameter.

Implements spec §3 Module 2.

---

## Scope

- Restructure `AgentCard` dataclass:
  - Replace `url: Optional[str]` and `preferred_transport: str` with
    `supported_interfaces: List[AgentInterface]`.
  - Remove `protocol_version: str` (moved into each `AgentInterface`).
  - Add `provider: Optional[AgentProvider]`.
  - Add `documentation_url: Optional[str]`.
  - Add `security_schemes: Optional[Dict[str, SecurityScheme]]`.
  - Add `security_requirements: Optional[List[SecurityRequirement]]`.
  - Add `signatures: Optional[List[AgentCardSignature]]`.
- Implement `AgentCard.to_dict(version="1.0")`:
  - v1.0: emit `supportedInterfaces` array, `provider`, `documentationUrl`,
    `securitySchemes`, `securityRequirements`. Omit `url`, `preferredTransport`.
  - v0.3: emit flat `url` (from `supported_interfaces[0].url`),
    `preferredTransport` (from `supported_interfaces[0].protocol_binding`),
    `protocolVersion` as `"0.3.0"`. Omit `supportedInterfaces`.
- Implement `AgentCard.from_dict()` that auto-detects format:
  - Presence of `supportedInterfaces` → v1.0 parsing.
  - Presence of flat `url` → v0.3 parsing (build a single `AgentInterface`).
- Update `A2AServer.get_agent_card()` in server.py to construct
  `supported_interfaces` from `self._url` and `self.base_path`.
- Update `__init__.py` exports to include new types.

**NOT in scope**:
- Server route changes (TASK-1714)
- Client changes (TASK-1717)
- Core enum/Part/Message model changes (TASK-1712)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/a2a/models.py` | MODIFY | Restructure AgentCard |
| `packages/ai-parrot-server/src/parrot/a2a/server.py` | MODIFY | Update get_agent_card() to build supported_interfaces |
| `packages/ai-parrot/src/parrot/a2a/__init__.py` | MODIFY | Export new types |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.a2a.models import AgentCard          # verified: models.py:332
from parrot.a2a.models import AgentCapabilities   # verified: models.py:309
from parrot.a2a.models import AgentSkill          # verified: models.py:282
# After TASK-1712:
from parrot.a2a.models import AgentInterface      # created in TASK-1712
from parrot.a2a.models import AgentProvider       # created in TASK-1712
from parrot.a2a.models import SecurityScheme      # created in TASK-1712
from parrot.a2a.models import SecurityRequirement # created in TASK-1712
from parrot.a2a.models import AgentCardSignature  # created in TASK-1712
from parrot.a2a.models import AgentExtension      # created in TASK-1712
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/a2a/models.py

class AgentCard:                                 # line 332
    name: str                                    # line 334
    description: str                             # line 335
    version: str                                 # line 336
    skills: List[AgentSkill]                     # line 337
    url: Optional[str] = None                    # line 338
    capabilities: AgentCapabilities              # line 339
    default_input_modes: List[str]               # line 340
    default_output_modes: List[str]              # line 341
    protocol_version: str = "0.3.0"             # line 345
    preferred_transport: str = "JSONRPC"         # line 349
    icon_url: Optional[str] = None               # line 350
    tags: List[str]                              # line 351
    def to_dict(self) -> Dict[str, Any]:         # line 353
    @classmethod
    def from_dict(cls, d: Dict) -> "AgentCard":  # line 388

# packages/ai-parrot-server/src/parrot/a2a/server.py

class A2AServer:                                 # line 50
    def get_agent_card(self) -> AgentCard:        # line 207
    # Constructs AgentCard at line 236-244:
    #   self._agent_card = AgentCard(
    #       name=self.agent.name,
    #       description=description,
    #       version=self.version,
    #       url=self._url,
    #       skills=skills,
    #       capabilities=self.capabilities,
    #       tags=self.tags or getattr(self.agent, 'tags', []),
    #   )
```

### Does NOT Exist

- ~~`AgentCard.supported_interfaces`~~ — must be added (replacing `url`)
- ~~`AgentCard.provider`~~ — must be added
- ~~`AgentCard.documentation_url`~~ — must be added
- ~~`AgentCard.security_schemes`~~ — must be added
- ~~`AgentCard.security_requirements`~~ — must be added
- ~~`AgentCard.signatures`~~ — must be added

---

## Implementation Notes

### Key Constraints

- The `url` attribute on AgentCard is used by many consumers: `A2AClient`,
  `A2AMeshDiscovery`, `A2AProxyRouter`, `A2AAgentConnection`. After restructuring,
  add a `@property url` that returns `supported_interfaces[0].url` for backward
  compat so existing code doesn't break. Similarly, add a `@property
  preferred_transport` that returns `supported_interfaces[0].protocol_binding`.
- `A2AServer.get_agent_card()` constructs the card at line 236. Update it to
  build `supported_interfaces=[AgentInterface(url=self._url, ...)]` instead
  of setting `url=self._url`.
- The v0.3 `to_dict()` output must match what Microsoft Copilot Studio's
  `a2a-dotnet` parser expects: flat `url`, `preferredTransport`, and
  `protocolVersion` fields (see existing comments at lines 356-381).

### References in Codebase

- `packages/ai-parrot/src/parrot/a2a/models.py` — AgentCard at line 332
- `packages/ai-parrot-server/src/parrot/a2a/server.py` — get_agent_card() at line 207

---

## Acceptance Criteria

- [ ] `AgentCard` has `supported_interfaces: List[AgentInterface]` field
- [ ] `AgentCard.url` property returns first interface URL (backward compat)
- [ ] `AgentCard.to_dict(version="1.0")` emits `supportedInterfaces` array
- [ ] `AgentCard.to_dict(version="0.3")` emits flat `url` + `preferredTransport`
- [ ] `AgentCard.from_dict()` auto-detects v1.0 vs v0.3 format
- [ ] `AgentCard` has `provider`, `documentation_url`, `security_schemes`,
      `security_requirements`, `signatures` fields
- [ ] `A2AServer.get_agent_card()` constructs `supported_interfaces`
- [ ] New types exported from `parrot.a2a.__init__`
- [ ] No linting errors

---

## Test Specification

```python
# packages/ai-parrot/tests/test_a2a_v1_models.py (append to existing)

class TestAgentCardV1:
    def test_to_dict_v1_supported_interfaces(self):
        card = AgentCard(
            name="Test", description="Test agent", version="1.0",
            skills=[], supported_interfaces=[
                AgentInterface(url="https://a.com/a2a", protocol_binding="JSONRPC",
                               protocol_version="1.0")
            ],
        )
        d = card.to_dict(version="1.0")
        assert "supportedInterfaces" in d
        assert d["supportedInterfaces"][0]["url"] == "https://a.com/a2a"
        assert "url" not in d  # flat url NOT in v1.0

    def test_to_dict_v03_flat_url(self):
        card = AgentCard(
            name="Test", description="Test", version="1.0",
            skills=[], supported_interfaces=[
                AgentInterface(url="https://a.com/a2a", protocol_binding="JSONRPC",
                               protocol_version="1.0")
            ],
        )
        d = card.to_dict(version="0.3")
        assert d["url"] == "https://a.com/a2a"
        assert d["preferredTransport"] == "JSONRPC"
        assert "supportedInterfaces" not in d

    def test_from_dict_v1(self):
        d = {
            "name": "Test", "description": "T", "version": "1.0",
            "supportedInterfaces": [{"url": "https://a.com", "protocolBinding": "JSONRPC", "protocolVersion": "1.0"}],
            "capabilities": {"streaming": True},
            "defaultInputModes": ["text/plain"],
            "defaultOutputModes": ["text/plain"],
            "skills": [],
        }
        card = AgentCard.from_dict(d)
        assert len(card.supported_interfaces) == 1
        assert card.url == "https://a.com"

    def test_from_dict_v03_compat(self):
        d = {
            "name": "Test", "description": "T", "version": "1.0",
            "url": "https://a.com", "preferredTransport": "JSONRPC",
            "protocolVersion": "0.3.0",
            "capabilities": {"streaming": True},
            "defaultInputModes": ["text/plain"],
            "defaultOutputModes": ["text/plain"],
            "skills": [],
        }
        card = AgentCard.from_dict(d)
        assert card.url == "https://a.com"

    def test_provider_field(self):
        card = AgentCard(
            name="Test", description="T", version="1.0", skills=[],
            supported_interfaces=[AgentInterface(url="https://a.com", protocol_binding="JSONRPC", protocol_version="1.0")],
            provider=AgentProvider(url="https://example.com", organization="Acme"),
        )
        d = card.to_dict(version="1.0")
        assert d["provider"]["organization"] == "Acme"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/a2a-protocol-compatibility.spec.md`
2. **Check dependencies** — verify TASK-1712 is in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — read `models.py` (it will have changed from TASK-1712)
4. **Implement** the AgentCard restructuring
5. **Run tests**: `pytest packages/ai-parrot/tests/test_a2a_v1_models.py -v`
6. **Move this file** to `sdd/tasks/completed/`
7. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (Claude Opus 4.8)
**Date**: 2026-07-10
**Notes**:
- Restructured `AgentCard`: replaced flat `url`/`preferred_transport`/
  `protocol_version` fields with `supported_interfaces: List[AgentInterface]`.
  Added `provider`, `documentation_url`, `security_schemes`,
  `security_requirements`, `signatures`.
- Added read-only backward-compat properties `url`, `preferred_transport`,
  `protocol_version` returning the first interface's values so existing
  consumers (client/mesh/router) keep working.
- `to_dict(version="1.0")` emits `supportedInterfaces` + v1.0 fields;
  `to_dict(version="0.3")` emits the flat `url`+`preferredTransport` shape.
  `from_dict()` auto-detects `supportedInterfaces` (v1.0) vs flat `url` (v0.3)
  and also folds in v0.3 `additionalInterfaces`.
- `A2AServer.get_agent_card()` now builds a single `AgentInterface` from
  `self._url`.
- Exported all new v1.0 model types from `parrot.a2a.__init__`.
- 35 model unit tests pass (incl. 6 new `TestAgentCardV1`); ruff clean.
**Deviations from spec**: none. (Server-side default serialization still
version-unaware until TASK-1714 wires the `A2A-Version` header; the e2e v0.3
regression is resolved there.)
