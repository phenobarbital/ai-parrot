# TASK-5573: ChatStorageTurn model and tolerant reader

**Feature**: FEAT-886 — Durable Conversation Memory
**Spec**: `sdd/specs/durable-conversation-memory.spec.md` (Module 3)
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5569, TASK-5570
**Assigned-to**: unassigned

---

## Context

ChatStorage today persists a degraded turn (`ChatStorage.save_turn` builds two `ChatMessage`
objects and a hand-rolled dict; tool calls collapse to `status="completed"`, `output=None`).
M3 introduces `ChatStorageTurn`, the single typed shape of one stored turn: the full
`ConversationTurn` plus a `TurnPresentation` (built by the bot, TASK-5569) and usage. It is
consumed by `ChatStorage.store_turn` / `handle_turn_completed` (TASK-5579), by
`ChatStorageHydrationSource` (TASK-5582) and by the backfill driver's readers. This task is
the model and its (de)serialization only: no storage I/O.

---

## Scope

- Add `ChatStorageTurn` (Pydantic v2) to `storage/models.py` with the exact fields of spec §2 Data Models.
- `from_event_payload(payload)`: build from a `TurnCompletedEvent` payload dict; raise `InvalidTurnPayloadError` (permanent) on a missing identity field or a missing/unparseable timestamp.
- `from_row(row)`: tolerant reader. Rows without `schema_version` are legacy: missing fields default, legacy `tool_calls` map to `tool_invocations`, `schema_version` is reported as `1`.
- `to_row()`: JSON-safe dict for `ConversationBackend.put_turn`; `timestamp` as ISO-8601 UTC and `sequence` are the keys the backends (TASK-5574..5577) read to build their chronological index.
- `to_conversation_turn()`: project onto `ConversationTurn` (presentation dropped).
- `to_messages()`: the user + assistant message dicts `ChatStorage.load_conversation` returns today, plus the richer fields.
- Export `ChatStorageTurn` from `parrot.storage`.
- Unit tests.

**NOT in scope**: `ChatStorage.store_turn`, the bus handler, tombstones (TASK-5579); reading rows from a backend (TASK-5582); `TurnPresentation` itself and `ConversationTurn.sequence` (TASK-5569); `parrot.storage.errors` (TASK-5570); removing `ChatMessage`/`ToolCall`/`Source` (they stay: `ChatStorage.save_turn` is removed in TASK-5579, the dataclasses are still imported by `chat.py` and other modules).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/storage/models.py` | MODIFY | Add `ChatStorageTurn`, `_parse_utc`, `_json_safe`, legacy tool-call mapper |
| `packages/ai-parrot/src/parrot/storage/__init__.py` | MODIFY | Export `ChatStorageTurn` |
| `packages/ai-parrot/tests/unit/storage/test_chat_storage_turn.py` | CREATE | Unit tests (tolerant reader, invalid payloads, round trips) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.memory.abstract import ConversationTurn                         # verified: memory/abstract.py:102
from parrot.memory.compaction.models import (                               # verified: memory/compaction/models.py:24,31,46,~100
    ToolInvocation, ToolStatus, TokenCount, TurnState)
from pydantic import BaseModel, ConfigDict, Field, field_validator          # pydantic 2.12.5 installed (.venv); BaseModel, Field already imported at storage/models.py:15
# --- created by dependency tasks (read their completion notes; do NOT assume more than listed) ---
from parrot.memory.persistence import TurnPresentation                      # TASK-5569: new module parrot/memory/persistence.py
from parrot.storage.errors import InvalidTurnPayloadError                   # TASK-5570: new module parrot/storage/errors.py
```

Import-cycle check (done when writing this task): nothing under `parrot/memory/` imports
`parrot.storage` (`grep -rn "parrot.storage\|from \.\.storage" packages/ai-parrot/src/parrot/memory` is empty),
and `storage/chat.py:16` already imports `..memory.render` at module level, so a module-level
`from parrot.memory...` import in `storage/models.py` is safe. Re-run the grep when implementing.

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/memory/abstract.py
@dataclass
class ConversationTurn:                                        # :102
    turn_id: str; user_id: str; user_message: str; assistant_response: str   # :105-108
    context_used: Optional[str] = None                         # :109
    tools_used: List[str] = field(default_factory=list)        # :110
    timestamp: datetime = field(default_factory=datetime.now)  # :111  naive local time today
    metadata: Dict[str, Any] = field(default_factory=dict)     # :112
    chatbot_id: Optional[str] = None                           # :116
    tool_invocations: List[ToolInvocation]                     # :119
    error: Optional[str] = None                                # :121
    token_count: Optional[TokenCount] = None                   # :124
    state: TurnState = TurnState.RAW                           # :127
    schema_version: int = 1                                    # :129  turn-level, NOT the row version
    norm_version: Optional[str] = None                         # :132
    sequence: Optional[int] = None                             # ADDED by TASK-5569
    def to_dict(self) -> Dict[str, Any]                        # :134  timestamp.isoformat(), tool_invocations as dicts
    @classmethod
    def from_dict(cls, data) -> "ConversationTurn"             # :155

# packages/ai-parrot/src/parrot/memory/compaction/models.py
class ToolInvocation:                                          # :46
    tool_name; input; output; status: ToolStatus; error; elapsed_ms; output_chars; omitted; wm_key
    def to_dict(self) -> Dict[str, Any]                        # :78
    @classmethod
    def from_dict(cls, data) -> "ToolInvocation"               # :91
class TokenCount:                                              # frozen; .to_dict() / .from_dict()  (used at abstract.py:148,171)

# packages/ai-parrot/src/parrot/storage/models.py
def _safe_serialize(obj: Any) -> Any                           # :224  returns objects UNCHANGED unless they have to_dict/to_json — NOT JSON-safe
class ChatMessage / ToolCall / Source                          # :73 / :26 / :54  legacy dataclasses, untouched

# Legacy cold row written by ChatStorage._save_to_dynamodb (storage/chat.py:228-242)
# keys: user_message, assistant_response, timestamp (ISO str), output, output_mode, data, code, model,
#       provider, response_time_ms, tool_calls=[{name,status,output,arguments}], sources=[{content,metadata}], metadata
# Backends add: session_id, turn_id, updated_at.  user_id / agent_id are NOT in the payload (they are key parts).

# Legacy load_conversation message shape (storage/chat.py:347-375) — to_messages() must keep these keys:
#   user:      role, content, timestamp, turn_id
#   assistant: role, content, timestamp, turn_id, output, output_mode, data, code, model, provider,
#              response_time_ms, tool_calls, sources, metadata
```

### Does NOT Exist

- ~~`ChatStorageTurn`~~, ~~`TurnPresentation`~~ (until TASK-5569), ~~`parrot.storage.errors`~~ (until TASK-5570) — none exists on the base branch.
- ~~`ConversationTurn.sequence`~~ — added by TASK-5569; do not add it here.
- ~~`ChatStorageTurn.save` / `.store`~~ — the model does no I/O.
- ~~`ChatMessage.to_row`~~ — unrelated legacy dataclass; do not extend it.
- ~~A timestamp column/field on legacy rows guaranteed to parse~~ — legacy rows may lack it or hold garbage; the reader must not raise on it.
- `from_row(row, *, user_id=..., ...)` keyword args are an ADDITIVE extension of the spec skeleton (legacy rows carry no user/agent key); see Implementation Notes.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/storage/models.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/storage/__init__.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/unit/storage/test_chat_storage_turn.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/memory/abstract.py#ConversationTurn",
    "sym:packages/ai-parrot/src/parrot/memory/compaction/models.py#ToolInvocation",
    "sym:packages/ai-parrot/src/parrot/memory/compaction/models.py#TokenCount",
    "sym:packages/ai-parrot/src/parrot/storage/models.py#_safe_serialize"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow

Pydantic models in the same module (`ArtifactSummary`, `Artifact`, `ThreadMetadata` at `storage/models.py:263-402`). Google-style docstrings, strict type hints.

### Key Constraints

- **Pydantic v2** (`model_dump`, `model_validate`, `field_validator`). No `class Config`.
- **The model does no I/O** and imports nothing from `parrot.storage.chat` (that would create a cycle: `chat.py` imports `models.py`).
- **UTC everywhere** (spec §7 Timestamps): `timestamp` is always tz-aware UTC after validation; a naive input is treated as UTC (the tolerant reader and the event path alike); a non-UTC aware input is converted with `astimezone(timezone.utc)`.
- **Two version numbers, do not mix them**: `ChatStorageTurn.schema_version` (row shape: `2` current, `1` = legacy row read by the tolerant reader) vs `ConversationTurn.schema_version` (turn shape, stamped by `add_turn`). The event's `turn["schema_version"]` is the second kind: ignore it for the row version. `to_conversation_turn()` leaves the turn-level one at its default (`add_turn` restamps it when hydration stages the turn, TASK-5580).
- **Row layout (decision, bounded by spec §3 M3 "(de)serialization to the backend dict payload")**: `to_row()` writes every `ChatStorageTurn` field at the top level EXCEPT `presentation`, which is nested under the key `"presentation"` (no flat mirror of its fields: one source of truth). `from_row` accepts both this layout and the legacy flat layout (`output`, `output_mode`, `data`, `code`, `model`, `provider`, `response_time_ms`, `sources` at the top level).
- **JSON-safe**: the row must survive `json.dumps` (SQLite) and be storable as JSONB / BSON / DynamoDB. `presentation.output` / `.data` are `Any` and may hold DataFrames or custom objects: run the dumped dict through `_json_safe` (`json.loads(json.dumps(obj, default=_json_default))`; `_json_default` handles `datetime` → `isoformat()`, objects with `to_dict`/`model_dump`, `Decimal` → int/float, everything else → `str`). Do not use `_safe_serialize` for this (it returns objects unchanged). Floats become Decimal only inside the DynamoDB backend (TASK-5577), never here.
- **Legacy timestamp fallback (decision)**: if a legacy row has no parseable `timestamp`, fall back to the row's `updated_at` when parseable, otherwise to `datetime(1970, 1, 1, tzinfo=timezone.utc)`, and set `metadata["legacy_timestamp_missing"] = True`. The reader must never raise on a legacy row; it must never invent a chronology that looks real (hydration additionally refuses such sessions: the backend reports the index `invalid`).
- **Invalid event payloads are permanent**: wrap every `pydantic.ValidationError`, `TypeError`, `ValueError` raised while building from an event payload in `InvalidTurnPayloadError` (message names the offending field and the `turn_id` when known). `ChatStorage.handle_turn_completed` (TASK-5579) acknowledges these without retry.

### References in Codebase

- `packages/ai-parrot/src/parrot/memory/abstract.py:134-175` — `ConversationTurn.to_dict` / `from_dict` (the event's `turn` dict has exactly this shape).
- `packages/ai-parrot/src/parrot/storage/chat.py:228-242, 347-375` — legacy row and legacy message shapes this model must read and re-emit.
- `sdd/specs/durable-conversation-memory.spec.md` §2 "Piece 3", §3 Module 3, §7 "Timestamps".

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. Never change a signature,
> class name, or file path the blueprint fixes.

### Steps (in order)
1. Confirm TASK-5569 and TASK-5570 are `done`; read `parrot/memory/persistence.py` and `parrot/storage/errors.py` and confirm `TurnPresentation` fields and `InvalidTurnPayloadError` exist as in the spec — *why*: this task imports both and must not guess.
2. Add the imports and the three private helpers to `storage/models.py` — *why*: `from_row`/`from_event_payload`/`to_row` share them.
3. Add `ChatStorageTurn` below `CanvasDefinition` (end of module) — *why*: keeps the existing public classes untouched and avoids forward references.
4. Export `ChatStorageTurn` from `storage/__init__.py` — *why*: spec §3 M3 / TASK-5579 import it from `parrot.storage`.
5. Write the unit tests, then run the mutation checks listed under Acceptance Criteria — *why*: Rule 6 of ARCHITECTURE.md.

### `packages/ai-parrot/src/parrot/storage/models.py` (MODIFY) — imports and helpers
```python
# occurrences: 1 (verified: grep -c 'from pydantic import BaseModel, Field' packages/ai-parrot/src/parrot/storage/models.py)
# BEFORE (models.py:15):  from pydantic import BaseModel, Field
# AFTER — replace that line with:
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

# occurrences: 1 (verified: grep -c 'from typing import List, Dict, Any, Optional' ...)  models.py:10
# AFTER — replace with:
from typing import List, Dict, Any, Mapping, Optional

# occurrences: 1 (verified: grep -c 'from datetime import datetime' ...)  models.py:12
# AFTER — replace with:
from datetime import datetime, timezone
# AFTER — add directly below the pydantic import (module scope):
import json
from decimal import Decimal

from parrot.memory.abstract import ConversationTurn
from parrot.memory.compaction.models import TokenCount, ToolInvocation, TurnState
from parrot.memory.persistence import TurnPresentation          # TASK-5569
from .errors import InvalidTurnPayloadError                     # TASK-5570
```
**Why**: new imports only; `ChatMessage`/`ToolCall`/`Source` keep working. If `from .errors import` triggers a cycle (it must not: `errors.py` only imports `parrot.exceptions`), import it lazily inside `from_event_payload`.

### `packages/ai-parrot/src/parrot/storage/models.py` (MODIFY) — helpers (append at end of module)
```python
_EPOCH_SENTINEL = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _parse_utc(value: Any) -> Optional[datetime]:
    """Parse ``value`` into a tz-aware UTC datetime, or ``None`` when absent/unparseable.

    Naive datetimes and naive ISO strings are interpreted as UTC (spec §7).
    """
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip())
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _json_default(obj: Any) -> Any:
    """``json.dumps`` fallback: datetimes, model-ish objects, Decimals, then ``str``."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return int(obj) if obj == obj.to_integral_value() else float(obj)
    for attr in ("model_dump", "to_dict"):
        method = getattr(obj, attr, None)
        if callable(method):
            return method()
    return str(obj)


def _json_safe(obj: Any) -> Any:
    """Round-trip ``obj`` through JSON so the result holds only JSON types."""
    return json.loads(json.dumps(obj, default=_json_default))


_FAILED_TOOL_STATUSES = {"error", "failed", "failure"}


def _legacy_tool_call_to_invocation(call: Mapping[str, Any]) -> Dict[str, Any]:
    """Map a legacy ``{name, status, output, arguments}`` tool call onto ``ToolInvocation.to_dict()``."""
    output = call.get("output")
    if output is not None and not isinstance(output, str):
        output = json.dumps(output, default=_json_default, sort_keys=True)
    failed = str(call.get("status", "completed")).lower() in _FAILED_TOOL_STATUSES
    return ToolInvocation(
        tool_name=str(call.get("name") or "unknown"),
        input=dict(call.get("arguments") or {}),
        output=output,
        status=ToolStatus.ERROR if failed else ToolStatus.COMPLETED,
        error=(output if failed else None),
    ).to_dict()
```
**Why**: `ToolStatus` must be imported too — extend the memory import above to `ToolInvocation, ToolStatus, TokenCount, TurnState` (all four verified at `memory/compaction/models.py`). The legacy mapper keeps `status="completed"` rows as completed (the old handler wrote that for every call), and only marks a call failed when the legacy row says so.

### `packages/ai-parrot/src/parrot/storage/models.py` (MODIFY) — the model (append after the helpers)
```python
class ChatStorageTurn(BaseModel):
    """Full audit record of one conversation turn (spec FEAT-886 §2 Data Models).

    ``agent_id`` is the agent NAME (the ChatStorage key); ``chatbot_id`` is the bot's
    ``memory_key_id`` and may differ. ``timestamp`` and ``sequence`` are emitter-owned
    and immutable once stored.
    """

    model_config = ConfigDict(extra="ignore")

    schema_version: int = 2
    turn_id: str
    user_id: str
    session_id: str
    agent_id: str
    chatbot_id: Optional[str] = None
    timestamp: datetime
    sequence: int = 0
    user_message: str
    assistant_response: str
    context_used: Optional[str] = None
    tools_used: List[str] = Field(default_factory=list)
    tool_invocations: List[Dict[str, Any]] = Field(default_factory=list)
    error: Optional[str] = None
    token_count: Optional[Dict[str, Any]] = None
    state: str = "raw"
    norm_version: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    presentation: TurnPresentation = Field(default_factory=TurnPresentation)

    @field_validator("timestamp", mode="after")
    @classmethod
    def _force_utc(cls, value: datetime) -> datetime:
        """Naive → UTC, aware → converted to UTC."""
        return _parse_utc(value) or value

    @classmethod
    def from_event_payload(cls, payload: Dict[str, Any]) -> "ChatStorageTurn":
        """Build from a ``TurnCompletedEvent`` payload.

        Raises:
            InvalidTurnPayloadError: ``turn_id``, ``user_id``, ``session_id``, ``agent_name``
                or a parseable timestamp is missing (permanent defect — never retried).
        """
        turn = payload.get("turn") if isinstance(payload, dict) else None
        if not isinstance(turn, dict):
            raise InvalidTurnPayloadError("turn event payload has no 'turn' object")
        ident = {
            "turn_id": turn.get("turn_id"),
            "user_id": payload.get("user_id") or turn.get("user_id"),
            "session_id": payload.get("session_id"),
            "agent_name": payload.get("agent_name"),
        }
        missing = [name for name, value in ident.items() if not value]
        timestamp = _parse_utc(turn.get("timestamp"))
        if missing or timestamp is None:
            bad = missing + ([] if timestamp else ["timestamp"])
            raise InvalidTurnPayloadError(
                f"turn {ident['turn_id']!r}: missing or invalid {', '.join(bad)}")
        try:
            return cls(
                turn_id=ident["turn_id"], user_id=ident["user_id"],
                session_id=ident["session_id"], agent_id=ident["agent_name"],
                chatbot_id=payload.get("chatbot_id") or turn.get("chatbot_id") or None,
                timestamp=timestamp, sequence=int(turn.get("sequence") or 0),
                user_message=turn.get("user_message", ""),
                assistant_response=turn.get("assistant_response", ""),
                context_used=turn.get("context_used"),
                tools_used=list(turn.get("tools_used") or []),
                tool_invocations=list(turn.get("tool_invocations") or []),
                error=turn.get("error"), token_count=turn.get("token_count"),
                state=str(turn.get("state") or "raw"), norm_version=turn.get("norm_version"),
                metadata=dict(turn.get("metadata") or {}),
                presentation=TurnPresentation.model_validate(payload.get("presentation") or {}),
            )
        except (ValidationError, TypeError, ValueError) as exc:
            raise InvalidTurnPayloadError(f"turn {ident['turn_id']!r}: {exc}") from exc
```
**Why**: the five identity checks are exactly the ones the spec lists. Nothing here swallows an error: every defect becomes `InvalidTurnPayloadError`.

```python
    @classmethod
    def from_row(cls, row: Dict[str, Any], *, user_id: str = "", agent_id: str = "",
                 session_id: str = "") -> "ChatStorageTurn":
        """Tolerant reader for rows written before and after FEAT-886.

        A row carrying ``schema_version >= 2`` is the current layout. A row without it is
        legacy: missing fields default, ``tool_calls`` map to ``tool_invocations`` and the
        reported ``schema_version`` is ``1``. ``user_id`` / ``agent_id`` / ``session_id`` are
        used only when the row itself does not carry them (legacy rows don't: they are key
        parts of the backend row).
        """
        if int(row.get("schema_version") or 1) >= 2:
            data = {k: v for k, v in row.items() if k != "updated_at"}
            data.setdefault("user_id", user_id)
            data.setdefault("agent_id", agent_id)
            data.setdefault("session_id", session_id)
            return cls.model_validate(data)
        return cls._from_legacy_row(row, user_id, agent_id, session_id)

    @classmethod
    def _from_legacy_row(cls, row: Dict[str, Any], user_id: str, agent_id: str,
                         session_id: str) -> "ChatStorageTurn":
        """Map the pre-FEAT-886 flat layout onto the model (``schema_version=1``)."""
        metadata = dict(row.get("metadata") or {})
        timestamp = _parse_utc(row.get("timestamp"))
        if timestamp is None:
            timestamp = _parse_utc(row.get("updated_at")) or _EPOCH_SENTINEL
            metadata["legacy_timestamp_missing"] = True
        calls = [c for c in (row.get("tool_calls") or []) if isinstance(c, dict)]
        return cls(
            schema_version=1,
            turn_id=str(row.get("turn_id") or ""),
            user_id=str(row.get("user_id") or user_id),
            session_id=str(row.get("session_id") or session_id),
            agent_id=str(row.get("agent_id") or agent_id),
            timestamp=timestamp,
            sequence=0,
            user_message=row.get("user_message") or "",
            assistant_response=row.get("assistant_response") or "",
            tools_used=[str(c.get("name") or "unknown") for c in calls],
            tool_invocations=[_legacy_tool_call_to_invocation(c) for c in calls],
            metadata=metadata,
            presentation=TurnPresentation(
                output=row.get("output"), output_mode=row.get("output_mode"),
                data=row.get("data"), code=row.get("code"),
                sources=list(row.get("sources") or []),
                response_time_ms=row.get("response_time_ms"),
                model=row.get("model"), provider=row.get("provider"),
            ),
        )
```
**Why**: legacy rows have random turn ids, no sequence (`0`), no usage. `schema_version=1` is passed explicitly so a legacy row never reports `2`. If the row has `schema_version` but its value is not an int, let pydantic raise: that is a corrupt row, not a legacy one.

```python
    def to_row(self) -> Dict[str, Any]:
        """JSON-safe dict for ``ConversationBackend.put_turn``.

        ``timestamp`` is ISO-8601 UTC and ``sequence`` an int: the backends derive their
        chronological index from exactly these two keys.
        """
        row = _json_safe(self.model_dump(exclude={"presentation"}))
        row["timestamp"] = self.timestamp.astimezone(timezone.utc).isoformat()
        row["presentation"] = _json_safe(self.presentation.model_dump())
        return row

    def to_conversation_turn(self) -> ConversationTurn:
        """Project onto the working-memory turn; ``presentation`` is dropped."""
        return ConversationTurn(
            turn_id=self.turn_id, user_id=self.user_id,
            user_message=self.user_message, assistant_response=self.assistant_response,
            context_used=self.context_used, tools_used=list(self.tools_used),
            timestamp=self.timestamp, metadata=dict(self.metadata),
            chatbot_id=self.chatbot_id,
            tool_invocations=[ToolInvocation.from_dict(d) for d in self.tool_invocations],
            error=self.error,
            token_count=TokenCount.from_dict(self.token_count) if self.token_count else None,
            state=TurnState(self.state), norm_version=self.norm_version,
            sequence=self.sequence or None,
        )
```
**Why**: `sequence=self.sequence or None` keeps legacy turns (stored as `0`) as "unknown sequence" in working memory, matching `ConversationTurn.sequence`'s contract ("None on legacy turns").

```python
    def to_messages(self) -> List[Dict[str, Any]]:
        """The user + assistant dicts ``ChatStorage.load_conversation`` returns, with rich fields."""
        stamp = self.timestamp.astimezone(timezone.utc).isoformat()
        p = self.presentation
        legacy_calls = [
            {"name": inv.get("tool_name"), "status": inv.get("status", "completed"),
             "output": inv.get("output"), "arguments": inv.get("input")}
            for inv in self.tool_invocations
        ]
        user = {"role": MessageRole.USER.value, "content": self.user_message,
                "timestamp": stamp, "turn_id": self.turn_id}
        assistant = {
            "role": MessageRole.ASSISTANT.value, "content": self.assistant_response,
            "timestamp": stamp, "turn_id": self.turn_id,
            "output": p.output, "output_mode": p.output_mode, "data": p.data, "code": p.code,
            "model": p.model, "provider": p.provider, "response_time_ms": p.response_time_ms,
            "tool_calls": legacy_calls, "sources": list(p.sources), "metadata": dict(self.metadata),
            # --- FEAT-886 rich fields ---
            "tools_used": list(self.tools_used), "tool_invocations": list(self.tool_invocations),
            "usage": p.usage, "cost_usd": p.cost_usd, "tenant": p.tenant, "error": self.error,
            "sequence": self.sequence, "schema_version": self.schema_version,
        }
        return [user, assistant]
```
**Why**: every legacy key stays so UI consumers don't break; new keys are additive. `TASK-5579` decides how `load_conversation` surfaces them.

### `packages/ai-parrot/src/parrot/storage/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from .models import ChatMessage, Conversation' packages/ai-parrot/src/parrot/storage/__init__.py)  -> line 4
# BEFORE: from .models import ChatMessage, Conversation
# AFTER:  from .models import ChatMessage, ChatStorageTurn, Conversation

# occurrences: 1 (verified: grep -c '    "ChatMessage",' ...)  -> line 32 (inside __all__)
# AFTER — add directly below it:
    "ChatStorageTurn",
```
**Why**: `TASK-5570` also edits this file (error exports, `BackfillBatch`): both edits are additive lines; re-read the file before editing and keep theirs.

### FILL IN checklist
- [ ] `storage/models.py::ChatStorageTurn.from_event_payload` — the exact message text of `InvalidTurnPayloadError`; bounded by "must name the field and the turn_id" (AC-M3-2).
- [ ] `storage/models.py::ChatStorageTurn._from_legacy_row` — the `error` text of a failed legacy tool call (blueprint uses the output); bounded by "never raises on a legacy row".
- [ ] `storage/models.py::_json_default` — whether `set`/`bytes` need handling; bounded by "result must `json.dumps` cleanly" (add a test for each type you handle).
- [ ] `tests/unit/storage/test_chat_storage_turn.py` — the concrete `TurnPresentation` kwargs: read `parrot/memory/persistence.py` (TASK-5569) and use its real field names.

---

## Acceptance Criteria

- [ ] `ChatStorageTurn` has exactly the fields of spec §2 Data Models, `schema_version` defaults to `2` (spec §4 `test_chat_storage_turn_tolerant_reader`).
- [ ] A pre-FEAT-886 row loads without raising, reports `schema_version == 1`, maps legacy `tool_calls` to `tool_invocations`, defaults `sequence` to `0` and fills the presentation from the flat keys (AC "Rich turns": pre-existing rows still load).
- [ ] `from_event_payload` raises `InvalidTurnPayloadError` for each of: missing `turn_id`, `user_id`, `session_id`, `agent_name`, missing timestamp, unparseable timestamp, non-dict `turn` (spec §4 `test_chat_storage_turn_invalid_payload`).
- [ ] `ChatStorageTurn.from_row(turn.to_row()) == turn` for a v2 row; `to_row()` output passes `json.dumps` even when `presentation.output`/`data` hold non-JSON objects.
- [ ] `timestamp` is UTC-aware after construction from a naive value; `to_row()["timestamp"]` ends with `+00:00`.
- [ ] `to_conversation_turn()` drops presentation and returns typed `ToolInvocation`s and `TokenCount`; `sequence` round-trips (`0` → `None`).
- [ ] `to_messages()` keeps every key of the legacy message shape (contract section) and adds the rich fields.
- [ ] `ChatStorageTurn` importable from `parrot.storage`; `ruff check` clean on the three files.
- [ ] **Mutation checks** (record the result in the Completion Note): (1) remove `_force_utc` → `test_naive_timestamp_becomes_utc` RED; (2) make `from_row` ignore the legacy branch (always `model_validate`) → `test_legacy_row_loads_as_schema_version_1` RED; (3) drop `timestamp` from the identity check in `from_event_payload` → `test_invalid_payload[missing-timestamp]` RED; (4) replace `_json_safe` with the identity function → `test_to_row_is_json_safe` RED.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/storage/test_chat_storage_turn.py -q`
- `pytest packages/ai-parrot/tests/unit/storage/test_chat_hot_tier_metadata.py -q`

---

## Test Specification

> Fixtures live inside the test file (no shared conftest edits). No Mock objects: events are
> built from real `ConversationTurn.to_dict()` and real `TurnPresentation`.

```python
# packages/ai-parrot/tests/unit/storage/test_chat_storage_turn.py
import json
from datetime import datetime, timezone

import pytest

from parrot.memory.abstract import ConversationTurn
from parrot.memory.compaction.models import ToolInvocation, ToolStatus
from parrot.memory.persistence import TurnPresentation
from parrot.storage import ChatStorageTurn
from parrot.storage.errors import InvalidTurnPayloadError

UTC = timezone.utc


def _event_payload(**overrides):
    turn = ConversationTurn(
        turn_id="t-1", user_id="u-1", user_message="hi", assistant_response="hello",
        timestamp=datetime(2026, 11, 1, 10, 0, 0, tzinfo=UTC), chatbot_id="bot-uuid",
        tool_invocations=[ToolInvocation(tool_name="search", input={"q": "x"}, output="r",
                                         status=ToolStatus.COMPLETED, elapsed_ms=12)],
        tools_used=["search"], sequence=7,
    )
    payload = {
        "agent_name": "MyAgent", "chatbot_id": "bot-uuid", "user_id": "u-1", "session_id": "s-1",
        "turn": turn.to_dict(),
        "presentation": TurnPresentation(
            output="hello", output_mode="markdown", tenant="acme",
            usage={"input_tokens": 3, "output_tokens": 5}, cost_usd=0.0021,
            model="m", provider="p").model_dump(),
    }
    payload.update(overrides)
    return payload


@pytest.fixture
def legacy_row():
    return {
        "session_id": "s-1", "turn_id": "9f8e7d", "updated_at": "2026-05-01T00:00:00+00:00",
        "user_message": "q", "assistant_response": "a", "timestamp": "2026-05-01T09:30:00",
        "output": "a", "output_mode": "markdown", "data": None, "code": None,
        "model": "m", "provider": "p", "response_time_ms": 120,
        "tool_calls": [{"name": "search", "status": "completed", "output": {"k": 1}, "arguments": {"q": "x"}}],
        "sources": [{"content": "c", "metadata": {}}], "metadata": {"k": "v"},
    }


class TestTolerantReader:
    def test_legacy_row_loads_as_schema_version_1(self, legacy_row):
        turn = ChatStorageTurn.from_row(legacy_row, user_id="u-1", agent_id="MyAgent")
        assert turn.schema_version == 1
        assert (turn.user_id, turn.agent_id, turn.session_id) == ("u-1", "MyAgent", "s-1")
        assert turn.sequence == 0
        assert turn.tool_invocations[0]["tool_name"] == "search"
        assert turn.tool_invocations[0]["input"] == {"q": "x"}
        assert turn.presentation.model == "m" and turn.presentation.response_time_ms == 120
        assert turn.timestamp.tzinfo is not None   # naive stored timestamp read as UTC

    def test_legacy_row_with_garbage_timestamp_does_not_raise(self, legacy_row):
        legacy_row["timestamp"] = "not-a-date"
        turn = ChatStorageTurn.from_row(legacy_row, user_id="u", agent_id="a")
        assert turn.metadata["legacy_timestamp_missing"] is True

    def test_v2_round_trip(self):
        original = ChatStorageTurn.from_event_payload(_event_payload())
        again = ChatStorageTurn.from_row(original.to_row())
        assert again == original and again.schema_version == 2

    def test_to_row_is_json_safe(self):
        payload = _event_payload()
        payload["presentation"]["data"] = {"obj": object()}   # not JSON-serializable
        row = ChatStorageTurn.from_event_payload(payload).to_row()
        json.dumps(row)                                        # must not raise
        assert row["timestamp"].endswith("+00:00") and row["sequence"] == 7


class TestEventPayload:
    def test_happy_path_keeps_both_ids_and_tenant(self):
        turn = ChatStorageTurn.from_event_payload(_event_payload())
        assert turn.agent_id == "MyAgent" and turn.chatbot_id == "bot-uuid"
        assert turn.sequence == 7 and turn.presentation.tenant == "acme"
        assert turn.tool_invocations[0]["elapsed_ms"] == 12

    def test_naive_timestamp_becomes_utc(self):
        payload = _event_payload()
        payload["turn"]["timestamp"] = "2026-11-01T10:00:00"
        assert ChatStorageTurn.from_event_payload(payload).timestamp.utcoffset().total_seconds() == 0

    @pytest.mark.parametrize("field", ["agent_name", "session_id", "user_id"])
    def test_invalid_payload_missing_identity(self, field):
        payload = _event_payload(**{field: ""})
        if field == "user_id":
            payload["turn"]["user_id"] = ""    # from_event_payload falls back to turn["user_id"]
        with pytest.raises(InvalidTurnPayloadError):
            ChatStorageTurn.from_event_payload(payload)

    @pytest.mark.parametrize("bad", [None, "", "nope"])
    def test_invalid_payload_timestamp(self, bad):
        payload = _event_payload()
        payload["turn"]["timestamp"] = bad
        with pytest.raises(InvalidTurnPayloadError):
            ChatStorageTurn.from_event_payload(payload)

    def test_invalid_payload_missing_turn_id_and_turn_object(self):
        payload = _event_payload()
        payload["turn"]["turn_id"] = ""
        with pytest.raises(InvalidTurnPayloadError):
            ChatStorageTurn.from_event_payload(payload)
        with pytest.raises(InvalidTurnPayloadError):
            ChatStorageTurn.from_event_payload({"agent_name": "a", "user_id": "u", "session_id": "s"})


class TestProjections:
    def test_to_conversation_turn_drops_presentation(self):
        turn = ChatStorageTurn.from_event_payload(_event_payload()).to_conversation_turn()
        assert isinstance(turn, ConversationTurn) and turn.sequence == 7
        assert isinstance(turn.tool_invocations[0], ToolInvocation)
        assert not hasattr(turn, "presentation")

    def test_to_messages_keeps_legacy_keys(self):
        user, assistant = ChatStorageTurn.from_event_payload(_event_payload()).to_messages()
        assert set(user) == {"role", "content", "timestamp", "turn_id"}
        for key in ("output", "output_mode", "data", "code", "model", "provider",
                    "response_time_ms", "tool_calls", "sources", "metadata"):
            assert key in assistant
        assert assistant["tool_calls"][0]["name"] == "search"
        assert assistant["tenant"] == "acme"
```
`# FILL IN: add the mutation-check variants (see Acceptance Criteria) as comments next to the tests they
turn RED — bounded by Rule 6 of ARCHITECTURE.md (each new assertion is mutation-checked).`

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug durable-conversation-memory --feature-id FEAT-886`)
2. **Read the spec** at `sdd/specs/durable-conversation-memory.spec.md` (§2 Piece 3, §3 Module 3, §7)
3. **Check dependencies** — TASK-5569 and TASK-5570 must be `"done"` in `sdd/tasks/index/durable-conversation-memory.json`
4. **Verify the Codebase Contract** — before writing ANY code, confirm every import and signature above (especially `TurnPresentation` and `InvalidTurnPayloadError`, created by the dependencies); update the contract first if something changed
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the Blueprint; complete every `# FILL IN:`; never change a fixed signature or path
7. **Verify** all acceptance criteria and run the Validation Commands; record the mutation-check results
8. **Commit the code** — stage only the three files this task lists
9. **Close the task** with `parrot sdd task close TASK-5573 durable-conversation-memory verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

Added ChatStorageTurn (+ _parse_utc, _json_default/_json_safe handling set/bytes/Decimal/datetime/model objects, legacy tool-call mapper) to storage/models.py and exported it from parrot.storage.

**Completed by**: sdd-worker (sequential fallback)
**Date**: 2026-11-12
**Tests**: test_chat_storage_turn 16 passed, test_chat_hot_tier_metadata + tests/test_chat_storage.py green; ruff clean.
**Mutation evidence**: no _force_utc -> RED; always model_validate (no legacy branch) -> RED; identity _json_safe -> RED. Dropping the explicit `timestamp is None` identity check SURVIVED (equivalent mutant): pydantic rejects `timestamp=None` and the failure is wrapped in InvalidTurnPayloadError with a message that still names "timestamp"; the explicit check is kept for the clearer message only. Restored each time.

**Deviations from spec**: none
