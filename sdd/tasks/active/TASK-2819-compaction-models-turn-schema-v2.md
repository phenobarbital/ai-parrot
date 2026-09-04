# TASK-2819: Compaction data models + `ConversationTurn` schema v2

**Feature**: FEAT-525 — Per-Turn Conversation Compaction
**Spec**: `sdd/specs/per-turn-conversation-compaction.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: none *(external prerequisite: FEAT-524 merged to `dev` — see banner)*
**Assigned-to**: unassigned

> ⚠️ **FEAT-524 prerequisite (spec C14).** This task extends
> `ConversationTurn.chatbot_id` and `from_ai_message()`, both created by
> FEAT-524 M2. Before writing any code, confirm on the current branch that
> `packages/ai-parrot/src/parrot/memory/render.py` exists and
> `ConversationTurn.from_ai_message` is defined. If not, STOP — FEAT-524 has
> not merged; do not re-implement it here. Every "FEAT-524 — unverified"
> entry in the contract below must be re-verified with real line numbers
> and the contract updated first.

---

## Context

Spec §2 "Data Models" and §3 Module 1. Every other task in FEAT-525 imports
the vocabulary defined here: `ToolInvocation`, `TokenCount`, `ContextBudget`,
`Limit`, `CompactionState`, `Omission`, `TurnView`, `CompactionResult`,
`CompactionCommit`, `TurnState`, `ToolStatus`. It also widens
`ConversationTurn` to schema v2 so tool activity (inputs, outputs, errors,
timing) survives the write for the first time (spec §1 problem 3), while
legacy dicts keep deserializing (spec G5 / C5).

---

## Scope

- Create the package `parrot/memory/compaction/` with `__init__.py` and
  `models.py` containing every model in spec §2 "Data Models" (`models.py`
  block), with the exact field names, defaults and `to_dict`/`from_dict`
  methods listed there. `ContextBudget.__post_init__` validates the
  invariants listed in the spec; `ContextBudget.available` never returns a
  negative number. Also define `FALLBACK_WINDOW = 32_000` here (re-exported
  by `budget.py` in TASK-2823).
  **Two planner amendments to the spec's `models.py` block** (decided at
  `/sdd-task` time, 2026-09-04): (a) `CompactionCommit` gains two optional
  telemetry fields with defaults — `history_estimate: int = 0` and
  `dropped_turns: int = 0` — so `AbstractBot.save_conversation_turn`
  (TASK-2830) can populate `Stage2CompactionNeededEvent` without a second
  channel; `apply_commit` (TASK-2823) ignores them. (b) `CompactionState`
  gets `to_dict()` / `from_dict()` (same tolerant convention as
  `TokenCount`) because it is persisted as `history.metadata["compaction"]`
  by TASK-2826 and read back by TASK-2830.
- Extend `ConversationTurn` (`parrot/memory/abstract.py`) with the six new
  fields (`tool_invocations`, `error`, `token_count`, `state`,
  `schema_version`, `norm_version`) with the defaults in the spec. Extend
  `to_dict` to emit every field (`tool_invocations` as a list of dicts,
  `token_count` as a dict or `None`, `state` as its value) and `from_dict`
  to tolerate the absence of every new key.
- Extend `ConversationTurn.from_ai_message` (FEAT-524) with an `error:
  Optional[str] = None` kwarg and fill `tool_invocations` from
  `response.tool_calls`: `tool_name=tc.name`, `input=tc.arguments`,
  `output=_stringify(tc.result)`, `status=ERROR if tc.error else COMPLETED`,
  `error=tc.error`, `elapsed_ms=int(tc.execution_time * 1000)` when set,
  `wm_key=result["_tee"]["key"]` when `tc.result` is a dict carrying a
  `_tee` block. `tools_used` stays exactly as FEAT-524 fills it.
- `_stringify(result)`: `str` unchanged; `None` → `None`; dict/list →
  `orjson.dumps(..., option=OPT_SORT_KEYS).decode()`; anything else → `str()`.
- Unit tests in `packages/ai-parrot/tests/unit/memory/compaction/test_models.py`.

**NOT in scope**: normalization (TASK-2820), token counting (TASK-2821),
the omission store (TASK-2822), `MODEL_WINDOWS`/`resolve_window`/`apply_*`
(TASK-2823), any change to `ConversationMemory` or the backends
(TASK-2826), `render_history` (TASK-2824), `memory/__init__.py` exports
(TASK-2832).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/memory/compaction/__init__.py` | CREATE | package marker; re-export the models (no other imports) |
| `packages/ai-parrot/src/parrot/memory/compaction/models.py` | CREATE | all models from spec §2 |
| `packages/ai-parrot/src/parrot/memory/abstract.py` | MODIFY | `ConversationTurn` v2 fields, `to_dict`/`from_dict`, `from_ai_message` |
| `packages/ai-parrot/tests/unit/memory/compaction/__init__.py` | CREATE | test package |
| `packages/ai-parrot/tests/unit/memory/compaction/conftest.py` | CREATE | `make_turn()`, `chatty_history`, `database_history` fixtures (spec §4) |
| `packages/ai-parrot/tests/unit/memory/compaction/test_models.py` | CREATE | round-trip, legacy defaults, `from_ai_message`, budget validation |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
from parrot.memory.abstract import ConversationTurn, ConversationHistory   # verified: memory/abstract.py:11, 51 (dev a824f6535)
from parrot.models.basic import ToolCall, CompletionUsage                  # verified: models/basic.py:23, 48
from parrot.models.responses import AIMessage                              # verified: models/responses.py:72
import orjson                                                              # verified: 3.12.0 installed; pyproject.toml:164
from parrot.tools.compression.tee import attach_tee_pointer                # verified: tools/compression/tee.py:161 (tests only — builds a _tee block)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/memory/abstract.py  (dev a824f6535 — FEAT-524 adds chatbot_id + from_ai_message)
@dataclass
class ConversationTurn:                                            # line 10-11
    turn_id: str; user_id: str; user_message: str; assistant_response: str   # 13-16
    context_used: Optional[str] = None                             # 17
    tools_used: List[str] = field(default_factory=list)            # 18  ← keep as a real field
    timestamp: datetime = field(default_factory=datetime.now)      # 19
    metadata: Dict[str, Any] = field(default_factory=dict)         # 20
    def to_dict(self) -> Dict[str, Any]                            # 22  (stdlib dataclass, hand-written dict)
    @classmethod def from_dict(cls, data) -> 'ConversationTurn'    # 36  (uses data.get(..., default) for optionals)
# FEAT-524 — unverified in code (spec conversation-history-ownership §2):
#   chatbot_id: Optional[str] = None
#   @classmethod from_ai_message(cls, *, user_message, response: "AIMessage", user_id, chatbot_id,
#                                context_used=None, turn_id=None, assistant_text=None) -> "ConversationTurn"
#   # tools_used = [tc.name for tc in response.tool_calls]; metadata = {model, provider, usage(dict), finish_reason, response_time}

# packages/ai-parrot/src/parrot/models/basic.py
class ToolCall(BaseModel):                                         # 23
    id: str; name: str; arguments: Dict[str, Any]                  # 24-27
    result: Optional[Any] = None; error: Optional[str] = None      # 28-29
    execution_time: Optional[float] = None                         # 30  (seconds)
class CompletionUsage(BaseModel):                                  # 48
    @property input_tokens(self) -> int                            # 104

# packages/ai-parrot/src/parrot/models/responses.py
class AIMessage(BaseModel):                                        # 72
    usage: CompletionUsage                                         # 118
    tool_calls: List[ToolCall]                                     # 139
    turn_id: Optional[str]                                         # 163

# packages/ai-parrot/src/parrot/tools/compression/tee.py
def attach_tee_pointer(payload, key, reason) -> Any                # 161: dict → {**payload, "_tee": pointer} (:181); else {"result": payload, "_tee": pointer} (:182)
# pointer is a dict; its "key" looks like "__tee__:{tool_name}:{turn_id}:{n}" (:117)
```

### Does NOT Exist
- ~~`parrot.memory.compaction`~~ — does not exist yet; this task creates it.
- ~~`ToolInvocation`, `TokenCount`, `ContextBudget`, `Limit`, `CompactionState`, `Omission`, `TurnView`, `CompactionResult`, `CompactionCommit`, `TurnState`, `ToolStatus`~~ — none exist under `parrot/`; create them exactly as in spec §2.
- ~~`ConversationTurn.tool_invocations` / `.error` / `.token_count` / `.state` / `.schema_version` / `.norm_version`~~ — new here.
- ~~Pydantic `BaseModel` for these models~~ — do NOT use Pydantic; `ConversationTurn` is a stdlib dataclass with hand-written `to_dict`/`from_dict` and the new models follow the same convention (spec §2 note).
- ~~`ConversationHistory.get_messages_for_api`~~ — removed by FEAT-524; never call it.
- ~~`MODEL_WINDOWS`, `resolve_window`, `apply_usage`, `apply_commit`~~ — TASK-2823, not here.
- ~~`ConversationMemory.add_turn` being concrete~~ — still abstract until TASK-2826.

---

## Implementation Notes

### Pattern to Follow
```python
# memory/abstract.py:22-47 — hand-written dict round trip; extend, do not replace
def to_dict(self) -> Dict[str, Any]:
    return {..., 'tools_used': self.tools_used, 'timestamp': self.timestamp.isoformat(), 'metadata': self.metadata,
            'chatbot_id': self.chatbot_id,                                   # FEAT-524
            'tool_invocations': [inv.to_dict() for inv in self.tool_invocations],
            'error': self.error,
            'token_count': self.token_count.to_dict() if self.token_count else None,
            'state': self.state.value, 'schema_version': self.schema_version, 'norm_version': self.norm_version}

@classmethod
def from_dict(cls, data):
    return cls(..., tool_invocations=[ToolInvocation.from_dict(d) for d in data.get('tool_invocations', [])],
               error=data.get('error'), token_count=TokenCount.from_dict(tc) if (tc := data.get('token_count')) else None,
               state=TurnState(data.get('state', 'raw')), schema_version=data.get('schema_version', 1),
               norm_version=data.get('norm_version'))
```

### Key Constraints
- `models.py` imports stdlib + `orjson` only; it must NOT import `parrot.memory.abstract` (abstract imports it — avoid the cycle by importing the models in `abstract.py`, never the reverse).
- Frozen dataclasses for everything except `ToolInvocation` (mutated by the write-time offload in TASK-2826) and `ConversationTurn`.
- `TurnState` stored value is always `"raw"` in v1; `PRUNED` is a view-only state.
- `ContextBudget` invariants: `window > reserve_output + reserve_fixed`; `0 < low_watermark <= high_watermark <= 1`; `max_turns >= min_verbatim_turns >= 1`; `verbatim_tokens >= 0`; `oversize_tool_tokens > 0` → `ValueError` otherwise.
- Google-style docstrings, strict type hints, no `print`.

### References in Codebase
- `packages/ai-parrot/src/parrot/memory/abstract.py:10-47` — dataclass + dict round-trip convention.
- `packages/ai-parrot/src/parrot/security/groundedness/models.py` — style of small frozen dataclasses in this repo.

---

## Acceptance Criteria

- [ ] `from parrot.memory.compaction.models import ToolInvocation, TokenCount, ContextBudget, Limit, CompactionState, Omission, TurnView, CompactionResult, CompactionCommit, TurnState, ToolStatus, FALLBACK_WINDOW` works.
- [ ] `ConversationTurn.from_dict(turn.to_dict()) == turn` for a v2 turn with invocations, error, token_count.
- [ ] A FEAT-524-shaped dict (no new keys) deserializes with `tool_invocations == []`, `error is None`, `token_count is None`, `state is TurnState.RAW`, `schema_version == 1`, `norm_version is None`; `tools_used` intact.
- [ ] `from_ai_message` fills `tool_invocations` (status ERROR when `tc.error`; `elapsed_ms`; `wm_key` from a `_tee` block) and `error`; `tools_used` unchanged from FEAT-524.
- [ ] `ContextBudget(window=1000, reserve_output=900, reserve_fixed=200)` raises `ValueError`; `ContextBudget(window=32_000).available == 19_712`.
- [ ] All tests pass: `timeout -s KILL 300 pytest packages/ai-parrot/tests/unit/memory/compaction/test_models.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/memory/compaction packages/ai-parrot/src/parrot/memory/abstract.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/memory/compaction/test_models.py
import pytest
from parrot.memory.abstract import ConversationTurn
from parrot.memory.compaction.models import (
    ContextBudget, TokenCount, ToolInvocation, ToolStatus, TurnState,
)
from parrot.models.basic import ToolCall, CompletionUsage
from parrot.models.responses import AIMessage
from parrot.tools.compression.tee import attach_tee_pointer


def test_turn_roundtrip_v2():
    inv = ToolInvocation(tool_name="q", input={"b": 1, "a": 2}, output="rows", elapsed_ms=12)
    t = ConversationTurn(turn_id="t1", user_id="u", user_message="hi", assistant_response="yo",
                         chatbot_id="bot", tool_invocations=[inv], error=None,
                         token_count=TokenCount(user=1, assistant=1, tools=2, total=4, tokenizer="heuristic"),
                         schema_version=2, norm_version="1")
    assert ConversationTurn.from_dict(t.to_dict()) == t


def test_turn_legacy_dict_defaults():
    legacy = {"turn_id": "t", "user_id": "u", "user_message": "a", "assistant_response": "b",
              "tools_used": ["x"], "timestamp": "2026-09-04T00:00:00", "metadata": {}}
    t = ConversationTurn.from_dict(legacy)
    assert t.tool_invocations == [] and t.error is None and t.token_count is None
    assert t.state is TurnState.RAW and t.schema_version == 1 and t.norm_version is None
    assert t.tools_used == ["x"]


def test_from_ai_message_fills_invocations():
    result = attach_tee_pointer({"rows": [1, 2]}, key="__tee__:q:abc:1", reason="lossy")
    msg = AIMessage(content="ok", usage=CompletionUsage(input_tokens=10, output_tokens=2),
                    tool_calls=[ToolCall(id="1", name="q", arguments={"sql": "x"}, result=result, execution_time=1.5),
                                ToolCall(id="2", name="w", arguments={}, error="boom")])
    t = ConversationTurn.from_ai_message(user_message="u", response=msg, user_id="u1", chatbot_id="bot")
    a, b = t.tool_invocations
    assert a.tool_name == "q" and a.wm_key == "__tee__:q:abc:1" and a.elapsed_ms == 1500 and a.status is ToolStatus.COMPLETED
    assert b.status is ToolStatus.ERROR and b.error == "boom"
    assert t.tools_used == ["q", "w"]


def test_context_budget_validation():
    with pytest.raises(ValueError):
        ContextBudget(window=1000, reserve_output=900, reserve_fixed=200)
    assert ContextBudget(window=32_000).available == 19_712
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify FEAT-524 is merged (banner above)
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `sdd/tasks/index/per-turn-conversation-compaction.json` → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2819-compaction-models-turn-schema-v2.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
