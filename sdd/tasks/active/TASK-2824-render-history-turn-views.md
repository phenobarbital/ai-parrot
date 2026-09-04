# TASK-2824: `render_history` accepts `TurnView` sequences (tool-activity suffix)

**Feature**: FEAT-525 — Per-Turn Conversation Compaction
**Spec**: `sdd/specs/per-turn-conversation-compaction.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2819
**Assigned-to**: unassigned

> ✅ **FEAT-524 merged** (PR #1310, merge `729ef7367`, 2026-09-04). Every
> FEAT-524 anchor below was re-verified on `dev` @ `198e6fecd` (after the
> post-merge `black` reformat `4831528a4`); `memory/render.py`,
> `ConversationTurn.from_ai_message` and `AbstractBot.memory_key_id` exist.

---

## Context

Spec §3 Module 9 and constraint C9. `compact_history()` (TASK-2828) is a pure
pre-pass that returns `TurnView`s with an already-rendered
`assistant_suffix`. `render_history` is the single place stored turns become
`HistoryMessage`s, so it must accept those views and *only concatenate* —
never compute ids, touch a store or import the compaction package at
runtime. A plain `ConversationHistory` must render byte-identically to
FEAT-524 (regression fixtures already exist in
`tests/unit/memory/test_render_history.py`).

---

## Scope

- Widen `render_history`'s first parameter to
  `Optional[ConversationHistory] | Sequence[TurnView]` (type-hint via a
  `TYPE_CHECKING`-only import of `TurnView`; runtime dispatch by duck-typing:
  an object with `.turns` is a history, a sequence whose items have
  `assistant_suffix` is a view list; an empty sequence renders `[]`).
- For views: the assistant content is
  `f"{view.assistant_text}{view.assistant_suffix}"` built **before** the
  existing foreign-label / merge / alternation logic (so a foreign turn
  renders `"[agent:x] " + text + suffix`). `max_turns` is ignored for views
  (compaction already applied the ceiling). `current_chatbot_id`,
  `include_other_agents`, `other_agent_label` behave exactly as for turns,
  using `view.chatbot_id`. A view whose `assistant_text` is blank is skipped
  exactly like a turn with a blank `assistant_response` (the suffix does not
  rescue it — keeps the "text-only views ≡ plain render" property).
- `HistoryMessage.turn_id` / `chatbot_id` come from `view.turn_id` /
  `view.chatbot_id`.
- Refactor the loop body into one private helper that takes
  `(turn_id, chatbot_id, user_text, assistant_text)` tuples so both paths
  share the merge/label logic — the plain-history path must produce the same
  bytes as before the refactor.
- Update the module docstring (it already names this feature as the
  extension point).
- Tests in `packages/ai-parrot/tests/unit/memory/compaction/test_render_views.py`.

**NOT in scope**: producing views (TASK-2828), the `<tool-activity>` text
itself (TASK-2827/2828), any bot change (TASK-2830/2831).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/memory/render.py` | MODIFY | widen first parameter; shared per-turn helper; `TYPE_CHECKING` import of `TurnView` |
| `packages/ai-parrot/tests/unit/memory/compaction/test_render_views.py` | CREATE | suffix appended, foreign label order, plain-history byte equality, text-only equality, no runtime compaction import |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: Use only what is listed here. Verify anything else before using it.

### Verified Imports
```python
from parrot.memory.render import HistoryMessage, render_history      # dev 198e6fecd: memory/render.py:42, :87
from parrot.memory import HistoryMessage, render_history             # dev: memory/__init__.py:13 re-exports both
from parrot.memory.abstract import ConversationHistory, ConversationTurn   # dev 198e6fecd: memory/abstract.py:130, :16
from parrot.memory.compaction.models import TurnView, TurnState      # TASK-2819 — TYPE_CHECKING-only import inside render.py
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/memory/render.py  (dev @ 198e6fecd — FEAT-524 merged)
from .abstract import ConversationHistory                             # :32  (the ONLY runtime parrot import)
__all__ = ("HistoryMessage", "render_history")                        # :34
_MERGE_SEPARATOR = "\n\n"                                             # :38
@dataclass(frozen=True)
class HistoryMessage:                                                 # :42
    role: Literal["user", "assistant"]; content: str
    chatbot_id: Optional[str] = None; turn_id: Optional[str] = None   # :56-59
def _append(out: List[HistoryMessage], message: HistoryMessage) -> None   # :62  merges same-role tail, keeps FIRST turn's ids
def render_history(history: Optional[ConversationHistory], *, max_turns: Optional[int] = None,
                   current_chatbot_id: Optional[str] = None, include_other_agents: bool = True,
                   other_agent_label: str = "[agent:{chatbot_id}]") -> List[HistoryMessage]   # :87
#   body: None/empty → []; max_turns<=0 → []; skip blank assistant_response; foreign = current_chatbot_id is not None
#         and turn.chatbot_id is not None and differ; label = other_agent_label.format(chatbot_id=…); f"{label} {text}"
# Module rule (docstring :14-18 + test): imports ONLY from .abstract at runtime.

# packages/ai-parrot/src/parrot/memory/compaction/models.py (TASK-2819)
@dataclass(frozen=True)
class TurnView: turn_id: str; chatbot_id: Optional[str]; user_text: str; assistant_text: str
                assistant_suffix: str; state: TurnState; estimated_tokens: int

# Regression fixtures (dev): packages/ai-parrot/tests/unit/memory/test_render_history.py
#   _turn(index, assistant="a", chatbot_id=None) :16 ; _history(*turns) :27 ; 
#   test_render_module_does_not_import_storage_backends :209 — source-text scan for `import/from .redis|.file|.mem|redis|aiofiles`; a TYPE_CHECKING `from .compaction.models import TurnView` does not match it
```

### Does NOT Exist
- ~~`render_history(..., budget=…)`~~ / ~~`render_history(..., views=…)`~~ — no such parameters; the *first positional* parameter is widened.
- ~~`ConversationHistory.get_messages_for_api`~~ — removed by FEAT-524; do not resurrect.
- ~~A `"tool"` role on `HistoryMessage`~~ — role stays `Literal["user", "assistant"]` (C8).
- ~~`TurnView.context_used`~~ — not a field; nothing renders `context_used` in any tier.
- ~~Runtime `from .compaction.models import TurnView` in render.py~~ — forbidden; `TYPE_CHECKING` only. Note that `parrot.memory.abstract` itself imports `compaction.models` after TASK-2819, so a `sys.modules` check is NOT a valid test — scan `render.py`'s source text / AST instead.

---

## Implementation Notes

### Pattern to Follow
```python
from typing import TYPE_CHECKING, Iterable, List, Literal, Optional, Sequence, Tuple, Union
if TYPE_CHECKING:  # pragma: no cover
    from .compaction.models import TurnView

def _iter_rows(source, max_turns) -> Iterable[Tuple[str, Optional[str], str, str]]:
    """Yield (turn_id, chatbot_id, user_text, assistant_text) for a history or a view sequence."""
    if source is None: return
    if hasattr(source, "turns"):                       # ConversationHistory
        turns = source.turns
        if max_turns is not None:
            if max_turns <= 0: return
            turns = turns[-max_turns:]
        for t in turns:
            yield t.turn_id, t.chatbot_id, t.user_message or "", t.assistant_response or ""
        return
    for v in source:                                   # Sequence[TurnView] — max_turns ignored
        yield v.turn_id, v.chatbot_id, v.user_text, f"{v.assistant_text}{v.assistant_suffix}" if v.assistant_text.strip() else ""
```
Then the existing loop consumes rows: blank assistant → skip; foreign label; `_append` user then assistant.

### Key Constraints
- Pure: no I/O, no mutation of history or views, no id computation.
- Plain-history output must be **byte-identical** — run the FEAT-524 test file unchanged as the regression gate.
- Keep `__all__ = ("HistoryMessage", "render_history")`.
- Google-style docstrings; extend the `render_history` docstring's `Args` with the view behaviour.

### References in Codebase
- `packages/ai-parrot/src/parrot/memory/render.py:87-160` — the function you are widening.
- `packages/ai-parrot/tests/unit/memory/test_render_history.py` — fixtures (`_turn` :16, `_history` :27) + import-scan test style (:209).

---

## Acceptance Criteria

- [ ] `render_history(views)` appends `assistant_suffix` to the assistant content; alternation/merge guarantees hold; foreign views render `"[agent:x] " + text + suffix`.
- [ ] `render_history(history)` output is byte-identical to FEAT-524 for every case in `tests/unit/memory/test_render_history.py` (that file passes unchanged).
- [ ] Views with `assistant_suffix == ""` built from a history render exactly the same `HistoryMessage` list as the plain history.
- [ ] `render.py` source has no runtime import of `parrot.memory.compaction` (only under `if TYPE_CHECKING:`).
- [ ] All tests pass: `timeout -s KILL 300 pytest packages/ai-parrot/tests/unit/memory/compaction/test_render_views.py packages/ai-parrot/tests/unit/memory/test_render_history.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/memory/render.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/memory/compaction/test_render_views.py
import ast
from pathlib import Path
from parrot.memory.abstract import ConversationHistory, ConversationTurn
from parrot.memory.compaction.models import TurnState, TurnView
from parrot.memory.render import render_history


def _turn(i, chatbot_id="bot"):
    return ConversationTurn(turn_id=f"t{i}", user_id="u", user_message=f"q{i}", assistant_response=f"a{i}", chatbot_id=chatbot_id)


def _view(t, suffix="", state=TurnState.RAW):
    return TurnView(turn_id=t.turn_id, chatbot_id=t.chatbot_id, user_text=t.user_message,
                    assistant_text=t.assistant_response, assistant_suffix=suffix, state=state, estimated_tokens=1)


def test_render_views_appends_suffix():
    t = _turn(1)
    out = render_history([_view(t, "\n\n<tool-activity>\n- q ok\n</tool-activity>")], current_chatbot_id="bot")
    assert [m.role for m in out] == ["user", "assistant"]
    assert out[1].content == "a1\n\n<tool-activity>\n- q ok\n</tool-activity>" and out[1].turn_id == "t1"


def test_render_foreign_view_label_precedes_text_and_suffix():
    t = _turn(1, chatbot_id="other")
    out = render_history([_view(t, "\n\nX")], current_chatbot_id="bot")
    assert out[1].content == "[agent:other] a1\n\nX"


def test_render_text_only_views_identical_to_plain():
    turns = [_turn(i) for i in range(5)]
    h = ConversationHistory(session_id="s", user_id="u", chatbot_id="bot", turns=turns)
    assert render_history([_view(t) for t in turns], current_chatbot_id="bot") == render_history(h, current_chatbot_id="bot")


def test_render_plain_history_max_turns_unchanged():
    h = ConversationHistory(session_id="s", user_id="u", turns=[_turn(i) for i in range(5)])
    assert [m.turn_id for m in render_history(h, max_turns=2)] == ["t3", "t3", "t4", "t4"]


def test_render_imports_no_compaction():
    import parrot.memory.render as mod
    tree = ast.parse(Path(mod.__file__).read_text(encoding="utf-8"))
    guarded = {id(n) for top in tree.body if isinstance(top, ast.If) and getattr(top.test, "id", "") == "TYPE_CHECKING"
               for n in ast.walk(top)}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)) and id(node) not in guarded:
            names = [a.name for a in node.names] + [getattr(node, "module", "") or ""]
            assert not any("compaction" in n for n in names), ast.dump(node)
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2819 in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** before writing any code; update it first if anything changed
4. **Update status** in `sdd/tasks/index/per-turn-conversation-compaction.json` → `"in-progress"`
5. **Implement** following the scope, contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2824-render-history-turn-views.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
