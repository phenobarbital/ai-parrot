# TASK-5572: Rich history parts — `MessagePart`, budgeted parts on views, canonical text, renderer

**Feature**: FEAT-886 — Durable Conversation Memory
**Spec**: `sdd/specs/durable-conversation-memory.spec.md` (Module 16)
**Status**: pending
**Priority**: medium
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-5569 (memory/__init__.py)
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 16 / §2 "Piece 4 — Composer: structured parts" / G9. Today `TurnView.assistant_suffix` is one pre-rendered
`<tool-activity>` string; `HistoryMessage` is text-only. This task introduces structured, ALREADY-BUDGETED parts without changing
what any client receives (Phase 1):

- `parrot/memory/parts.py` — `MessagePart` (frozen dataclass) and `render_parts_text`, the ONE canonical formatter of tool parts.
- `TurnView.parts` and `PrunedInvocation.parts` — produced by `compact_history` / the prune policies together with their canonical text, so the
  token counter measures exactly the text that is sent.
- `HistoryMessage.parts` — carried by `render_history` next to the already-rendered `content` (informational; every `_format_history`
  consumes `content` once and never appends parts again).
- With compaction disabled the output is byte-identical to today and `parts is None`.

`parrot/memory/__init__.py` was last edited by TASK-5569 (persistence exports); this task adds its own exports at different anchors.
TASK-5580 (hydration) later edits `memory/__init__.py` again.

---

## Scope

- Create `parrot/memory/parts.py`: `MessagePart`, `render_parts_text` (stdlib only — it is a leaf, like `render.py`).
- `compaction/models.py`: `TurnView.parts: Optional[Tuple[MessagePart, ...]] = None`.
- `compaction/policies.py`: `PrunedInvocation.parts`; `format_invocation_parts` (the line is derived from it, so they cannot diverge);
  `prune_turn_parts` (and `prune_turn` becomes `render_parts_text` of it, signature unchanged).
- `compaction/compact.py`: `render_raw_parts` (and `render_raw_view` delegates), `compact_history` fills `TurnView.parts`.
- `render.py`: `HistoryMessage.parts`; `_iter_rows` / `render_history` carry view parts; merged messages concatenate parts in order.
- Export `MessagePart`, `render_parts_text` from `parrot/memory/__init__.py`.
- Tests: `test_history_parts.py` (spec §4 `test_parts_raw_pruned_dropped`, `test_suffix_equals_rendered_parts`, `test_disabled_compaction_byte_identical`,
  `test_custom_policy_without_parts`) and `test_format_history_consumes_content_once.py` (base, bedrock, google, jev).

**NOT in scope**: emitting native provider `tool_use` / `tool_result` blocks from `parts` (follow-up; `MessagePart.tool_call_id` stays `None`);
any change to `parrot/clients/base.py` or to a client's `_format_history` (tests only); `ConversationTurn` / persistence changes;
the FEAT-538 task-recall injection at `bots/abstract.py:2498` (it builds a `HistoryMessage` with no parts and must keep working unchanged);
Stage 2 summaries.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/memory/parts.py` | CREATE | `MessagePart`, `render_parts_text` |
| `packages/ai-parrot/src/parrot/memory/compaction/models.py` | MODIFY | `TurnView.parts` |
| `packages/ai-parrot/src/parrot/memory/compaction/compact.py` | MODIFY | `render_raw_parts`; views carry parts |
| `packages/ai-parrot/src/parrot/memory/compaction/policies.py` | MODIFY | `PrunedInvocation.parts`, `format_invocation_parts`, `prune_turn_parts` |
| `packages/ai-parrot/src/parrot/memory/render.py` | MODIFY | `HistoryMessage.parts`, row/part carrying, merge |
| `packages/ai-parrot/src/parrot/memory/__init__.py` | MODIFY | export `MessagePart`, `render_parts_text` |
| `packages/ai-parrot/tests/unit/memory/compaction/test_history_parts.py` | CREATE | parts unit tests |
| `packages/ai-parrot/tests/unit/clients/test_format_history_consumes_content_once.py` | CREATE | four `_format_history` implementations |

---

## Codebase Contract (Anti-Hallucination)

Re-verified against the tree at `6d564b36a2` (branch `dev`).

### Verified Imports
```python
from parrot.memory.abstract import ConversationHistory, ConversationTurn            # verified: memory/compaction/compact.py:18
from parrot.memory.compaction.models import (CompactionResult, ContextBudget, Limit, Omission, TurnState, TurnView, ToolInvocation, ToolStatus)  # verified: compact.py:19-26, policies.py:23
from parrot.memory.compaction.policies import PrunePolicy, PrunedInvocation, format_invocation_line, get_policy, prune_turn   # verified: compact.py:27 (+ policies.py:33,40,60,301,320)
from parrot.memory.compaction.tokens import HeuristicCounter, TokenCounter           # verified: tests/unit/memory/compaction/conftest.py:12 ; compact.py:28
from parrot.memory.render import HistoryMessage, render_history                      # verified: memory/__init__.py:27
from parrot.memory.compaction.omission import content_id                              # verified: policies.py:24
from parrot.clients.base import AbstractClient                                        # verified: tests/unit/clients/test_abstract_client_memoryless.py:17
# NEW module created by THIS task:
from parrot.memory.parts import MessagePart, render_parts_text
# tests, satellite clients (all three import in the dev venv; use pytest.importorskip anyway):
#   parrot.clients.amazon.bedrock.BedrockConverseBase   (_format_history :705)
#   parrot.clients.google.client.GoogleGenAIClient      (_format_history :3241)
#   parrot.clients.jev.client.JevClient                 (_format_history :348)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/memory/render.py
@dataclass(frozen=True)
class HistoryMessage:                                                     # :54   role, content, chatbot_id=None, turn_id=None
def _append(out, message) -> None                                          # :74   merges into the tail on a role clash with "\n\n" (_MERGE_SEPARATOR)
def _iter_rows(source, max_turns) -> Iterable[Tuple[str, Optional[str], str, str]]   # :99  (turn_id, chatbot_id, user_text, assistant_text)
    # view path: row_assistant = f"{assistant_text}{view.assistant_suffix}" if assistant_text.strip() else ""
def render_history(history, *, max_turns=None, current_chatbot_id=None, include_other_agents=True, other_agent_label="[agent:{chatbot_id}]") -> List[HistoryMessage]   # :143
    # foreign label: assistant_text = f"{label} {assistant_text}" (precedes text AND suffix)
# test constraint: tests/unit/memory/compaction/test_render_views.py:55 `test_render_imports_no_compaction` — render.py must not import anything containing "compaction" at runtime.

# packages/ai-parrot/src/parrot/memory/compaction/models.py
@dataclass(frozen=True)
class TurnView:                                                           # :283
    turn_id; chatbot_id; user_text; assistant_text; assistant_suffix; state: TurnState; estimated_tokens: int   # :296 last field (1 occurrence of `    estimated_tokens: int`)
# module docstring: "leaf module: imports stdlib and orjson only; must NEVER import parrot.memory.abstract" — parts.py is stdlib-only, importing it is allowed.

# packages/ai-parrot/src/parrot/memory/compaction/policies.py
@dataclass(frozen=True)
class PrunedInvocation: notice: str; omissions: Tuple[Omission, ...]       # :33
class PrunePolicy(Protocol): def prune(self, inv, *, turn_id, limit) -> PrunedInvocation   # :40/:45  (signature must NOT change)
def format_invocation_line(inv, *, limit, body) -> str                      # :60  "- {tool} {ok|error}[ {N.N}s] in={canonical}" + (" "+body if body)
def omission_notice(inv, content_id_, chars) -> str                         # :88
def _prune_shared(inv, *, turn_id, limit, narrowed_input=None, extra_parts=()) -> PrunedInvocation   # :127 — every built-in policy ends here
def prune_turn(turn, *, limit=Limit(), policies=None) -> Tuple[str, Tuple[Omission, ...]]   # :320
    # suffix = "\n\n<tool-activity>\n" + "\n".join(lines) + "\n</tool-activity>" (+ "\nOmitted content can be recovered with read_omitted_content(...) ..." iff a "<tool-output-omitted" notice exists)

# packages/ai-parrot/src/parrot/memory/compaction/compact.py
def render_raw_view(turn, limit, *, oversize=(), policies=None, counter) -> Tuple[str, Tuple[Omission, ...]]   # :36 (~80 lines — already over the 60-line budget: extract, do not grow)
    # RAW block: f"\n\n<tool-activity>\n{block}\n</tool-activity>"; overflow line "… +N more"; token-collapse pops lines from the end then appends "… +N more"
def render_tool_activity(turn, limit) -> str                                # :120 (HeuristicCounter wrapper)
def compact_history(history, budget, *, policies=None, boundary_turn_id=None, counter=None, calibration=1.0, current_chatbot_id=None, include_other_agents=True) -> CompactionResult   # :143
    # :248 `raw_suffix, raw_omissions = render_raw_view(` ; :253 `pr_suffix, pr_omissions = prune_turn(turn, limit=budget.tool_activity_limit, policies=policies)`
    # :292 `assistant_suffix=raw_suffix,` ; :310 `assistant_suffix=pr_suffix,`  (each 1 occurrence)

# packages/ai-parrot/src/parrot/memory/__init__.py
from .render import HistoryMessage, render_history                          # :27  (1 occurrence)  "MemoryContext", / "render_history", in __all__ (1 occurrence each)

# four _format_history implementations (all already consume `message.content` once):
#   AbstractClient._format_history   clients/base.py:1863  -> [{"role": m.role, "content": [{"type": "text", "text": m.content}]}]
#   BedrockConverseBase              bedrock.py:705        -> [{"role", "content": [{"text": m.content}]}]
#   GoogleGenAIClient                google/client.py:3241 -> UserContent/ModelContent(parts=[Part(text=m.content)]); blank content skipped
#   JevClient                        jev/client.py:348     -> [{"role": m.role, "content": m.content}]
```

### Does NOT Exist
- ~~`parrot.memory.parts`~~, ~~`MessagePart`~~, ~~`render_parts_text`~~ — created by THIS task.
- ~~`HistoryMessage.parts`~~, ~~`TurnView.parts`~~, ~~`PrunedInvocation.parts`~~ — added here. ~~`TurnView.tool_invocations`~~ — NOT a field; the renderer must never recover raw invocations after the budget decision.
- ~~`ToolInvocation.tool_call_id`~~ — not a field; `MessagePart.tool_call_id` stays `None` in Phase 1.
- ~~`prune_turn_parts`~~, ~~`render_raw_parts`~~, ~~`format_invocation_parts`~~ — added here (existing names `prune_turn`, `render_raw_view`, `format_invocation_line` keep their signatures and return types).
- ~~A change to `PrunePolicy.prune`'s signature~~ — it stays; a custom policy returning no `parts` yields one `text` part holding its rendered line.
- ~~Provider-native tool blocks emitted from parts~~ — follow-up; no client reads `parts`.
- ~~An import of `parrot.memory.compaction` from `render.py`~~ — forbidden by `test_render_imports_no_compaction`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/memory/parts.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/memory/compaction/models.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/memory/compaction/compact.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/memory/compaction/policies.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/memory/render.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/memory/__init__.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/unit/memory/compaction/test_history_parts.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/unit/clients/test_format_history_consumes_content_once.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/memory/render.py#HistoryMessage",
    "sym:packages/ai-parrot/src/parrot/memory/render.py#render_history",
    "sym:packages/ai-parrot/src/parrot/memory/compaction/models.py#TurnView",
    "sym:packages/ai-parrot/src/parrot/memory/compaction/policies.py#PrunedInvocation",
    "sym:packages/ai-parrot/src/parrot/memory/compaction/policies.py#PrunePolicy",
    "sym:packages/ai-parrot/src/parrot/memory/compaction/policies.py#format_invocation_line",
    "sym:packages/ai-parrot/src/parrot/memory/compaction/policies.py#prune_turn",
    "sym:packages/ai-parrot/src/parrot/memory/compaction/compact.py#render_raw_view",
    "sym:packages/ai-parrot/src/parrot/memory/compaction/compact.py#compact_history"
  ]
}
```

---

## Implementation Notes

### The canonical formatter (decided design — implement exactly)
Parts are an ordered tuple. `render_parts_text(parts)` is the inverse of today's suffix construction:
- `tool_use` part = the invocation header `- {tool} {ok|error}[ {N.N}s] in={...}` (`tool_name` set); `tool_result` part = the body
  (`out=...`, omission notice, `exit=`, `rows=`, `error=...`) appended to the SAME line with one space; an invocation with an empty body has no result part.
- `text` part whose content does NOT start with `"\n"` is a standalone line inside the block (the `… +N more` overflow line, or a custom policy's rendered line).
- `text` part whose content STARTS with `"\n"` is a trailer placed after the closing tag (the `Omitted content can be recovered ...` hint).
- Output: `""` for empty parts; otherwise `"\n\n<tool-activity>\n" + "\n".join(lines) + "\n</tool-activity>" + "".join(trailers)`.
This reproduces BOTH the RAW and PRUNED suffix byte for byte. `format_invocation_line` is re-expressed as `" ".join(p.content for p in format_invocation_parts(...))`,
so a line and its parts cannot drift apart. `assistant_suffix == render_parts_text(parts)` for every view that has tool activity; a view with none keeps `parts=None`, `assistant_suffix=""`.

### Key Constraints
- Byte identity is the hard constraint: every existing test in `tests/unit/memory/compaction/` and `tests/unit/memory/test_render_history.py` stays green UNCHANGED.
- The token counter must measure `render_parts_text(parts)` — in `compact_history` that is the same string already passed to `counter.count(...)` (it is now derived from the parts).
- Disabled compaction: `render_history(ConversationHistory)` is untouched → `HistoryMessage.parts is None`; text-only views also keep `parts=None`.
- Omission notices, errors and role alternation are preserved; DROPPED turns produce no view/message/parts/summary (unchanged walk).
- Functions ≤ 60 lines, cyclomatic complexity ≤ 10: `render_raw_view` is already ~80 lines — extract `_raw_invocation_parts(...)` and `_collapse_to_token_limit(...)` as part of this change instead of growing it.
- Frozen dataclasses for `MessagePart`, `TurnView`, `HistoryMessage`, `PrunedInvocation` (spec §7). Google-style docstrings; no I/O.

### References in Codebase
- `packages/ai-parrot/tests/unit/memory/compaction/conftest.py:60-100` — `make_turn`, `database_history`, `counter`, `budget` fixtures (reuse the pattern; do not edit that conftest).
- `packages/ai-parrot/tests/unit/memory/compaction/test_render_views.py` — `_view(...)` helper shape for building `TurnView`s.
- `packages/ai-parrot/tests/unit/clients/test_abstract_client_memoryless.py:22-45` — `StubClient(AbstractClient)` pattern.

---

## Implementation Blueprint

### Steps (in order)
1. Create `parts.py` — *why*: every other file imports it; it is a stdlib leaf.
2. `policies.py`: `format_invocation_parts`, `PrunedInvocation.parts`, `_prune_shared`, `prune_turn_parts`, `prune_turn` delegating — *why*: parts originate here.
3. `compact.py`: `render_raw_parts` (+ extraction), `render_raw_view` delegating, views carry parts — *why*: RAW parts + the walk.
4. `models.py`: `TurnView.parts` — *why*: the carrier (done before step 3 compiles: do step 4 first if you prefer).
5. `render.py`: `HistoryMessage.parts`, `_iter_rows`, `render_history`, `_append` — *why*: the consumer.
6. `memory/__init__.py` exports; tests; mutation checks.

### `packages/ai-parrot/src/parrot/memory/parts.py` (CREATE)
```python
"""Structured message parts and the one canonical text formatter (FEAT-886 M16).

Leaf module: stdlib only. ``compaction`` produces already-budgeted parts and the text derived from them with
:func:`render_parts_text`; ``render_history`` carries both. Phase 1 sends only the text to providers.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional, Sequence

TOOL_ACTIVITY_OPEN = "\n\n<tool-activity>\n"
TOOL_ACTIVITY_CLOSE = "\n</tool-activity>"


@dataclass(frozen=True)
class MessagePart:
    """One structured piece of a rendered message.

    Attributes:
        kind: ``"text"``, ``"tool_use"`` (an invocation header line) or ``"tool_result"`` (its body).
        content: The rendered text of this part.
        tool_name: The tool a ``tool_use`` / ``tool_result`` part belongs to.
        tool_call_id: Always ``None`` in Phase 1 (``ToolInvocation`` has no call id).
    """

    kind: Literal["text", "tool_use", "tool_result"]
    content: str
    tool_name: Optional[str] = None
    tool_call_id: Optional[str] = None


def render_parts_text(parts: Sequence[MessagePart]) -> str:
    """The ONE canonical text rendering of tool parts.

    For the same invocations it returns exactly the string ``assistant_suffix`` holds today.

    Args:
        parts: Ordered parts of one turn's tool activity (``tool_use`` / ``tool_result`` / ``text``).

    Returns:
        ``""`` for no parts; otherwise the ``<tool-activity>`` block followed by any trailer text parts.
    """
    # FILL IN: implement the "canonical formatter (decided design)" from Implementation Notes — lines list, trailer list,
    #   tool_result appended to the previous line with " " (a tool_result with no previous line becomes its own line),
    #   text starting with "\n" -> trailer. Bounded by the byte-identity tests (AC-2, AC-3).
    raise NotImplementedError
```
**Why this shape**: names and fields are fixed by spec §2 Data Models / §3 M16. The two constants keep the wrapper in one place.

### `packages/ai-parrot/src/parrot/memory/compaction/policies.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from parrot.memory.compaction.omission import content_id' policies.py)  -> add BELOW it:
from parrot.memory.parts import MessagePart, render_parts_text

# occurrences: 1 (verified: grep -c '^class PrunedInvocation:' policies.py) -> REPLACE the class body (policies.py:33-37) with:
@dataclass(frozen=True)
class PrunedInvocation:
    """One invocation's rendered PRUNED-view line, plus any new omissions.

    ``parts`` are the ``tool_use`` + ``tool_result`` parts matching ``notice``; a custom policy may leave it empty
    (the caller then wraps ``notice`` in one ``text`` part).
    """

    notice: str
    omissions: Tuple[Omission, ...]
    parts: Tuple[MessagePart, ...] = ()

# occurrences: 1 (verified: grep -c '^def format_invocation_line' policies.py) -> add ABOVE it, and make format_invocation_line return
# " ".join(p.content for p in format_invocation_parts(inv, limit=limit, body=body)) (body unchanged otherwise):
def format_invocation_parts(inv: ToolInvocation, *, limit: Limit, body: str) -> Tuple[MessagePart, ...]:
    """The ``tool_use`` header part and, when ``body`` is non-empty, the ``tool_result`` part of one line."""
    # FILL IN: header = the existing f"- {inv.tool_name} {status_word}{elapsed} in={canonical_input}" computation moved here VERBATIM
    #   (status_word / elapsed / canonical_input truncation incl. the "…"); return (MessagePart("tool_use", header, inv.tool_name),) plus
    #   (MessagePart("tool_result", body, inv.tool_name),) iff body. Bounded by byte identity of format_invocation_line.

# In `_prune_shared` (policies.py:127) replace the last 3 lines
#     line = format_invocation_line(line_source, limit=limit, body=" ".join(p for p in parts if p))
#     return PrunedInvocation(line, tuple(omissions))
# with:
    line_parts = format_invocation_parts(line_source, limit=limit, body=" ".join(p for p in parts if p))
    return PrunedInvocation(" ".join(p.content for p in line_parts), tuple(omissions), line_parts)

# occurrences: 1 (verified: grep -c '^def prune_turn' policies.py) -> add `prune_turn_parts` BELOW prune_turn's imports and rewrite prune_turn:
def prune_turn_parts(
    turn: ConversationTurn,
    *,
    limit: Limit = Limit(),
    policies: Optional[Dict[str, PrunePolicy]] = None,
) -> Tuple[Tuple[MessagePart, ...], Tuple[Omission, ...]]:
    """PRUNED-view parts of a turn (``()`` for a turn with no invocations) plus new omissions. Pure."""
    # FILL IN: move the existing prune_turn loop here; per invocation extend `parts` with pruned.parts, or with
    #   (MessagePart("text", pruned.notice),) when pruned.parts is empty (custom policy); keep `has_notice`; when has_notice append the trailer
    #   MessagePart("text", "\nOmitted content can be recovered with read_omitted_content(content_id) "
    #   f'or read_omitted_content(turn_id="{turn.turn_id}").') — the exact existing hint string. Bounded by byte identity (AC-3).

def prune_turn(turn, *, limit=Limit(), policies=None) -> Tuple[str, Tuple[Omission, ...]]:
    """Render the PRUNED-view ``<tool-activity>`` suffix for a turn (signature and output unchanged)."""
    parts, omissions = prune_turn_parts(turn, limit=limit, policies=policies)
    return render_parts_text(parts), omissions
```
**Why**: the suffix becomes DERIVED from the parts, so `assistant_suffix == render_parts_text(parts)` holds by construction. `PrunePolicy.prune` is untouched.

### `packages/ai-parrot/src/parrot/memory/compaction/compact.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from parrot.memory.compaction.policies import PrunePolicy, format_invocation_line, get_policy, prune_turn' compact.py)
# REPLACE (compact.py:27) with:
from parrot.memory.compaction.policies import (
    PrunePolicy,
    format_invocation_parts,
    get_policy,
    prune_turn_parts,
)
from parrot.memory.parts import MessagePart, render_parts_text

# render_raw_view (compact.py:36-117): rename the body to `render_raw_parts(...)` returning (parts, omissions) and make render_raw_view:
def render_raw_view(turn, limit, *, oversize=(), policies=None, counter) -> Tuple[str, Tuple[Omission, ...]]:
    """RAW-view ``<tool-activity>`` suffix (signature and output unchanged) — derived from :func:`render_raw_parts`."""
    parts, omissions = render_raw_parts(turn, limit, oversize=oversize, policies=policies, counter=counter)
    return render_parts_text(parts), omissions

# FILL IN: render_raw_parts — same loop as today but each LINE is a group (tuple of MessagePart): oversize/offloaded invocation -> pruned.parts
#   (or (MessagePart("text", pruned.notice),) when empty); otherwise format_invocation_parts(inv, limit=limit, body=" ".join(parts)) with the existing
#   out=/error= body; overflow `… +N more` -> one text-part group; the token-collapse loop pops GROUPS (line text = " ".join(p.content ...)) exactly as it pops
#   lines today; flatten the groups; return () for a turn with no invocations. Extract `_raw_invocation_group(...)` and `_collapse_groups(...)` so each
#   function stays <= 60 lines / complexity <= 10. Bounded by byte identity vs the old render_raw_view (AC-3) and by spec §2 "RAW" rule.

# occurrences: 1 (verified: grep -c 'raw_suffix, raw_omissions = render_raw_view(' compact.py)  (compact.py:248) -> REPLACE the call with:
        raw_parts, raw_omissions = render_raw_parts(
# (keep its argument lines) and add right after the call:   raw_suffix = render_parts_text(raw_parts)
# occurrences: 1 (verified: grep -c 'pr_suffix, pr_omissions = prune_turn(turn, limit=budget.tool_activity_limit, policies=policies)' compact.py)  (:253) -> REPLACE with:
        pr_parts, pr_omissions = prune_turn_parts(turn, limit=budget.tool_activity_limit, policies=policies)
        pr_suffix = render_parts_text(pr_parts)
# occurrences: 1 each (verified: grep -c '                    assistant_suffix=raw_suffix,' / '...=pr_suffix,' compact.py) -> add a line below each:
                    parts=raw_parts or None,      # below `assistant_suffix=raw_suffix,`
                    parts=pr_parts or None,       # below `assistant_suffix=pr_suffix,`
```
**Why**: `render_tool_activity` (`HeuristicCounter` wrapper) keeps working through `render_raw_view`. `raw_size`/`pr_size` keep measuring `counter.count(<suffix>)`,
now provably the canonical text of the parts. `format_invocation_line` is no longer imported here — remove it from the import if ruff reports it unused.

### `packages/ai-parrot/src/parrot/memory/compaction/models.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    estimated_tokens: int' packages/ai-parrot/src/parrot/memory/compaction/models.py)
# AFTER — insert below `    estimated_tokens: int` inside TurnView (models.py:296):
    #: Already-budgeted parts for the assistant message; ``None`` when compaction is disabled or the turn has no
    #: tool activity. ``assistant_suffix == render_parts_text(parts)`` whenever it is set (FEAT-886).
    parts: Optional[Tuple[MessagePart, ...]] = None
# add the import below `from typing import Any, Dict, Optional, Tuple`:
from ..parts import MessagePart
```
**Why**: the last field has no default, so adding a defaulted field after it breaks no positional call site. `models.py` stays a leaf: `parts.py` is stdlib-only
(update the module docstring's "imports stdlib and orjson only" sentence to mention `parrot.memory.parts`).

### `packages/ai-parrot/src/parrot/memory/render.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '^from .abstract import ConversationHistory' render.py) -> add BELOW it:
from .parts import MessagePart

# HistoryMessage (render.py:54) — add the field after `turn_id: Optional[str] = None` and a docstring entry:
    parts: Optional[Tuple[MessagePart, ...]] = None
    # docstring: "parts: Structured view of ``content``. Informational in Phase 1 — clients send ``content`` only. Merged messages concatenate their parts in order."

# FILL IN: `_iter_rows` — yield a 5th element `parts`: for a view with `view.parts` set (and non-blank assistant text) ->
#   (MessagePart("text", assistant_text),) + tuple(view.parts); otherwise None. Plain ConversationHistory rows ALWAYS yield None (byte identity). Bounded by AC-3.
# FILL IN: `render_history` — unpack the 5-tuple; the foreign-agent label must precede text AND parts: when parts is set, replace parts[0] with
#   MessagePart("text", f"{label} {parts[0].content}"); the user message and `content` are unchanged; pass `parts=` to the assistant HistoryMessage only.
# FILL IN: `_append` merge — when either message has parts: merged.parts = (prev.parts or (MessagePart("text", prev.content),)) +
#   (MessagePart("text", _MERGE_SEPARATOR),) + (msg.parts or (MessagePart("text", msg.content),)); when both are None -> None (byte identity).
#   Bounded by "Merged messages concatenate their parts in order" and test_render_history.py (existing merge tests unchanged).
```
**Why**: `content` is already the concatenated canonical text; `parts` only mirrors it. `render.py` must not import `compaction` (existing AST test) — it imports `.parts` only.

### `packages/ai-parrot/src/parrot/memory/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from .render import HistoryMessage, render_history' memory/__init__.py)  (:27) -> add BELOW it:
from .parts import MessagePart, render_parts_text
# __all__ — occurrences 1 each: `"MemoryContext",` -> add after it:  "MessagePart",      `"render_history",` -> add after it:  "render_parts_text",
# (do NOT touch the persistence imports TASK-5569 added; verify `python -c "import parrot.memory as m; print(m.MessagePart)"`)
```

### `packages/ai-parrot/tests/unit/memory/compaction/test_history_parts.py` (CREATE)
```python
"""FEAT-886 M16 — budgeted parts: RAW / PRUNED / dropped, canonical text, byte identity, custom policy."""
from __future__ import annotations

import pytest

from parrot.memory.abstract import ConversationHistory, ConversationTurn
from parrot.memory.compaction.compact import compact_history
from parrot.memory.compaction.models import ContextBudget, ToolInvocation, ToolStatus, TurnState
from parrot.memory.compaction.policies import PrunedInvocation, register_policy
from parrot.memory.parts import MessagePart, render_parts_text
from parrot.memory.render import HistoryMessage, render_history
from parrot.memory.compaction.tokens import HeuristicCounter

# fixtures: reuse the conftest fixtures (`counter`, `budget`, `database_history`, `chatty_history`) and its make_turn pattern
# (tests/unit/memory/compaction/conftest.py) — do not edit that conftest; build any extra turn inline in this file.


def test_parts_raw_pruned_dropped():
    """RAW, PRUNED, oversized/offloaded and dropped turns produce the specified parts."""
    # FILL IN: database_history with a small budget so the walk yields RAW newest, PRUNED older, DROPPED oldest;
    #   RAW view: parts[0].kind == "tool_use" (tool_name set), tool_result carries `out=` text limited by tool_activity_limit;
    #   PRUNED view: tool_result contains `<tool-output-omitted` notice; an invocation with `error` keeps `error=` in the result part;
    #   a turn whose output was offloaded at write time (omitted={"output": "om_x"}) renders the notice via parts;
    #   dropped turn ids appear in result.dropped_turn_ids and in NO view/part. Bounded by AC-2.


def test_suffix_equals_rendered_parts():
    """assistant_suffix == render_parts_text(parts) for every view, and the token size measures that text."""
    # FILL IN: for each view with tool activity: view.parts is not None and view.assistant_suffix == render_parts_text(view.parts);
    #   estimated_tokens >= HeuristicCounter().count(view.assistant_suffix) (calibration 1.0 => equality with the recomputed size). Bounded by AC-3.
    #   Mutation: have compact_history count a different string than render_parts_text(parts) -> RED.


def test_disabled_compaction_byte_identical():
    """The plain path is unchanged: no parts, same messages as before this feature."""
    # FILL IN: render_history(ConversationHistory(...)) — every message `.parts is None`; output equals the pre-change expectation
    #   (compare with an explicit literal list of HistoryMessage(role, content, chatbot_id, turn_id)); a text-only TurnView list renders
    #   identically to the plain history (parts None). Bounded by AC-4.


def test_custom_policy_without_parts():
    """A custom policy returning no parts yields one text part holding its rendered line."""
    # FILL IN: class _NoParts: name="np"; def prune(self, inv, *, turn_id, limit): return PrunedInvocation("- np ok CUSTOM-LINE", ());
    #   register_policy("np_tool", _NoParts()) (restore the registry in a finally/monkeypatch); a PRUNED view of a turn using it has
    #   parts == (MessagePart("text", "- np ok CUSTOM-LINE"),) and suffix == render_parts_text(parts). Bounded by AC-5.


def test_history_message_parts_carry_and_merge():
    """render_history carries view.parts on the assistant message; merged messages concatenate parts in order; foreign label first."""
    # FILL IN: bounded by AC-3/AC-4; mutation: drop the parts concatenation in _append -> RED.
```
**Why this shape**: pure functions only — real `ConversationTurn` / `compact_history` / `render_history`, no doubles.

### `packages/ai-parrot/tests/unit/clients/test_format_history_consumes_content_once.py` (CREATE)
```python
"""FEAT-886 M16 — every _format_history emits message.content exactly once and never appends parts."""
from __future__ import annotations

import pytest

from parrot.memory.parts import MessagePart
from parrot.memory.render import HistoryMessage

SENTINEL = "ASSISTANT-CONTENT-ONCE"
PART_MARKER = "PART-ONLY-MARKER"


def _history() -> list[HistoryMessage]:
    """user + assistant message whose `parts` carry text that must never reach a provider."""
    return [
        HistoryMessage(role="user", content="question"),
        HistoryMessage(
            role="assistant",
            content=SENTINEL,
            parts=(MessagePart("text", SENTINEL), MessagePart("tool_use", PART_MARKER, tool_name="t")),
        ),
    ]


# FILL IN: parametrized over four classes, each resolved with pytest.importorskip:
#   AbstractClient (via a StubClient subclass as in tests/unit/clients/test_abstract_client_memoryless.py), BedrockConverseBase
#   (parrot.clients.amazon.bedrock), GoogleGenAIClient (parrot.clients.google.client), JevClient (parrot.clients.jev.client).
#   Obtain an instance WITHOUT network/credentials via `cls.__new__(cls)` where __init__ needs them (these `_format_history` bodies read no instance state);
#   flatten the formatted output to a string (repr / json) and assert: SENTINEL appears exactly once, PART_MARKER appears zero times,
#   and the message count equals the history length (Google skips blank content only). Bounded by AC-6.
#   Mutation: make one implementation also append `message.parts` -> that parametrization goes RED.
```

### FILL IN checklist
- [ ] `parts.py::render_parts_text` — bounded by byte identity (AC-2, AC-3).
- [ ] `policies.py::format_invocation_parts`, `_prune_shared` tail, `prune_turn_parts`, `prune_turn` — bounded by byte identity and AC-5.
- [ ] `compact.py::render_raw_parts` (+ extracted helpers ≤ 60 lines each) and the three edits in `compact_history`.
- [ ] `render.py::_iter_rows`, `render_history` label handling, `_append` part merge.
- [ ] Both test files' bodies; mutation checks recorded.
- [ ] `models.py` docstring sentence about the `parrot.memory.parts` import.

---

## Acceptance Criteria

- [ ] AC-1 (spec §5 "Composer and budgets"): `MessagePart`, `render_parts_text`, `TurnView.parts`, `PrunedInvocation.parts`, `HistoryMessage.parts` exist with the specified shapes; `tool_call_id` is `None` everywhere.
- [ ] AC-2: RAW, PRUNED, oversized/offloaded and dropped turns produce the specified parts; omission notices, errors and role alternation are preserved; dropped turns produce no view / message / parts / summary — `test_parts_raw_pruned_dropped`.
- [ ] AC-3: `assistant_suffix == render_parts_text(parts)` for every view with tool activity and the token count measures exactly that text — `test_suffix_equals_rendered_parts`.
- [ ] AC-4: with compaction disabled the output is byte-identical to today and `parts is None` — `test_disabled_compaction_byte_identical`; every existing test in `tests/unit/memory/compaction/` and `tests/unit/memory/test_render_history.py` passes unchanged.
- [ ] AC-5: a custom policy that returns no parts yields a single `text` part holding its rendered line — `test_custom_policy_without_parts`.
- [ ] AC-6: base, Bedrock, Google and Jev `_format_history` emit `content` once and never parts — `test_format_history_consumes_content_once`; `parrot/clients/base.py` is NOT modified.
- [ ] Mutation checks (record evidence): (1) make `render_parts_text` drop the trailer → PRUNED byte-identity RED; (2) count a different string than the canonical text in `compact_history` → AC-3 RED; (3) append `message.parts` in one `_format_history` (temporary, in the test via a subclass) → AC-6 RED; (4) drop the part concatenation in `_append` → merge test RED.
- [ ] `render.py` still imports nothing containing `compaction` at runtime (`test_render_imports_no_compaction`).
- [ ] FEAT-538 task recall (`HistoryMessage` without parts, `bots/abstract.py:2498`) still works: `pytest packages/ai-parrot/tests/unit/memory/test_render_history.py -q`.
- [ ] `ruff check` clean on all eight files; every touched function ≤ 60 lines / complexity ≤ 10.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/memory/compaction/test_history_parts.py -q`
- `pytest packages/ai-parrot/tests/unit/clients/test_format_history_consumes_content_once.py -q`
- `pytest packages/ai-parrot/tests/unit/memory/compaction/test_compact.py -q`
- `pytest packages/ai-parrot/tests/unit/memory/compaction/test_policies.py -q`
- `pytest packages/ai-parrot/tests/unit/memory/compaction/test_render_views.py -q`
- `pytest packages/ai-parrot/tests/unit/memory/test_render_history.py -q`
- `pytest packages/ai-parrot/tests/unit/memory/compaction/test_integration_round_trip.py -q`

---

## Test Specification

Spec §4 rows for M16 (fixtures are written inside the test files or reused from the existing compaction conftest — no shared conftest edits):

```python
def test_parts_raw_pruned_dropped(): ...                 # RAW, PRUNED, oversized/offloaded and dropped turns produce the specified parts
def test_suffix_equals_rendered_parts(): ...             # assistant_suffix == render_parts_text(parts); token count measures that text
def test_disabled_compaction_byte_identical(): ...       # plain path output unchanged, parts is None
def test_custom_policy_without_parts(): ...              # a policy returning no parts yields one text part
def test_history_message_parts_carry_and_merge(): ...    # (extra) renderer carries / merges parts; foreign label precedes
@pytest.mark.parametrize("client", ["base", "bedrock", "google", "jev"])
def test_format_history_consumes_content_once(client): ...   # base, bedrock, google and jev emit content once, never parts
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug durable-conversation-memory --feature-id FEAT-886`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — TASK-5569 must be `"done"` in `sdd/tasks/index/durable-conversation-memory.json` (it edits `memory/__init__.py` first)
4. **Verify the Codebase Contract** — re-run every `grep -c` above (all expected `1`); update the contract first if anything moved
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:`
7. **Verify** all acceptance criteria — run the Validation Commands and the four mutation checks
8. **Commit the code** — stage only the files this task lists
9. **Close the task** with `parrot sdd task close TASK-5572 durable-conversation-memory verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
