# TASK-2478: Swarm Config & Event Models

**Feature**: FEAT-463 — Matrix Agents Swarm
**Spec**: `sdd/specs/matrix-agents-swarm.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §2 Data Models / §3 Module 1. Every later task imports these models. Adds the
channel/tunnel/space configuration to `MatrixCrewConfig`, the new `m.parrot.*` event
types and their Pydantic contents, and the `AgentAnswer` envelope returned by `ask_agent`.
Backward compatibility with FEAT-044/195 YAML is mandatory (all new fields default).

---

## Scope

- Add `ChannelConfig`, `TunnelConfig`, `SpaceConfig` to `crew/config.py`; extend
  `CollaborativeConfig` (`max_concurrent_sessions`, `cooldown_seconds`) and
  `MatrixCrewConfig` (`channels`, `tunnels`, `space`, `human_namespace_patterns`).
- Validators on `MatrixCrewConfig`: channel names unique; every `ChannelConfig.agents`
  entry is a key of `agents` (only when `agents` non-empty, same rule as
  `validate_summarizer_agent`); any channel with `answer_policy == "swarm"` requires
  `collaborative` to be set.
- Add to `events.py`: `ParrotEventType.CHANNEL/TUNNEL/FEEDBACK` (+ `*_EVENT` mautrix
  objects, STATE class for CHANNEL/TUNNEL), `AgentAnswer`, `FeedbackEventContent`,
  `ChannelStateContent`, `TunnelStateContent`; extend `TaskEventContent` with
  `correlation_id`, `hops`, `origin_session`, `expected_schema`.
- `AgentAnswer.validate_against(schema)` helper using `jsonschema` **only if already
  installed** — otherwise implement a minimal required/type check; do NOT add a dependency.
- Export new names from `crew/__init__.py` and the lazy map in `matrix/__init__.py`.
- Tests.

**NOT in scope**: any room I/O, toolkit, transport changes (TASK-2479+).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/matrix/crew/config.py` | MODIFY | new models + fields + validators |
| `packages/ai-parrot-integrations/src/parrot/integrations/matrix/events.py` | MODIFY | new event types + contents + `AgentAnswer` |
| `packages/ai-parrot-integrations/src/parrot/integrations/matrix/crew/__init__.py` | MODIFY | export `ChannelConfig`, `TunnelConfig`, `SpaceConfig` |
| `packages/ai-parrot-integrations/src/parrot/integrations/matrix/__init__.py` | MODIFY | lazy map: `AgentAnswer`, `FeedbackEventContent`, `ChannelStateContent`, `TunnelStateContent` → `.events` |
| `packages/ai-parrot-integrations/tests/test_matrix_swarm_config.py` | CREATE | config tests |
| `packages/ai-parrot-integrations/tests/test_matrix_swarm_events.py` | CREATE | event model tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.integrations.matrix.crew.config import (      # crew/config.py
    CollaborativeConfig, MatrixCrewAgentEntry, MatrixCrewConfig, _walk_and_substitute)
from parrot.integrations.matrix.events import (            # events.py
    ParrotEventType, TaskEventContent, ResultEventContent, StatusEventContent, AgentCardEventContent)
from pydantic import BaseModel, Field, model_validator
```

### Existing Signatures to Use
```python
# crew/config.py
class MatrixCrewAgentEntry(BaseModel)           # :57  chatbot_id, display_name, mxid_localpart, ...
class CollaborativeConfig(BaseModel)            # :91  command_prefix="!investigate", max_rounds=1 (1..10),
                                                #      agent_timeout=120.0, session_timeout=600.0, summarizer_agent,
                                                #      session_verbosity: Literal["full","minimal","silent"], include_chat_context=True
class MatrixCrewConfig(BaseModel)               # :139 ... agents: Dict[str, MatrixCrewAgentEntry], collaborative: Optional[CollaborativeConfig]
    @model_validator(mode="after")
    def validate_summarizer_agent(self) -> "MatrixCrewConfig"   # :193 — pattern: only enforce when self.agents is non-empty
    @classmethod
    def from_yaml(cls, path: str) -> "MatrixCrewConfig"        # :217 — yaml.safe_load + _walk_and_substitute

# events.py
class ParrotEventType:                          # :21
    AGENT_CARD = "m.parrot.agent_card"          # :25
    TASK = "m.parrot.task"; RESULT = "m.parrot.result"; STATUS = "m.parrot.status"   # :28-30
    # :35-47: try: from mautrix.types import EventType; AGENT_CARD_EVENT = EventType.find(AGENT_CARD, t_class=EventType.Class.STATE) ...
    #         except ImportError: *_EVENT = None   (:52-55)
class TaskEventContent(BaseModel)               # :87  task_id: str, context_id: Optional[str], content: str,
                                                #      metadata: Dict[str, Any], target_agent: Optional[str], skill_id: Optional[str]
class ResultEventContent(BaseModel)             # :103 task_id, context_id, content: str, artifacts: List[Dict], metadata, success=True, error
```

### Does NOT Exist
- ~~`ChannelConfig`, `TunnelConfig`, `SpaceConfig`, `AgentAnswer`, `FeedbackEventContent`~~ — you create them.
- ~~`ParrotEventType.CHANNEL / TUNNEL / FEEDBACK`~~ — you add them.
- ~~`jsonschema` as a declared dependency~~ — check `importlib.util.find_spec("jsonschema")`; do not add to pyproject.
- ~~`answer_policy: "router"`~~ — must be rejected by the `Literal`.

---

## Implementation Notes

### Skeleton (normative field names — see spec §2 Data Models)
```python
# crew/config.py (additions)
from typing import List, Literal, Optional

class ChannelConfig(BaseModel):
    """One declared agent channel (Matrix room) — spec §2."""
    name: str = Field(..., pattern=r"^[a-z0-9][a-z0-9_-]*$", description="alias localpart")
    visibility: Literal["public", "private"] = "public"
    agents: List[str] = Field(default_factory=list)
    answer_policy: Literal["mention", "swarm", "silent"] = "mention"
    room_id: Optional[str] = None
    topic: Optional[str] = None

class TunnelConfig(BaseModel):
    enabled: bool = True
    ttl_minutes: int = Field(default=120, ge=0)          # 0 = keep forever
    max_hops: int = Field(default=3, ge=1, le=10)
    default_timeout: float = Field(default=60.0, gt=0)
    echo_summary_to_channel: bool = True

class SpaceConfig(BaseModel):
    enabled: bool = False
    name: str = "Parrot Swarm"
    room_id: Optional[str] = None

# CollaborativeConfig additions
    max_concurrent_sessions: int = Field(default=3, ge=1, le=20)
    cooldown_seconds: float = Field(default=10.0, ge=0)

# MatrixCrewConfig additions
    channels: List[ChannelConfig] = Field(default_factory=list)
    tunnels: TunnelConfig = Field(default_factory=TunnelConfig)
    space: SpaceConfig = Field(default_factory=SpaceConfig)
    human_namespace_patterns: List[str] = Field(
        default_factory=lambda: [r"^@signal_", r"^@slack_", r"^@discord_"])

    @model_validator(mode="after")
    def validate_channels(self) -> "MatrixCrewConfig":
        names = [c.name for c in self.channels]
        if len(names) != len(set(names)):
            raise ValueError(f"duplicate channel names: {names}")
        for ch in self.channels:
            if self.agents:
                unknown = [a for a in ch.agents if a not in self.agents]
                if unknown:
                    raise ValueError(f"channel '{ch.name}' references unknown agents {unknown}")
            if ch.answer_policy == "swarm" and self.collaborative is None:
                raise ValueError(f"channel '{ch.name}' uses answer_policy=swarm but 'collaborative' is not configured")
        return self

    def channel(self, name: str) -> Optional[ChannelConfig]:
        return next((c for c in self.channels if c.name == name), None)
```

```python
# events.py (additions)
class ParrotEventType:
    CHANNEL = "m.parrot.channel"     # state event, state_key ""
    TUNNEL = "m.parrot.tunnel"       # state event, state_key ""
    FEEDBACK = "m.parrot.feedback"   # message event
    # inside the existing try-block: CHANNEL_EVENT / TUNNEL_EVENT with t_class=EventType.Class.STATE,
    # FEEDBACK_EVENT with t_class=EventType.Class.MESSAGE; None in the except branch.

class TaskEventContent(BaseModel):   # add:
    correlation_id: Optional[str] = None
    hops: int = Field(default=0, ge=0)
    origin_session: Optional[str] = None
    expected_schema: Optional[Dict[str, Any]] = None

class AgentAnswer(BaseModel):
    answer: Any
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    sources: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def validate_against(self, schema: Optional[Dict[str, Any]]) -> None:
        """Raise ValueError when ``answer`` does not satisfy ``schema`` (JSON Schema)."""
        if not schema:
            return
        if importlib.util.find_spec("jsonschema"):
            import jsonschema
            try:
                jsonschema.validate(self.answer, schema)
            except jsonschema.ValidationError as exc:
                raise ValueError(str(exc)) from exc
            return
        # minimal fallback: type + required keys
        ...

    @classmethod
    def from_text(cls, text: str) -> "AgentAnswer":
        """Parse an LLM reply: JSON object with 'answer' key → model; otherwise wrap raw text."""

class FeedbackEventContent(BaseModel):
    correlation_id: str; about_event_id: str; from_agent: str; to_agent: str
    rating: int = Field(..., ge=-1, le=5); comment: Optional[str] = None

class ChannelStateContent(BaseModel):
    name: str; visibility: str; answer_policy: str; agents: List[str]; version: int = 1

class TunnelStateContent(BaseModel):
    agents: List[str]; created_at: datetime; ttl_minutes: int; origin_session: Optional[str] = None
```

### Key Constraints
- Keep the module importable without mautrix (mirror the existing try/except at `events.py:35-55`).
- `from_yaml` must load `examples/matrix_crew/matrix_crew.yaml` and `collaborative_crew.yaml` unchanged.

---

## Acceptance Criteria

- [ ] `pytest packages/ai-parrot-integrations/tests/test_matrix_swarm_config.py packages/ai-parrot-integrations/tests/test_matrix_swarm_events.py -v` passes
- [ ] Existing `test_matrix_collaborative_config.py`, `test_matrix_crew.py` still pass
- [ ] `answer_policy="router"` raises `ValidationError`
- [ ] `from parrot.integrations.matrix import AgentAnswer, FeedbackEventContent` works (lazy map)
- [ ] `ruff check packages/ai-parrot-integrations/src/parrot/integrations/matrix`

---

## Test Specification

```python
# tests/test_matrix_swarm_config.py
import pytest
from pydantic import ValidationError
from parrot.integrations.matrix.crew.config import (
    ChannelConfig, CollaborativeConfig, MatrixCrewAgentEntry, MatrixCrewConfig, TunnelConfig)

BASE = dict(homeserver_url="http://hs", server_name="parrot.local", as_token="a", hs_token="h",
            bot_mxid="@parrot:parrot.local", general_room_id="!gen:parrot.local")
AGENTS = {"analyst": MatrixCrewAgentEntry(chatbot_id="analyst", display_name="Analyst", mxid_localpart="parrot-analyst")}

def test_defaults_backward_compat():
    cfg = MatrixCrewConfig(**BASE, agents=AGENTS)
    assert cfg.channels == [] and cfg.tunnels.ttl_minutes == 120 and cfg.space.enabled is False
    assert cfg.human_namespace_patterns[0].startswith("^@signal_")

def test_channel_unknown_agent():
    with pytest.raises(ValidationError, match="unknown agents"):
        MatrixCrewConfig(**BASE, agents=AGENTS, channels=[ChannelConfig(name="general", agents=["ghost"])])

def test_swarm_requires_collaborative():
    with pytest.raises(ValidationError, match="collaborative"):
        MatrixCrewConfig(**BASE, agents=AGENTS, channels=[ChannelConfig(name="g", agents=["analyst"], answer_policy="swarm")])

def test_router_policy_rejected():
    with pytest.raises(ValidationError):
        ChannelConfig(name="g", answer_policy="router")

def test_duplicate_channel_names():
    with pytest.raises(ValidationError, match="duplicate"):
        MatrixCrewConfig(**BASE, channels=[ChannelConfig(name="a"), ChannelConfig(name="a")])

def test_examples_still_load():
    for f in ("examples/matrix_crew/matrix_crew.yaml", "examples/matrix_crew/collaborative_crew.yaml"):
        assert MatrixCrewConfig.from_yaml(f)   # env vars substituted to "" is fine

# tests/test_matrix_swarm_events.py
from parrot.integrations.matrix.events import AgentAnswer, FeedbackEventContent, ParrotEventType, TaskEventContent

def test_new_event_types():
    assert ParrotEventType.FEEDBACK == "m.parrot.feedback"
    assert ParrotEventType.CHANNEL == "m.parrot.channel"

def test_task_content_new_fields_default():
    t = TaskEventContent(task_id="1", content="q")
    assert t.hops == 0 and t.correlation_id is None and t.expected_schema is None

def test_agent_answer_schema_ok():
    AgentAnswer(answer={"total": 3}).validate_against({"type": "object", "required": ["total"]})

def test_agent_answer_schema_fail():
    with pytest.raises(ValueError):
        AgentAnswer(answer={"x": 1}).validate_against({"type": "object", "required": ["total"]})

def test_agent_answer_from_text_json_and_raw():
    assert AgentAnswer.from_text('{"answer": "42", "confidence": 0.9}').confidence == 0.9
    assert AgentAnswer.from_text("plain reply").answer == "plain reply"

def test_feedback_rating_bounds():
    with pytest.raises(ValidationError):
        FeedbackEventContent(correlation_id="c", about_event_id="$e", from_agent="a", to_agent="b", rating=9)
```

---

## Agent Instructions

1. Read the spec §2 Data Models and §6. 2. Verify the contract lines above with `sed -n`. 3. Implement. 4. Run the tests listed plus the existing matrix tests. 5. Move this file to `sdd/tasks/completed/`, update `sdd/tasks/index/matrix-agents-swarm.json` → `done`, fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none
