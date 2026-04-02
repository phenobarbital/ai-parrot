# Feature Specification: Extending WorkingMemoryToolkit

**Feature ID**: FEAT-074
**Date**: 2026-04-02
**Author**: Jesus Lara
**Status**: approved
**Target version**: next

---

## 1. Motivation & Business Requirements

### Problem Statement

The `WorkingMemoryToolkit` currently stores **only `pd.DataFrame` objects**. Every
layer is hard-coupled to pandas:

- `CatalogEntry.df` is typed as `pd.DataFrame`.
- `compact_summary()` uses `df.dtypes`, `df.describe()`, `df.memory_usage()`.
- `OperationExecutor` operates exclusively on DataFrames.
- Tool methods like `store()`, `import_from_tool()` accept/return DataFrames only.
- The toolkit description itself says *"Store, compute, merge, and summarize DataFrames"*.

In practice, agents need to persist **many kinds of intermediate results** during
multi-step conversations:

| Data type | Example use case |
|-----------|-----------------|
| Plain text / markdown | Summarised research notes, extracted passages |
| `AIMessage` / LLM responses | Cached completions for downstream processing |
| `dict` / JSON-serialisable objects | API responses, structured tool outputs |
| `list[Document]` | RAG retrieval results held for re-ranking |
| Binary / bytes | Small file payloads (images, PDFs) awaiting processing |

Today an agent that wants to stash a text summary for later must wrap it in a
single-cell DataFrame — an ugly hack that confuses both the agent and the reader.

### Goals

- **G1**: Allow `WorkingMemoryToolkit` to store arbitrary typed data (text,
  dict, list, AIMessage, bytes, DataFrame) under a unified key-value catalog.
- **G2**: Keep full backward compatibility — all existing DataFrame-centric
  tools (`store`, `compute_and_store`, `merge_stored`, `summarize_stored`,
  `import_from_tool`) continue to work unchanged.
- **G3**: Provide type-aware compact summaries so the LLM sees meaningful
  previews regardless of data type (not just DataFrame stats).
- **G4**: Add lightweight `store_result` / `get_result` tools for non-DataFrame
  data that are simpler than the DSL-heavy DataFrame tools.
- **G5**: All existing tests pass without modification.
- **G6**: Integrate with `AnswerMemory` so that the LLM can save and recover
  previous Q&A interactions by `turn_id` directly from the working memory
  toolkit — bridging the gap between the conversation turn cache and the
  intermediate result store.

### Non-Goals (explicitly out of scope)

- Persistent / external storage backends (Redis, DB) — remains in-memory.
- Modifying the DSL or `OperationExecutor` to work on non-DataFrame types.
- Adding new DSL operations.
- Streaming or pub-sub patterns for stored results.
- Changing the `import_from_tool` bridge to import non-DataFrame objects.
- Replacing `AnswerMemory` — it remains the canonical turn cache in `BasicAgent`.
  This feature only adds a **bridge** so the toolkit can read from / write to it.

---

## 2. Architectural Design

### Overview

Introduce a **polymorphic catalog entry** model that wraps any Python object
alongside type-specific metadata, while keeping `CatalogEntry` as the
DataFrame-specific variant. A new `GenericEntry` dataclass holds arbitrary data
and provides its own `compact_summary()`. The `WorkingMemoryCatalog` stores both
entry types under the same key namespace.

New tool methods (`store_result`, `get_result`) provide a simple put/get
interface for non-DataFrame data. Existing DataFrame tools remain untouched.

Additionally, the toolkit gains an **optional `AnswerMemory` bridge**. When an
`AnswerMemory` instance is provided (typically via the owning agent), two new
tools allow the LLM to:

- `save_interaction` — persist a Q&A pair into `AnswerMemory` by turn id.
- `recall_interaction` — retrieve a previous Q&A pair from `AnswerMemory` by
  turn id, optionally importing it into the working memory catalog as a
  `GenericEntry` for further processing.

This closes the loop: an agent can recall a prior conversation turn, pull its
answer into working memory, and use it as input for downstream tools.

### Component Diagram

```
WorkingMemoryToolkit
├── store()                 # DataFrame → CatalogEntry (unchanged)
├── store_result()          # Any data  → GenericEntry (NEW)
├── get_stored()            # Returns CatalogEntry summary (unchanged)
├── get_result()            # Returns GenericEntry summary (NEW)
├── drop_stored()           # Drops any entry type (extended)
├── list_stored()           # Lists all entries, both types (extended)
├── compute_and_store()     # DataFrame DSL (unchanged)
├── merge_stored()          # DataFrame merge (unchanged)
├── summarize_stored()      # DataFrame summarize (unchanged)
├── import_from_tool()      # DataFrame bridge (unchanged)
├── list_tool_dataframes()  # DataFrame discovery (unchanged)
├── save_interaction()      # Q&A → AnswerMemory (NEW, bridge)
└── recall_interaction()    # AnswerMemory → GenericEntry (NEW, bridge)

WorkingMemoryCatalog                  AnswerMemory (external)
├── _store: dict[str, Entry]    ←──── recall_interaction() reads from
├── put()                             save_interaction() writes to ──────→
├── put_generic()   (NEW)
├── get()
└── list_entries()
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `CatalogEntry` (internals.py) | unchanged | Remains DataFrame-specific |
| `WorkingMemoryCatalog` (internals.py) | extended | New `put_generic()`, store type broadened |
| `WorkingMemoryToolkit` (tool.py) | extended | New `store_result()`, `get_result()`, `save_interaction()`, `recall_interaction()` tools |
| `models.py` | extended | New `StoreResultInput`, `GetResultInput`, `SaveInteractionInput`, `RecallInteractionInput` Pydantic models |
| `AbstractToolkit` | inherits | Unchanged — new async methods auto-discovered |
| `AnswerMemory` (memory/agent.py) | uses (optional) | Bridge: toolkit reads/writes Q&A pairs via `store_interaction()` / `get()` |

### Data Models

```python
from dataclasses import dataclass, field
from typing import Any, Optional
from enum import Enum

class EntryType(str, Enum):
    """Discriminator for catalog entry types."""
    DATAFRAME = "dataframe"
    TEXT = "text"
    JSON = "json"          # dict or list
    MESSAGE = "message"    # AIMessage or similar
    BINARY = "binary"      # bytes
    OBJECT = "object"      # fallback for any Python object


@dataclass
class GenericEntry:
    """Catalog entry for non-DataFrame data."""
    key: str
    data: Any
    entry_type: EntryType
    created_at: float = field(default_factory=time.time)
    description: str = ""
    turn_id: Optional[str] = None
    session_id: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def compact_summary(self, max_length: int = 500) -> dict:
        """Type-aware compact summary for the LLM context."""
        ...


# New tool input models
class StoreResultInput(BaseModel):
    """Input for storing a generic (non-DataFrame) result."""
    key: str = Field(description="Unique name for this entry")
    data_type: str = Field(
        default="auto",
        description="Type hint: text, json, message, binary, or auto (auto-detect)"
    )
    description: str = Field(default="", description="Human-readable description")
    turn_id: Optional[str] = Field(default=None, description="Conversation turn id")


class GetResultInput(BaseModel):
    """Input for retrieving a generic stored result."""
    key: str = Field(description="Key of the entry to retrieve")
    max_length: int = Field(default=500, description="Max chars in text preview")


# ── AnswerMemory bridge models ──

class SaveInteractionInput(BaseModel):
    """Input for saving a Q&A interaction to AnswerMemory."""
    turn_id: str = Field(description="Conversation turn identifier")
    question: str = Field(description="The user question")
    answer: str = Field(description="The assistant answer")

class RecallInteractionInput(BaseModel):
    """Input for recalling a Q&A interaction from AnswerMemory."""
    turn_id: Optional[str] = Field(
        default=None,
        description="Exact conversation turn identifier to recall"
    )
    query: Optional[str] = Field(
        default=None,
        description="Substring to search across stored questions (fuzzy match). "
                    "Returns the most recent match. Use when turn_id is unknown."
    )
    import_as: Optional[str] = Field(
        default=None,
        description="If provided, import the interaction into working memory under this key"
    )
```

### New Public Interfaces

```python
class WorkingMemoryToolkit(AbstractToolkit):
    # ... existing methods unchanged ...

    def __init__(
        self,
        ...,
        answer_memory: Optional[AnswerMemory] = None,  # NEW
        **kwargs,
    ):
        ...
        self._answer_memory = answer_memory

    @tool_schema(StoreResultInput)
    async def store_result(
        self,
        key: str,
        data: Any,
        data_type: str = "auto",
        description: str = "",
        turn_id: Optional[str] = None,
    ) -> dict:
        """Store any intermediate result (text, dict, list, AIMessage, etc.)
        into working memory for later retrieval by the LLM."""
        ...

    @tool_schema(GetResultInput)
    async def get_result(
        self,
        key: str,
        max_length: int = 500,
    ) -> dict:
        """Retrieve a stored result with a type-aware summary."""
        ...

    # ── AnswerMemory bridge tools ──

    @tool_schema(SaveInteractionInput)
    async def save_interaction(
        self,
        turn_id: str,
        question: str,
        answer: str,
    ) -> dict:
        """Save a question/answer pair to the agent's AnswerMemory,
        keyed by turn_id. Useful for persisting important exchanges
        that the LLM may need to recall later."""
        ...

    @tool_schema(RecallInteractionInput)
    async def recall_interaction(
        self,
        turn_id: Optional[str] = None,
        query: Optional[str] = None,
        import_as: Optional[str] = None,
    ) -> dict:
        """Recall a previous Q&A interaction from AnswerMemory.
        Lookup by exact turn_id, or by substring match against stored
        questions (returns most recent match). If import_as is provided,
        the interaction is also stored into working memory as a
        GenericEntry (entry_type=json) for further processing."""
        ...
```

---

## 3. Module Breakdown

### Module 1: Entry Type Enum & GenericEntry (`models.py` + `internals.py`)

- **Path**: `packages/ai-parrot/src/parrot/tools/working_memory/models.py` (add `EntryType` enum, `StoreResultInput`, `GetResultInput`)
- **Path**: `packages/ai-parrot/src/parrot/tools/working_memory/internals.py` (add `GenericEntry` dataclass)
- **Responsibility**: Define the `EntryType` discriminator, `GenericEntry` dataclass with type-aware `compact_summary()`, and new Pydantic input models.
- **Depends on**: existing models.py enums, pydantic, dataclasses

### Module 2: Extend WorkingMemoryCatalog (`internals.py`)

- **Path**: `packages/ai-parrot/src/parrot/tools/working_memory/internals.py`
- **Responsibility**: Broaden `_store` type to `dict[str, CatalogEntry | GenericEntry]`. Add `put_generic()` method. Update `list_entries()` to handle both types. Ensure `get()`, `drop()`, `keys()`, `__contains__` work with both types.
- **Depends on**: Module 1

### Module 3: New Generic Tool Methods (`tool.py`)

- **Path**: `packages/ai-parrot/src/parrot/tools/working_memory/tool.py`
- **Responsibility**: Add `store_result()` and `get_result()` async methods. Update `drop_stored()` and `list_stored()` to handle `GenericEntry` alongside `CatalogEntry`. Update toolkit description.
- **Depends on**: Module 1, Module 2

### Module 4: AnswerMemory Bridge (`tool.py`)

- **Path**: `packages/ai-parrot/src/parrot/tools/working_memory/tool.py`
- **Responsibility**: Add optional `answer_memory` parameter to `__init__()`.
  Add `save_interaction()` and `recall_interaction()` async tool methods.
  Both methods are **no-ops** (return error dict) when `_answer_memory is None` —
  the bridge is only active when an `AnswerMemory` instance is injected.
  `recall_interaction()` supports two lookup modes:
  - **By `turn_id`**: exact match via `AnswerMemory.get(turn_id)`.
  - **By `query`**: case-insensitive substring match across all stored questions
    in `AnswerMemory._interactions[agent_id]`. Returns the most recent match.
    At least one of `turn_id` or `query` must be provided.
  `recall_interaction()` with `import_as` stores the retrieved Q&A pair into
  the `WorkingMemoryCatalog` as a `GenericEntry` with `entry_type=EntryType.JSON`.
- **Depends on**: Module 1, Module 2, Module 3, `parrot.memory.AnswerMemory`

### Module 5: BasicAgent Auto-Injection (`agent.py`)

- **Path**: `packages/ai-parrot/src/parrot/bots/agent.py`
- **Responsibility**: In `BasicAgent.configure()` (or at the end of `__init__()`),
  after tools are registered, iterate over the tool manager's registered tools.
  If a `WorkingMemoryToolkit` instance is found and its `_answer_memory` is `None`,
  set `toolkit._answer_memory = self.answer_memory`. This wires the bridge
  automatically without requiring the user to pass `answer_memory=` explicitly.
- **Depends on**: Module 4

### Module 6: Package Exports (`__init__.py`)

- **Path**: `packages/ai-parrot/src/parrot/tools/working_memory/__init__.py`
- **Responsibility**: Export `EntryType`, `GenericEntry`, `StoreResultInput`, `GetResultInput`, `SaveInteractionInput`, `RecallInteractionInput`.
- **Depends on**: Modules 1-4

### Module 7: Tests

- **Path**: `packages/ai-parrot/src/parrot/tools/working_memory/tests/test_generic_entries.py`
- **Responsibility**: Tests for storing/retrieving text, dict, list, AIMessage-like objects, bytes. Tests for `list_stored()` mixing DataFrame and generic entries. Tests for `drop_stored()` on generic entries. Tests for `compact_summary()` on each `EntryType`.
- **Path**: `packages/ai-parrot/src/parrot/tools/working_memory/tests/test_answer_memory_bridge.py`
- **Responsibility**: Tests for `save_interaction()` and `recall_interaction()` (both by `turn_id` and by `query` substring match), with and without an `AnswerMemory` instance. Tests for `recall_interaction()` with `import_as` importing into working memory catalog. Tests for auto-injection in `BasicAgent`.
- **Depends on**: Modules 1-6

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_store_text_result` | Module 3 | Store a plain string, verify summary contains preview |
| `test_store_dict_result` | Module 3 | Store a dict, verify JSON-like summary |
| `test_store_list_result` | Module 3 | Store a list of items, verify count and preview |
| `test_store_message_result` | Module 3 | Store an AIMessage-like object, verify content preview |
| `test_store_bytes_result` | Module 3 | Store bytes, verify size shown without content dump |
| `test_auto_detect_entry_type` | Module 1 | Verify `EntryType` auto-detection for str, dict, list, bytes |
| `test_get_result_text` | Module 3 | Retrieve stored text with truncation at max_length |
| `test_get_result_not_found` | Module 3 | KeyError raised for missing key |
| `test_drop_generic_entry` | Module 3 | Drop a generic entry, verify removed |
| `test_list_mixed_entries` | Module 3 | List entries with both DataFrames and generic entries |
| `test_generic_entry_compact_summary` | Module 1 | Each EntryType produces correct summary shape |
| `test_existing_df_store_unchanged` | Module 3 | Existing `store()` still works with DataFrames |
| `test_existing_compute_and_store` | Module 3 | Existing DSL operations unaffected |
| `test_save_interaction` | Module 4 | Save Q&A pair via toolkit, verify in AnswerMemory |
| `test_save_interaction_no_memory` | Module 4 | Returns error when no AnswerMemory provided |
| `test_recall_interaction` | Module 4 | Recall a stored Q&A pair by turn_id |
| `test_recall_interaction_not_found` | Module 4 | Returns error for unknown turn_id |
| `test_recall_and_import` | Module 4 | Recall with `import_as` stores into catalog as GenericEntry |
| `test_recall_no_memory` | Module 4 | Returns error when no AnswerMemory provided |
| `test_recall_by_query` | Module 4 | Recall by substring match on question text |
| `test_recall_by_query_no_match` | Module 4 | Returns error when no question matches query |
| `test_recall_by_query_most_recent` | Module 4 | Multiple matches → returns the most recently stored |
| `test_recall_requires_turn_id_or_query` | Module 4 | Returns error when neither `turn_id` nor `query` provided |
| `test_auto_inject_answer_memory` | Module 5 | BasicAgent.configure() injects answer_memory into WorkingMemoryToolkit |
| `test_auto_inject_no_overwrite` | Module 5 | Auto-inject skips when toolkit already has an answer_memory |

### Integration Tests

| Test | Description |
|---|---|
| `test_mixed_workflow` | Store a DataFrame, store a text result, list both, retrieve each, drop each |
| `test_backward_compat_full` | Run the existing `TestFullWorkflow` test suite — must pass unchanged |
| `test_answer_memory_roundtrip` | Save interaction → recall → import into working memory → get_result → verify content matches |
| `test_fuzzy_recall_roundtrip` | Save 3 interactions → recall by query substring → verify correct match → import into catalog |

### Test Data / Fixtures

```python
@pytest.fixture
def sample_text():
    return "This is a summarised research finding about market trends."

@pytest.fixture
def sample_dict():
    return {"status": "ok", "data": [1, 2, 3], "nested": {"a": 1}}

@pytest.fixture
def sample_message():
    """AIMessage-like object with .content attribute."""
    class FakeMessage:
        content = "The analysis shows a positive correlation."
        role = "assistant"
    return FakeMessage()

@pytest.fixture
def answer_memory():
    from parrot.memory import AnswerMemory
    return AnswerMemory(agent_id="test-agent")

@pytest.fixture
def toolkit_with_memory(answer_memory):
    return WorkingMemoryToolkit(answer_memory=answer_memory)
```

---

## 5. Acceptance Criteria

- [ ] `store_result("key", "some text")` stores and returns a summary with `entry_type: "text"`
- [ ] `store_result("key", {"a": 1})` stores and returns a summary with `entry_type: "json"`
- [ ] `store_result("key", b"raw bytes")` stores and returns a summary with `entry_type: "binary"` showing byte length, not content
- [ ] `store_result("key", ai_message)` stores objects with `.content` attribute as `entry_type: "message"`
- [ ] `get_result("key")` returns a type-aware compact summary
- [ ] `get_result("key", max_length=50)` truncates text previews at 50 chars
- [ ] `list_stored()` returns both DataFrame and generic entries with correct type labels
- [ ] `drop_stored("key")` works for both CatalogEntry and GenericEntry
- [ ] All existing DataFrame tests pass without modification
- [ ] `store()`, `compute_and_store()`, `merge_stored()`, `summarize_stored()` unchanged
- [ ] `save_interaction(turn_id, question, answer)` persists Q&A into `AnswerMemory`
- [ ] `recall_interaction(turn_id)` returns the stored Q&A pair
- [ ] `recall_interaction(turn_id, import_as="key")` additionally stores as `GenericEntry` in catalog
- [ ] `recall_interaction(query="market trends")` finds interactions whose question contains the substring (case-insensitive)
- [ ] `recall_interaction()` with neither `turn_id` nor `query` returns an error
- [ ] `save_interaction()` / `recall_interaction()` return error dict when no `AnswerMemory` is configured
- [ ] `BasicAgent.configure()` auto-injects `self.answer_memory` into any `WorkingMemoryToolkit` found in the tool manager
- [ ] Auto-injection does NOT overwrite an already-set `_answer_memory`
- [ ] No new external dependencies required
- [ ] `from parrot.tools.working_memory import GenericEntry, EntryType` works

---

## 6. Implementation Notes & Constraints

### Patterns to Follow

- Use `@dataclass` for `GenericEntry` (consistent with `CatalogEntry`)
- Use `str(Enum)` for `EntryType` (consistent with `OperationType`)
- Use `@tool_schema` decorator for new tool methods (framework convention)
- Google-style docstrings, strict type hints throughout
- `self.logger` for all logging

### Type Detection Logic

```python
def _detect_entry_type(data: Any) -> EntryType:
    if isinstance(data, str):
        return EntryType.TEXT
    if isinstance(data, bytes):
        return EntryType.BINARY
    if isinstance(data, (dict, list)):
        return EntryType.JSON
    if hasattr(data, "content") and hasattr(data, "role"):
        return EntryType.MESSAGE
    if isinstance(data, pd.DataFrame):
        return EntryType.DATAFRAME
    return EntryType.OBJECT
```

### Summary Strategy per Type

| EntryType | Summary contents |
|-----------|-----------------|
| TEXT | `char_count`, truncated `preview`, `word_count` |
| JSON | `type` (dict/list), `keys` or `length`, truncated JSON preview |
| MESSAGE | `role`, truncated `content` preview, `content_length` |
| BINARY | `size_bytes`, `size_human` (e.g. "1.2 KB"), no content |
| OBJECT | `type_name`, `str(obj)` truncated, `attributes` list |
| DATAFRAME | Existing `CatalogEntry.compact_summary()` (unchanged) |

### AnswerMemory Bridge Pattern

The bridge is **optional and non-intrusive**:

```python
# Without AnswerMemory — tools are registered but return errors
toolkit = WorkingMemoryToolkit()
await toolkit.save_interaction(...)  # → {"status": "error", "error": "No AnswerMemory configured"}

# With AnswerMemory — full bridge (explicit wiring)
toolkit = WorkingMemoryToolkit(answer_memory=agent.answer_memory)

# Or auto-injected by BasicAgent — no explicit wiring needed:
# BasicAgent.configure() detects WorkingMemoryToolkit in tools and sets
# toolkit._answer_memory = self.answer_memory automatically.

# Save and recall by exact turn_id
await toolkit.save_interaction("turn-1", "What is X?", "X is ...")  # → {"status": "saved"}
result = await toolkit.recall_interaction(turn_id="turn-1", import_as="prev_answer")
# → {"status": "recalled", "interaction": {...}, "imported_as": "prev_answer"}

# Recall by fuzzy question match (when turn_id is unknown)
result = await toolkit.recall_interaction(query="What is X")
# → {"status": "recalled", "turn_id": "turn-1", "interaction": {"question": "What is X?", "answer": "X is ..."}}
```

The `AnswerMemory` class (`parrot/memory/agent.py`) stores `{question, answer}`
dicts keyed by `turn_id`, scoped to an `agent_id`. It uses an `asyncio.Lock`
for concurrency safety. The bridge calls `store_interaction()` and `get()` for
exact lookups. For fuzzy search, it iterates `_interactions[agent_id].items()`
and performs case-insensitive substring matching on the `question` field,
returning the most recently stored match.

### Auto-Injection Pattern (BasicAgent)

```python
# In BasicAgent.configure() — after tool registration:
from parrot.tools.working_memory import WorkingMemoryToolkit

for tool in self.tool_manager.get_tools():
    if isinstance(tool, WorkingMemoryToolkit) and tool._answer_memory is None:
        tool._answer_memory = self.answer_memory
        self.logger.debug("Auto-injected answer_memory into WorkingMemoryToolkit")
```

This ensures zero-config wiring: any `BasicAgent` (or subclass like `PandasAgent`)
that registers a `WorkingMemoryToolkit` gets the bridge for free.

### Known Risks / Gotchas

- **Key namespace collision**: DataFrame and generic entries share the same key
  namespace. This is intentional — a key is unique regardless of type. Storing a
  generic entry with a key that already holds a DataFrame replaces it (and vice versa).
  Document this clearly.
- **Serialisation**: `GenericEntry.data` holds arbitrary Python objects. Since the
  store is in-memory only, no serialisation is needed now. If a persistence backend
  is added later, serialisation will need to be addressed (out of scope).
- **`compact_summary()` for OBJECT type**: Calling `str()` on arbitrary objects
  could be expensive or produce huge output. Use `repr()` with a character limit.
- **AnswerMemory lifecycle**: The toolkit does NOT own the `AnswerMemory` instance.
  The owning agent is responsible for creating and managing it. If the agent is
  garbage-collected, the `AnswerMemory` reference becomes stale. This is acceptable
  since both share the same session lifetime.

### External Dependencies

No new dependencies. Uses only stdlib + pydantic + pandas (already present).

---

## 7. Worktree Strategy

- **Isolation**: `per-spec` — all tasks run sequentially in one worktree.
- **Rationale**: Changes are contained within the `working_memory` package.
  Modules depend on each other linearly (models → internals → tool → exports → tests).
- **Cross-feature dependencies**: FEAT-064 (refactor-workingmemorytoolkit) should
  be merged first since this spec builds on the refactored module structure.

---

## 8. Open Questions

- [x] Should `store_result()` accept a `metadata: dict` parameter for arbitrary user-defined tags? — *Owner: Jesus Lara*: Yes
- [x] Should `get_result()` return the raw data object in addition to the summary (e.g. `include_raw=True` flag)? — *Owner: Jesus Lara*: Yes
- [x] Should there be a `search_stored()` tool that finds entries by description substring or entry type? — *Owner: Jesus Lara*: Yes
- [x] Should `recall_interaction()` also support recalling by partial question match (fuzzy search) rather than only by exact `turn_id`? — *Owner: Jesus Lara* — **Yes**: add optional `query` parameter for substring match across stored questions.
- [x] Should `BasicAgent` auto-inject its `answer_memory` into `WorkingMemoryToolkit` when both are present, or leave it to explicit wiring? — *Owner: Jesus Lara* — **Yes**: auto-inject in `BasicAgent.configure()` when a `WorkingMemoryToolkit` is found in the tool manager.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-04-02 | Jesus Lara | Initial draft |
| 0.2 | 2026-04-02 | Jesus Lara | Added AnswerMemory bridge (G6) |
| 0.3 | 2026-04-02 | Jesus Lara | Resolved: fuzzy recall by query, BasicAgent auto-injection |
