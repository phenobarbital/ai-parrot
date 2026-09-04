# TASK-2809: `parrot.memory` render layer + turn attribution

**Feature**: FEAT-524 — Conversation History Ownership
**Spec**: `sdd/specs/conversation-history-ownership.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §2 "Data Models" and §3 Module 2. The memory layer becomes the only
place that knows how a `ConversationHistory` turns into provider-neutral
messages (`render_history`), and every turn learns which agent produced it
(`ConversationTurn.chatbot_id`). `ConversationHistory.get_messages_for_api()`
— provider-aware, Claude-shaped — is removed (hard cut). This is the
extension point the compaction brainstorm will be re-run against.

---

## Scope

- CREATE `packages/ai-parrot/src/parrot/memory/render.py`:
  - `@dataclass(frozen=True) class HistoryMessage: role: Literal["user","assistant"]; content: str; chatbot_id: Optional[str] = None; turn_id: Optional[str] = None`
  - `def render_history(history, *, max_turns=None, current_chatbot_id=None, include_other_agents=True, other_agent_label="[agent:{chatbot_id}]") -> list[HistoryMessage]` — pure; guarantees per spec §2:
    strict alternation starting `user`, ending `assistant`; consecutive
    same-role merge with `"\n\n"`; skip turns whose `assistant_response`
    is empty/whitespace; drop or label foreign-agent turns; `max_turns`
    keeps the most recent N.
  - `render.py` may import **only** from `.abstract` (leaf module; no
    `.redis`/`.file`/`.mem`).
- MODIFY `packages/ai-parrot/src/parrot/memory/abstract.py`:
  - `ConversationTurn.chatbot_id: Optional[str] = None` (last field, keeps positional compatibility); `to_dict`/`from_dict` carry it (`data.get('chatbot_id')`).
  - `@classmethod ConversationTurn.from_ai_message(cls, *, user_message, response, user_id, chatbot_id, context_used=None, turn_id=None, assistant_text=None)` — canonical metadata shape `{"model","provider","usage","finish_reason","response_time"}`; `tools_used=[tc.name for tc in response.tool_calls]`; `assistant_response = assistant_text if assistant_text is not None else response.to_text`; `turn_id = turn_id or response.turn_id or uuid4()`. Import `AIMessage` under `TYPE_CHECKING` only (avoid `parrot.models` ↔ `parrot.memory` import cycle — verify with `python -c "import parrot.memory"`).
  - REMOVE `ConversationHistory.get_messages_for_api` (lines 70-98).
- MODIFY `packages/ai-parrot/src/parrot/memory/__init__.py`: export `HistoryMessage`, `render_history` (add to `__all__`).
- CREATE `packages/ai-parrot/tests/unit/memory/test_render_history.py` and `test_conversation_turn_attribution.py`.

**NOT in scope**: backend changes (TASK-2810), bot/client call sites, the
other `get_messages_for_api` callers (`clients/base.py:2322`, `clients/claude.py:1414`
— TASK-2812/2813 delete them; until then those two lines are dead-but-present
references. Run `grep -rn get_messages_for_api packages/ai-parrot/src` and list
the survivors in the completion note).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/memory/render.py` | CREATE | `HistoryMessage`, `render_history` |
| `packages/ai-parrot/src/parrot/memory/abstract.py` | MODIFY | `chatbot_id` field, `from_ai_message`, remove `get_messages_for_api` |
| `packages/ai-parrot/src/parrot/memory/__init__.py` | MODIFY | exports |
| `packages/ai-parrot/tests/unit/memory/test_render_history.py` | CREATE | render guarantees |
| `packages/ai-parrot/tests/unit/memory/test_conversation_turn_attribution.py` | CREATE | field round-trip + `from_ai_message` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.memory import ConversationHistory, ConversationMemory, ConversationTurn  # parrot/memory/__init__.py:3
from parrot.models import AIMessage   # parrot/models/__init__.py:9  (TYPE_CHECKING-only inside parrot.memory)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/memory/abstract.py
@dataclass
class ConversationTurn:                                   # line 11
    turn_id: str; user_id: str; user_message: str; assistant_response: str
    context_used: Optional[str] = None; tools_used: List[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.now); metadata: Dict[str, Any] = field(default_factory=dict)
    def to_dict(self) -> Dict[str, Any]                    # line 22
    @classmethod from_dict(cls, data) -> 'ConversationTurn' # line 36

@dataclass
class ConversationHistory:                                # line 51
    session_id: str; user_id: str; chatbot_id: Optional[str] = None; turns: List[ConversationTurn] = ...
    def add_turn(self, turn) -> None                       # line 61
    def get_recent_turns(self, count: int = 5)             # line 66  (turns[-count:] if count > 0 else turns)
    def get_messages_for_api(self, model='claude')         # line 70-98  ← DELETE
    def clear_turns / to_dict / from_dict                  # lines 100 / 105 / 118

# packages/ai-parrot/src/parrot/memory/__init__.py
from .abstract import ConversationHistory, ConversationMemory, ConversationTurn   # line 3
__all__ = [...]                                                                    # line 76

# packages/ai-parrot/src/parrot/models/responses.py — AIMessage (line 72)
    model: str (111)  provider: str (114)  usage: CompletionUsage (118)  finish_reason: Optional[str] (135)
    tool_calls: List[ToolCall] (139)  response_time: Optional[float] (151)  turn_id: Optional[str] (163)
    @property to_text(self) -> str  (267)
```

### Does NOT Exist
- ~~`parrot.memory.HistoryMessage`~~, ~~`parrot.memory.render`~~, ~~`render_history`~~ — you create them.
- ~~`ConversationTurn.chatbot_id`~~, ~~`ConversationTurn.from_ai_message`~~ — you create them.
- `ChatMessage` exists at `parrot/storage/models.py:73` and `ai-parrot-server/.../handlers/openai_compat.py:79` — **different concepts, do not reuse or import**.
- ~~`ConversationMemory.get_messages_for_api`~~ — never existed on the backend ABC.
- ~~`ConversationSession`~~ — legacy name in a docstring only (`abstract.py:52`).

---

## Implementation Notes

### Pattern to Follow
```python
def render_history(history, *, max_turns=None, current_chatbot_id=None,
                   include_other_agents=True, other_agent_label="[agent:{chatbot_id}]"):
    if history is None or not history.turns:
        return []
    turns = history.turns[-max_turns:] if max_turns else history.turns
    out: list[HistoryMessage] = []
    for t in turns:
        if not (t.assistant_response or "").strip():
            continue
        foreign = current_chatbot_id is not None and t.chatbot_id not in (None, current_chatbot_id)
        if foreign and not include_other_agents:
            continue
        asst = t.assistant_response
        if foreign:
            asst = f"{other_agent_label.format(chatbot_id=t.chatbot_id)} {asst}"
        _append(out, HistoryMessage("user", t.user_message, t.chatbot_id, t.turn_id))
        _append(out, HistoryMessage("assistant", asst, t.chatbot_id, t.turn_id))
    # _append merges when out[-1].role == msg.role (content joined with "\n\n")
    return out
```
Treat `chatbot_id is None` on a turn as "own agent" (legacy turns, spec M2b).

### Key Constraints
- Pure function: no logging that alters output, no mutation of `history`.
- Dataclasses, not Pydantic, to match the existing module.
- Keep `render.py` importable without Redis/aiofiles installed.

---

## Acceptance Criteria

- [ ] `from parrot.memory import HistoryMessage, render_history` works.
- [ ] `not hasattr(ConversationHistory, "get_messages_for_api")`.
- [ ] Tests: alternation, merge-consecutive, skip-empty, label/filter foreign, `max_turns`, purity (two renders equal, input untouched), `chatbot_id` round-trip incl. legacy dict without key ⇒ `None`, `from_ai_message` metadata shape + `tools_used` + `assistant_text` override.
- [ ] `timeout -s KILL 300 pytest packages/ai-parrot/tests/unit/memory -v` green (except TASK-2808's intentionally red tests).
- [ ] `ruff check packages/ai-parrot/src/parrot/memory` clean.

---

## Test Specification

```python
def _turn(i, asst="a", cid=None):
    return ConversationTurn(f"t{i}", "u", f"q{i}", asst, chatbot_id=cid)

def test_render_alternation():
    h = ConversationHistory("s", "u"); [h.add_turn(_turn(i)) for i in range(3)]
    roles = [m.role for m in render_history(h)]
    assert roles == ["user", "assistant"] * 3

def test_render_skips_empty_assistant():
    h = ConversationHistory("s", "u"); h.add_turn(_turn(1, asst="   "))
    assert render_history(h) == []

def test_render_other_agent_label_and_filter():
    h = ConversationHistory("s", "u"); h.add_turn(_turn(1, cid="A")); h.add_turn(_turn(2, cid="B"))
    labeled = render_history(h, current_chatbot_id="A")
    assert labeled[3].content.startswith("[agent:B]")
    assert len(render_history(h, current_chatbot_id="A", include_other_agents=False)) == 2

def test_turn_chatbot_id_roundtrip_and_legacy():
    t = _turn(1, cid="X"); assert ConversationTurn.from_dict(t.to_dict()).chatbot_id == "X"
    legacy = {k: v for k, v in t.to_dict().items() if k != "chatbot_id"}
    assert ConversationTurn.from_dict(legacy).chatbot_id is None
```

---

## Agent Instructions

1. Read spec §2 Data Models + §3 M2. 2. Verify contract lines. 3. Implement with tests first.
4. `python -c "import parrot.memory; import parrot.clients.base"` must still import (no cycle).
5. Commit only the listed files; move this file to `completed/`; update the per-spec index; fill the note.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
