---
type: Wiki Overview
title: 'TASK-1712: v1.0 Data Models — Core Types & Enums'
id: doc:sdd-tasks-completed-task-1712-a2a-v1-data-models-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This is the foundational task for FEAT-272. All other tasks depend on the
relates_to:
- concept: mod:parrot.a2a.models
  rel: mentions
---

# TASK-1712: v1.0 Data Models — Core Types & Enums

**Feature**: FEAT-272 — A2A Protocol v1.0.0 Compatibility
**Spec**: `sdd/specs/a2a-protocol-compatibility.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This is the foundational task for FEAT-272. All other tasks depend on the
data models being updated to v1.0.0 first. The A2A Protocol v1.0.0
specification changes enum serialization from lowercase (`"submitted"`) to
SCREAMING_SNAKE_CASE with type prefix (`"TASK_STATE_SUBMITTED"`), renames
fields in `Part`, adds fields to `Message` and `AgentSkill`, restructures
`AgentCapabilities`, and introduces several new model types.

Implements spec §2 Data Models and spec §3 Module 1.

---

## Scope

- Update `TaskState` enum values to `SCREAMING_SNAKE_CASE` with `TASK_STATE_` prefix.
  Add `UNSPECIFIED` and `AUTH_REQUIRED` members. Rename `CANCELLED` to `CANCELED`
  (single-L per v1.0). Add `CANCELLED` as a deprecated alias.
- Update `Role` enum values to `ROLE_USER`, `ROLE_AGENT`. Add `ROLE_UNSPECIFIED`.
- Update `Part` dataclass: add `filename: Optional[str]` field. Keep `file_uri`
  and `file_bytes` as internal attributes but update `to_dict()` to emit v1.0
  field names (`url` instead of `fileWithUri`, `raw` instead of `fileWithBytes`).
  Update `from_dict()` to accept both v0.3 and v1.0 formats.
- Update `Message` dataclass: add `extensions: Optional[List[str]]` and
  `reference_task_ids: Optional[List[str]]` fields. Update `to_dict()` /
  `from_dict()`.
- Update `AgentCapabilities`: remove `state_transition_history`. Add
  `extended_agent_card: bool = False` and
  `extensions: List[AgentExtension] = field(default_factory=list)`.
  Update `to_dict()` / `from_dict()`.
- Update `AgentSkill`: add `input_modes: Optional[List[str]]`,
  `output_modes: Optional[List[str]]`,
  `security_requirements: Optional[List[SecurityRequirement]]`.
  Update `to_dict()` / `from_dict()`.
- Create new dataclasses: `AgentInterface`, `AgentProvider`,
  `SendMessageConfiguration`, `TaskPushNotificationConfig`,
  `AuthenticationInfo`, `A2AError`, `SecurityScheme` (and subtypes:
  `APIKeySecurityScheme`, `HTTPAuthSecurityScheme`, `OAuth2SecurityScheme`,
  `OpenIdConnectSecurityScheme`, `MutualTlsSecurityScheme`),
  `SecurityRequirement`, `AgentExtension`, `AgentCardSignature`.
- Create a version-aware serialization helper: `_serialize_enum(enum_val, version)`
  that emits lowercase for v0.3, SCREAMING_SNAKE for v1.0.
- Create a compat deserialization helper: `_deserialize_task_state(value)` that
  accepts both `"submitted"` and `"TASK_STATE_SUBMITTED"`.
- Add `version` parameter to `to_dict()` on `TaskStatus`, `Task`, `Artifact`,
  `Part`, `Message` — default `"1.0"`. When `version="0.3"`, emit old format.

**NOT in scope**:
- AgentCard restructuring (TASK-1713)
- Server-side route changes (TASK-1714/1715)
- Client changes (TASK-1717)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/a2a/models.py` | MODIFY | Update all dataclasses, enums, add new types |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.a2a.models import (
    AgentConfig,       # verified: models.py:11
    TaskState,         # verified: models.py:20
    Role,              # verified: models.py:31
    Part,              # verified: models.py:38
    Message,           # verified: models.py:99
    TaskStatus,        # verified: models.py:172
    Artifact,          # verified: models.py:191
    Task,              # verified: models.py:231
    AgentSkill,        # verified: models.py:282
    AgentCapabilities, # verified: models.py:309
    AgentCard,         # verified: models.py:332
    RegisteredAgent,   # verified: models.py:427
)
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/a2a/models.py

class TaskState(str, Enum):                      # line 20
    SUBMITTED = "submitted"                      # line 22
    WORKING = "working"                          # line 23
    COMPLETED = "completed"                      # line 24
    FAILED = "failed"                            # line 25
    CANCELLED = "cancelled"                      # line 26
    INPUT_REQUIRED = "input_required"            # line 27
    REJECTED = "rejected"                        # line 28

class Role(str, Enum):                           # line 31
    USER = "user"                                # line 33
    AGENT = "agent"                              # line 34

class Part:                                      # line 38
    text: Optional[str] = None                   # line 40
    file_uri: Optional[str] = None               # line 41
    file_bytes: Optional[bytes] = None           # line 42
    file_media_type: Optional[str] = None        # line 43
    data: Optional[Dict[str, Any]] = None        # line 44
    metadata: Optional[Dict[str, Any]] = None    # line 45
    def to_dict(self) -> Dict[str, Any]:         # line 55
    @classmethod
    def from_dict(cls, d: Dict) -> "Part":       # line 81

class Message:                                   # line 99
    message_id: str                              # line 101
    role: Role                                   # line 102
    parts: List[Part]                            # line 103
    context_id: Optional[str] = None             # line 104
    task_id: Optional[str] = None                # line 105
    metadata: Optional[Dict] = None              # line 106
    def to_dict(self) -> Dict[str, Any]:         # line 146
    @classmethod
    def from_dict(cls, d: Dict) -> "Message":    # line 160

class TaskStatus:                                # line 172
    state: TaskState                             # line 174
    message: Optional[Message] = None            # line 175
    timestamp: Optional[str] = None              # line 176
    def to_dict(self) -> Dict[str, Any]:         # line 182

class Artifact:                                  # line 191
    artifact_id: str                             # line 193
    parts: List[Part]                            # line 194
    name: Optional[str] = None                   # line 195
    description: Optional[str] = None            # line 196
    metadata: Optional[Dict] = None              # line 197
    def to_dict(self) -> Dict[str, Any]:         # line 216

class Task:                                      # line 231
    id: str                                      # line 233
    context_id: str                              # line 234
    status: TaskStatus                           # line 235
    artifacts: List[Artifact]                    # line 236
    history: List[Message]                       # line 237
    metadata: Optional[Dict] = None              # line 238
    def to_dict(self) -> Dict[str, Any]:         # line 267

class AgentSkill:                                # line 282
    id: str                                      # line 284
    name: str                                    # line 285
    description: str                             # line 286
    tags: List[str]                              # line 287
    input_schema: Optional[Dict] = None          # line 288
    examples: List[str]                          # line 289
    def to_dict(self) -> Dict[str, Any]:         # line 291

class AgentCapabilities:                         # line 309
    streaming: bool = True                       # line 311
    push_notifications: bool = False             # line 312
    state_transition_history: bool = False       # line 313
    def to_dict(self) -> Dict[str, Any]:         # line 315
    @classmethod
    def from_dict(cls, d: Dict) -> "AgentCapabilities": # line 322
```

### Does NOT Exist

- ~~`TaskState.AUTH_REQUIRED`~~ — must be created
- ~~`TaskState.UNSPECIFIED`~~ — must be created
- ~~`Role.UNSPECIFIED`~~ — must be created
- ~~`Part.filename`~~ — must be added
- ~~`Part.url`~~ — attribute is `file_uri`, not `url`
- ~~`Part.raw`~~ — attribute is `file_bytes`, not `raw`
- ~~`Message.extensions`~~ — must be added
- ~~`Message.reference_task_ids`~~ — must be added
- ~~`AgentCapabilities.extended_agent_card`~~ — must be added
- ~~`AgentCapabilities.extensions`~~ — must be added (currently no such field)
- ~~`AgentSkill.input_modes`~~ — must be added
- ~~`AgentSkill.output_modes`~~ — must be added
- ~~`AgentSkill.security_requirements`~~ — must be added
- ~~`parrot.a2a.models.AgentInterface`~~ — must be created
- ~~`parrot.a2a.models.AgentProvider`~~ — must be created
- ~~`parrot.a2a.models.SendMessageConfiguration`~~ — must be created
- ~~`parrot.a2a.models.TaskPushNotificationConfig`~~ — must be created
- ~~`parrot.a2a.models.AuthenticationInfo`~~ — must be created
- ~~`parrot.a2a.models.A2AError`~~ — must be created
- ~~`parrot.a2a.models.SecurityScheme`~~ — must be created
- ~~`parrot.a2a.models.AgentExtension`~~ — must be created
- ~~`parrot.a2a.models.AgentCardSignature`~~ — must be created
- ~~`parrot.a2a.models.SecurityRequirement`~~ — must be created

---

## Implementation Notes

### Pattern to Follow

All A2A models use `@dataclass` (NOT Pydantic). Continue this pattern:

```python
@dataclass
class AgentInterface:
    """v1.0 AgentCard interface entry."""
    url: str
    protocol_binding: str
    protocol_version: str
    tenant: Optional[str] = None

    def to_dict(self, version: str = "1.0") -> Dict[str, Any]:
        return {
            "url": self.url,
            "protocolBinding": self.protocol_binding,
            "protocolVersion": self.protocol_version,
            **({"tenant": self.tenant} if self.tenant else {}),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentInterface":
        return cls(
            url=data["url"],
            protocol_binding=data["protocolBinding"],
            protocol_version=data.get("protocolVersion", "1.0"),
            tenant=data.get("tenant"),
        )
```

### Enum Backward Compatibility Pattern

```python
# Build a lookup table for compat deserialization
_TASK_STATE_COMPAT = {
    "submitted": TaskState.SUBMITTED,
    "working": TaskState.WORKING,
    # ...v0.3 lowercase values
    "TASK_STATE_SUBMITTED": TaskState.SUBMITTED,
    "TASK_STATE_WORKING": TaskState.WORKING,
    # ...v1.0 SCREAMING_SNAKE values
    "cancelled": TaskState.CANCELED,  # v0.3 double-L maps to v1.0 single-L
}

def parse_task_state(value: str) -> TaskState:
    """Parse a TaskState from either v0.3 or v1.0 format."""
    try:
        return _TASK_STATE_COMPAT[value]
    except KeyError:
        return TaskState(value)  # fallback to enum lookup
```

### Key Constraints

- `CANCELLED` must remain as a deprecated alias for `CANCELED` so existing
  code referencing `TaskState.CANCELLED` continues to work. Python `Enum`
  supports aliases natively when two members share the same value.
- `to_dict()` methods gain a `version: str = "1.0"` parameter. Default to
  v1.0 output. Pass `version="0.3"` for legacy format.
- `from_dict()` methods must accept BOTH formats without requiring a version hint.
- camelCase field names in JSON are already the convention — maintain that.

---

## Acceptance Criteria

- [ ] `TaskState` enum has `UNSPECIFIED`, `SUBMITTED`, `WORKING`, `COMPLETED`,
      `FAILED`, `CANCELED`, `INPUT_REQUIRED`, `REJECTED`, `AUTH_REQUIRED` members
      with `TASK_STATE_*` values
- [ ] `TaskState.CANCELLED` is a deprecated alias for `TaskState.CANCELED`
- [ ] `Role` enum has `UNSPECIFIED`, `USER`, `AGENT` with `ROLE_*` values
- [ ] `Part` has `filename` field; `to_dict()` emits v1.0 Part format
- [ ] `Message` has `extensions` and `reference_task_ids` fields
- [ ] `AgentCapabilities` has `extended_agent_card` and `extensions` fields;
      `state_transition_history` removed
- [ ] `AgentSkill` has `input_modes`, `output_modes`, `security_requirements`
- [ ] All new dataclasses created with `to_dict()` and `from_dict()` methods
- [ ] Compat deserialization functions accept both v0.3 and v1.0 enum values
- [ ] `to_dict(version="0.3")` emits lowercase enum values
- [ ] `to_dict(version="1.0")` (default) emits SCREAMING_SNAKE enum values
- [ ] Existing imports from `parrot.a2a.models` still work
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/a2a/models.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/test_a2a_v1_models.py
import pytest
from parrot.a2a.models import (
    TaskState, Role, Part, Message, Artifact, Task, TaskStatus,
    AgentSkill, AgentCapabilities, AgentInterface, AgentProvider,
    SendMessageConfiguration, TaskPushNotificationConfig,
    AuthenticationInfo, A2AError, parse_task_state, parse_role,
)


class TestTaskStateV1:
    def test_v1_values(self):
        assert TaskState.SUBMITTED.value == "TASK_STATE_SUBMITTED"
        assert TaskState.AUTH_REQUIRED.value == "TASK_STATE_AUTH_REQUIRED"

    def test_cancelled_alias(self):
        assert TaskState.CANCELLED is TaskState.CANCELED

    def test_compat_parse(self):
        assert parse_task_state("submitted") == TaskState.SUBMITTED
        assert parse_task_state("TASK_STATE_SUBMITTED") == TaskState.SUBMITTED
        assert parse_task_state("cancelled") == TaskState.CANCELED


class TestRoleV1:
    def test_v1_values(self):
        assert Role.USER.value == "ROLE_USER"
        assert Role.UNSPECIFIED.value == "ROLE_UNSPECIFIED"


class TestPartV1:
    def test_to_dict_v1_text(self):
        p = Part(text="hello")
        d = p.to_dict(version="1.0")
        assert d["text"] == "hello"

    def test_to_dict_v1_file(self):
        p = Part(file_uri="https://example.com/f.pdf", file_media_type="application/pdf")
        d = p.to_dict(version="1.0")
        assert "url" in d

    def test_from_dict_v03_compat(self):
        d = {"kind": "file", "file": {"fileWithUri": "https://x.com/f.pdf"}}
        p = Part.from_dict(d)
        assert p.file_uri == "https://x.com/f.pdf"

    def test_filename_field(self):
        p = Part(text="hello", filename="doc.txt")
        d = p.to_dict(version="1.0")
        assert d.get("filename") == "doc.txt"


class TestMessageV1:
    def test_extensions_field(self):
        m = Message.user("hello", extensions=["ext1"])
        d = m.to_dict(version="1.0")
        assert d["extensions"] == ["ext1"]

    def test_reference_task_ids(self):
        m = Message.user("hello", reference_task_ids=["task-1"])
        d = m.to_dict(version="1.0")
        assert d["referenceTaskIds"] == ["task-1"]


class TestAgentCapabilitiesV1:
    def test_extended_agent_card(self):
        c = AgentCapabilities(extended_agent_card=True)
        d = c.to_dict()
        assert d["extendedAgentCard"] is True

    def test_no_state_transition_history(self):
        c = AgentCapabilities()
        d = c.to_dict()
        assert "stateTransitionHistory" not in d
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/a2a-protocol-compatibility.spec.md` for full context
2. **Check dependencies** — none for this task
3. **Verify the Codebase Contract** — read `packages/ai-parrot/src/parrot/a2a/models.py`
   and confirm all signatures match before modifying
4. **Update status** in per-spec index → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Run tests**: `pytest packages/ai-parrot/tests/test_a2a_v1_models.py -v`
7. **Verify** all acceptance criteria are met
8. **Move this file** to `sdd/tasks/completed/TASK-1712-a2a-v1-data-models.md`
9. **Update index** → `"done"`

---

## Completion Note

**Completed by**: sdd-worker (Claude Opus 4.8)
**Date**: 2026-07-10
**Notes**:
- Rewrote `models.py` with v1.0 core types: `TaskState`/`Role` now use
  `SCREAMING_SNAKE_CASE` ProtoJSON values. Added `UNSPECIFIED`, `AUTH_REQUIRED`;
  renamed `CANCELLED` → `CANCELED` with `CANCELLED` retained as a same-value
  deprecated alias (`TaskState.CANCELLED is TaskState.CANCELED`).
- Added compat helpers `parse_task_state`, `parse_role`, `serialize_task_state`,
  `serialize_role` that map both v0.3 lowercase and v1.0 SCREAMING_SNAKE.
- `Part`: added `filename`; `to_dict(version=)` emits v1.0 top-level `url`/`raw`
  or v0.3 nested `fileWithUri`/`fileWithBytes`; `from_dict` accepts both.
- `Message`: added `extensions`, `reference_task_ids` (v1.0-only in output).
- `TaskStatus`, `Task`, `Artifact`, `Part`, `Message` all gained
  `to_dict(version="1.0")` with v0.3 fallback.
- `AgentCapabilities`: removed `state_transition_history`; added
  `extended_agent_card` and `extensions`.
- `AgentSkill`: added `input_modes`, `output_modes`, `security_requirements`
  and a `from_dict`.
- New dataclasses: `AgentInterface`, `AgentProvider`, `SendMessageConfiguration`,
  `TaskPushNotificationConfig`, `AuthenticationInfo`, `A2AError`,
  `SecurityScheme` (+ `APIKeySecurityScheme`, `HTTPAuthSecurityScheme`,
  `OAuth2SecurityScheme`, `OpenIdConnectSecurityScheme`,
  `MutualTlsSecurityScheme`), `SecurityRequirement`, `AgentExtension`,
  `AgentCardSignature`.
- 30 new unit tests in `test_a2a_v1_models.py` pass; ruff clean; existing
  ai-parrot a2a tests still green.
**Deviations from spec**: `AgentCard` was intentionally kept in its flat v0.3
shape here (the restructure is TASK-1713's scope, per this task's explicit
"NOT in scope"). `AgentCard.from_dict` now delegates skill parsing to the new
`AgentSkill.from_dict`.
