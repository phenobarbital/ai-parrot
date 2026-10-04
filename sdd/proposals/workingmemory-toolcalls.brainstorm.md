---
type: feature
base_branch: dev
projects: [ai-parrot]
tags: [working-memory, tool-execution, task-memory, context-compression, observability]
---

# Brainstorm: Execution Proof Vouchers for Tool Calls

**Date**: 2026-09-21
**Author**: Jesus
**Status**: exploration
**Recommended Option**: Option B

---

## Problem Statement

A tool that returns a large payload — a 4.2M-row query result, a scraped
corpus, a multi-megabyte API response — pays for that payload **twice**: once
when the runtime serializes it, and again on every subsequent turn that the
conversation history carries it. The model rarely needs the bytes. It needs to
know *that the call ran*, *that it succeeded*, and *how to get at the data when
it actually wants to compute on it*.

Today AI-Parrot solves adjacent halves of this and never closes the loop:

- **`CompressionStage`** (`tool-result-compression.spec.md`, FEAT-380) shrinks a
  result but still returns the (lossy) payload inline.
- **`CompressionTee`** diverts the full payload to `WorkingMemoryToolkit` —
  but *only* when compression was lossy or the call errored. A large,
  successful, losslessly-serializable result goes straight into context.
- **`InvocationObserver`** (`workingmemory-toolkit.spec.md`, FEAT-538) already
  captures a rigorous per-attempt `InvocationRecord` — call id, outcome,
  attempt number, elapsed time, artifact receipts — but that record is
  internal. The model never sees it.
- **`WorkingMemoryToolkit`** can already store and retrieve datasets by key,
  but a tool has no way to say "register my result and hand the model a
  reference instead".

So the pieces for "data stays in working memory, only a proof-of-execution
moves" all exist and are not connected. The missing piece is a **voucher**: a
small, typed, LLM-facing projection of the invocation record that carries the
handle to the retained data.

**Who is affected**: agent authors whose tools return bulk data (database,
scraping, file, API toolkits); end users who hit context limits mid-analysis;
operators paying for re-sent payloads.

**Why now**: FEAT-538 landed the invocation record and FEAT-380 landed the tee.
The voucher is the join between them, and without it neither pays off for the
common case — the call that *worked* and returned a lot.

---

## Constraints & Requirements

- **Opt-in per tool.** A tool declares that it returns vouchers. No existing
  tool changes behavior on upgrade. (Round 1.3)
- **The voucher is a projection of `InvocationRecord`, not a second ledger.**
  One source of truth; the voucher and the journal can never disagree.
  (Round 1.2)
- **No-op when task memory is off.** A voucher-opted-in tool on an agent
  without FEAT-538 task memory returns its full payload exactly as today.
  Silent, not an error. (Round 2.1)
- **Redemption is same-turn, same-process.** Matches FEAT-538 Delivery A; no
  Redis, no Postgres, no A2A crossing in this feature. (Round 1.4)
- **The runtime always produces a shape summary; a tool may enrich it.** A
  voucher is never empty, and never requires tool changes to be useful.
  (Round 2.2)
- **An unredeemable voucher fails loudly and usefully** — a typed `expired`
  error naming the tool and arguments that produced it, so the model can
  deliberately re-run instead of inventing data. Never a silent auto-replay.
  (Round 2.3)
- **The performance contract this feature must prove: context savings +
  fidelity.** Tokens kept out of context per voucher, and byte-identical data
  on redemption. (Round 2.4)
- **The small-model executor is OUT OF SCOPE.** This feature establishes the
  model-independent execution contract that a later executor is measured
  against. (Round 1.1)
- Async-first, Pydantic v2 models, `self.logger`, Google-style docstrings,
  `aiohttp` only — per `.claude/rules/codebase-conventions.md`.
- Must not perturb FEAT-538's ordering invariants: `tool_started` persisted
  immediately before execution, terminal persisted before success is reported.

---

## Options Explored

### Option A: Vouchering as a compression codec / filter level

Treat "return a voucher instead of the payload" as the most aggressive rung of
the existing compression ladder. `CompressionStage.run()` already receives the
payload, the status and the metadata dict, already consults a budget router,
and already knows how to fall back to the original payload on any failure. A
new `FilterLevel` (or a registered codec) would register the payload into
working memory and emit the voucher as the "compressed" output.

✅ **Pros:**
- Near-zero new plumbing — the stage is already called on every tool result
  (`manager.py:2510`) and already owns the metadata channel.
- Inherits the stage's "never raises" guarantee and the budget router's
  latency circuit breaker for free.
- `CompressionReport` (`report.py:99`) already aggregates exactly the
  bytes-before/bytes-after/`est_tokens_saved` numbers the contract needs.

❌ **Cons:**
- Category error: every other codec is a *lossy rendering of the same value*.
  A voucher is a **different value with a different contract** — the model must
  now make a second call to get the data. Hiding that behind a codec means a
  budget-router passthrough or a circuit-breaker trip silently changes the
  tool's return type back to the payload, which is exactly the kind of
  nondeterminism the opt-in is meant to remove.
- Codec selection is per-payload-shape and budget-driven; the opt-in is
  per-tool and must be honoured unconditionally. Two different dispatch axes
  forced into one.
- The stage runs *after* result hooks and postprocessing, so the voucher would
  be built from an already-mutated payload.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pydantic` (v2) | Voucher model | already a core dependency |
| — | no new third-party dependency | reuses in-repo machinery |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/tools/compression/stage.py:117` — `CompressionStage.run()`
- `packages/ai-parrot/src/parrot/tools/compression/levels.py` — `FilterLevel`, `cap`
- `packages/ai-parrot/src/parrot/tools/compression/report.py:99` — `CompressionReport`

---

### Option B: A dedicated voucher stage in `ToolManager`, projecting the observer's record

Add an explicit post-dispatch stage in `ToolManager`, sitting **after** the
observer has closed the attempt and **before** (or instead of) the compression
stage. For a tool that opted in, the stage: registers the payload into the
bound `WorkingMemoryToolkit`, attaches the resulting artifact version to the
attempt via `TurnTaskSession.add_artifact_receipt()`, reads back the closed
`InvocationRecord` with `TurnTaskSession.receipt(call_id)`, and projects it
into a `ToolResult` whose `result` is the voucher.

The opt-in is a class-level boolean on `AbstractTool`, exactly parallel to the
existing `return_direct` / `enable_redaction` / `auto_open` flags
(`abstract.py:299/309/321`), plus a matching keyword on the `@tool` decorator.

✅ **Pros:**
- The voucher is, structurally, a *projection* — it reads the record the
  observer already wrote rather than assembling a parallel one. Directly
  implements the Round 1.2 decision.
- Keeps the observer's ordering-critical path untouched: no working-memory I/O
  is added inside `begin`/`finish`, so FEAT-538's fail-closed durability
  semantics are unchanged.
- Vouchering and compression stay separable: a voucher is emitted
  deterministically for an opted-in tool, and the (now tiny) voucher simply
  never trips the compression budget.
- Natural home for the no-op rule: the stage checks
  `WorkingMemoryToolkit.task_memory_enabled` (`tool.py:214`) once and returns
  the payload untouched when task memory is off.
- Reuses the tee's existing discovery and binding helpers
  (`_find_working_memory_toolkit()` at `manager.py:2573`).

❌ **Cons:**
- Touches `ToolManager`, a 2,800-line class on the hot path for every tool
  call — the highest-traffic, highest-risk file in the tools package.
- Adds a third concept (record / tee entry / voucher) that contributors must
  learn to tell apart.
- Requires care around `ToolManager.clone()` (`manager.py:2609`) and `sync()`
  (`manager.py:703`) so a cloned manager does not share or lose voucher state.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pydantic` (v2) | `ExecutionVoucher` model | core dependency |
| `orjson` | voucher serialization | already used by `task_memory` |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/tools/manager.py:2573` — `_find_working_memory_toolkit()`
- `packages/ai-parrot/src/parrot/tools/manager.py:1552` — `invocation_observer` property
- `packages/ai-parrot/src/parrot/tools/working_memory/task_memory/context.py:507` — `TurnTaskSession.receipt()`
- `packages/ai-parrot/src/parrot/tools/working_memory/task_memory/context.py:618` — `TurnTaskSession.add_artifact_receipt()`
- `packages/ai-parrot/src/parrot/tools/working_memory/tool.py:348` — `store_result()`
- `packages/ai-parrot/src/parrot/tools/working_memory/tool.py:399` — `get_result()` (redemption)
- `packages/ai-parrot/src/parrot/tools/abstract.py:321` — `auto_open` as the opt-in flag precedent

---

### Option C: Observer-owned vouchering

Push the whole thing into `InvocationObserver.finish()` (`observer.py:342`).
The observer already knows the call id, the outcome, the elapsed time and the
artifact receipts — it could register the payload and return the voucher as
part of closing the attempt. One write, one place, and the voucher is not
merely a projection of the record: it *is* the record, rendered.

✅ **Pros:**
- Conceptually the tightest possible reading of "the voucher is a projection".
- Exactly one place in the codebase captures tool activity, preserving the
  observer's stated design property that the journal and
  `ConversationTurn.tool_invocations` can never disagree.
- No new stage, no new ordering to reason about in `ToolManager`.

❌ **Cons:**
- **Puts a working-memory write inside the ordering-critical terminal path.**
  The observer's contract is that the terminal event is persisted before
  success is reported, and that a failure there yields `UNKNOWN` rather than a
  false success. Adding a dataset registration means a working-memory failure
  can now turn a perfectly good tool call into an `UNKNOWN` outcome — a
  correctness regression bought for architectural tidiness.
- The observer is deliberately payload-agnostic; it records *that* a call
  happened, not what it returned. Teaching it to inspect, summarize and store
  payloads inverts that separation.
- The fenced-ownership path (Delivery B) re-checks the claim before writing
  the terminal. A registration interleaved there has genuinely subtle
  semantics under fencing.

📊 **Effort:** Medium–High (low code volume, high blast radius on a
correctness-critical component)

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/tools/working_memory/task_memory/observer.py:342` — `InvocationObserver.finish()`
- `packages/ai-parrot/src/parrot/tools/working_memory/task_memory/models.py:1765` — `InvocationRecord`

---

### Option D (unconventional): Registration-time tool wrapping, no core change

Never touch `ToolManager` or the observer at all. When a `WorkingMemoryToolkit`
is registered alongside other tools, it **wraps** each opted-in tool in a proxy
that awaits the inner tool, stores the payload through its own
`store_result()`, and returns the voucher. The voucher's execution metadata is
read opportunistically from the ambient turn session — the same trick
`CompressionTee` already uses via `_ambient_producer()` (`tee.py:82`).

✅ **Pros:**
- Zero risk to the hot dispatch path; the highest-traffic file is untouched.
- Ships as a `WorkingMemoryToolkit` capability, so it can be adopted (and
  reverted) per agent with no core-version coupling.
- Easiest thing to delete if the experiment fails — which matters, because
  this feature's whole purpose is to produce evidence for a later decision.

❌ **Cons:**
- The wrapper sits *outside* the manager's guards, confirmation flow,
  compression stage and result hooks, so the voucher is built from a payload
  that has not been postprocessed — the model would see data that differs from
  what an unwrapped call returns.
- Correlating to the `InvocationRecord` becomes best-effort ambient lookup
  rather than a direct read, which is precisely the "second ledger that can
  drift" outcome Round 1.2 ruled out.
- Tool wrapping interacts badly with `ToolManager.clone()` and with toolkits
  that generate tools dynamically (`_generate_tools()`, `tool.py:170`).

📊 **Effort:** Low–Medium

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/tools/compression/tee.py:82` — `_ambient_producer()`
- `packages/ai-parrot/src/parrot/tools/working_memory/tool.py:170` — `_generate_tools()`

---

## Recommendation

**Option B** — a dedicated voucher stage in `ToolManager` that projects the
observer's `InvocationRecord`.

The decision turns on where a working-memory write is allowed to fail. Option C
is the most elegant on paper and is rejected for exactly one reason: it makes
storage failure indistinguishable from execution failure. FEAT-538 went to
considerable lengths to guarantee that a call reported as successful really
did persist its terminal event, and that anything less honest surfaces as
`UNKNOWN`. Registering a dataset is a fallible, I/O-bound, size-dependent
operation with no business being inside that guarantee. Option B keeps the
failure where it belongs: if registration fails, the voucher is not emitted,
the payload is returned as it would have been anyway, and the invocation record
remains exactly as truthful as before.

Option A is rejected because it conflates two dispatch axes. Compression is
budget-driven and may legitimately decline to run; vouchering is a per-tool
contract that must not silently change the return shape based on a latency
circuit breaker. A tool author who opts in needs to know what their tool
returns.

Option D is the tempting cheap answer and is genuinely attractive for an
experiment — but it produces the weaker artifact. Building the voucher outside
the manager means it is assembled from a pre-postprocessing payload and
correlated to the record by ambient guesswork. Since the entire deliverable
here is a *trustworthy performance contract*, measuring a path that is not the
real dispatch path would undermine the numbers the later executor decision
depends on.

What Option B trades away is blast radius: it edits the largest and busiest
class in the tools package. That is acceptable because the change is additive
and gated twice over — once by the per-tool opt-in flag, once by the
task-memory-enabled check — so every existing agent's dispatch path is
bit-for-bit unchanged until someone deliberately opts a tool in.

---

## Feature Description

### User-Facing Behavior

An agent author marks a bulk-returning tool as voucher-emitting, either on the
class (`returns_voucher = True`, alongside `return_direct` / `auto_open`) or
via the `@tool(...)` decorator. Nothing else about the agent changes.

At runtime, when that tool is called on an agent that has a
`WorkingMemoryToolkit` with task memory enabled, the model receives a compact
proof of execution instead of the payload:

```json
{
  "execution_id": "exec_123",
  "tool": "database_query",
  "status": "succeeded",
  "attempt": 1,
  "result": {
    "dataset_id": "wm_sales_456",
    "row_count": 4200000,
    "column_count": 18,
    "schema_ref": "wm_sales_456_schema"
  }
}
```

The data itself is in working memory. The model reaches it through the
already-existing retrieval and analysis tools — `get_result`, `summarize_stored`,
`compute_and_store`, `merge_stored` — by the `dataset_id` the voucher carries.
For a downstream agent in the same crew or flow run, the voucher is the whole
hand-off: it is small enough to pass in a prompt, and it redeems against the
shared catalog.

On an agent **without** task memory enabled, the opt-in is inert and the tool
returns its payload exactly as it does today. No error, no warning storm — one
debug-level log line.

### Internal Behavior

1. Dispatch proceeds unchanged through guards, confirmation and the observer.
   The observer opens the attempt, the tool body runs, the observer closes the
   attempt with a terminal outcome. **Nothing in this sequence is modified.**
2. The new voucher stage runs after result hooks and postprocessing. It is a
   no-op unless the tool opted in, a `WorkingMemoryToolkit` is bound, and
   `task_memory_enabled` is true.
3. The stage derives a **shape summary** from the payload generically — row and
   column counts for tabular data, length and element kind for sequences, key
   set for mappings, byte size otherwise. If the tool supplied its own summary,
   those fields are merged over the inferred ones.
4. The payload is registered into working memory, yielding a catalog key and an
   `artifact_id@version` evidence reference.
5. That reference is attached to the attempt via `add_artifact_receipt()`, and
   the closed `InvocationRecord` is read back via `receipt(call_id)`.
6. The record is projected into an `ExecutionVoucher`: identity and attempt
   number from the record, `status` from `CallOutcome`, the summary and the
   dataset handle from step 3–4. The `ToolResult` is rebuilt with the voucher
   as its `result`, and the original voucher payload is *not* carried alongside
   it.
7. Redemption is an ordinary working-memory read by `dataset_id`.

Savings accounting reuses the existing `CompressionReport` aggregator, whose
own docstring notes that wiring a live `ToolManager` listener is future work —
this feature is that work, for the voucher path.

### Edge Cases & Error Handling

- **Task memory off** — opt-in is inert; full payload returned. (Decided.)
- **No `WorkingMemoryToolkit` registered** — same as above.
- **Registration fails** (payload not serializable, catalog full, store raises)
  — the voucher is not emitted, the original payload is returned, and the
  failure is logged. A storage problem must never fail a tool call that
  succeeded, and must never be reported as an execution failure.
- **Tool failed** (`CallOutcome.ERROR` / `DENIED` / `NOT_EXECUTED`) — no
  payload to register. Existing error-path tee behavior at `manager.py:2079`
  is preserved untouched; whether a failure voucher is emitted at all is an
  open question below.
- **`CallOutcome.UNKNOWN` or `CANCELLED`** — unresolved outcomes. No voucher:
  the runtime must not issue a proof of execution for a call whose disposition
  it cannot establish.
- **Voucher redeemed after its data is gone** — next turn, post-compaction, or
  evicted by the retention cap — the retrieval path returns a structured
  `expired` error carrying the originating tool name and arguments, so the
  model can choose to re-run. Never an automatic replay: a non-idempotent tool
  must not be silently re-executed.
- **Voucher redeemed with an unknown id** — distinct `not_found` error, kept
  separate from `expired` so a hallucinated id is diagnosable.
- **`return_direct` tools** — returning a voucher directly to the user would
  show them JSON instead of an answer. Interaction flagged as an open question.
- **Cloned managers** (`clone()` / `sync()`) — voucher state must follow the
  same sharing rules as the tee, or a clone will emit vouchers redeemable
  against a catalog it does not hold.

---

## Capabilities

### New Capabilities
- `tool-result-vouchers`: per-tool opt-in that registers a tool's payload into
  working memory and returns a typed, LLM-facing projection of its
  `InvocationRecord` in place of the data.
- `voucher-savings-contract`: a measurement harness proving context tokens
  saved per voucher and byte-identical fidelity on redemption — the
  model-independent baseline a future small-model executor is judged against.

### Modified Capabilities
- `workingmemory-toolkit` (`sdd/specs/workingmemory-toolkit.spec.md`, FEAT-538)
  — the invocation record gains a consumer; artifact receipts are now attached
  from the dispatch path.
- `tool-result-compression` (`sdd/specs/tool-result-compression.spec.md`,
  FEAT-380) — the tee is no longer the only route from a tool result into
  working memory; the two paths must not double-register the same payload.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/tools/manager.py` | modifies | New voucher stage in the post-dispatch path; must respect `clone()`/`sync()` |
| `parrot/tools/abstract.py` | extends | New class-level opt-in flag on `AbstractTool`, parallel to `auto_open` (line 321) |
| `parrot/tools/decorators.py` | extends | New keyword on `@tool(...)` (line 59) mirroring the class flag |
| `parrot/tools/working_memory/tool.py` | depends on | `store_result()` / `get_result()` as the registration and redemption surface |
| `parrot/tools/working_memory/task_memory/context.py` | depends on | `receipt()` and `add_artifact_receipt()` — read and attach, no signature change |
| `parrot/tools/working_memory/task_memory/observer.py` | unchanged | Explicitly NOT modified — protecting FEAT-538 ordering invariants |
| `parrot/tools/compression/tee.py` | coordinates with | Must not double-store a payload the voucher stage already registered |
| `parrot/tools/compression/report.py` | extends | Live `ToolManager` listener, which its docstring names as future work |
| `parrot/memory/compaction/recover.py` | adjacent | `read_omitted_content` is a *different* recovery channel (compaction omissions, not tool payloads) — must stay distinct |
| Docs | adds | A `docs/` page describing the voucher contract for tool authors |

No new third-party dependencies. No breaking changes: both gates (per-tool
opt-in, task-memory-enabled) default off.

---

## Code Context

### User-Provided Code

```json
// Source: user-provided (sdd/proposals/workingmemory_toolcalls.md:9-21)
{
  "execution_id": "exec_123",
  "tool": "database_query",
  "status": "succeeded",
  "attempt": 1,
  "result": {
    "dataset_id": "wm_sales_456",
    "row_count": 4200000,
    "column_count": 18,
    "schema_ref": "wm_sales_456_schema"
  }
}
```

```
# Source: user-provided (sdd/proposals/workingmemory_toolcalls.md:24-36)
flowchart TD
    P["LLM thinking"] -->|"Subtarea acotada"| S["Modelo pequeño"]
    S -->|"Tool y argumentos"| R["Runtime"]
    R --> T["Tool de consulta"]
    T -->|"Dataset completo"| W["Memoria de trabajo"]
    W -->|"ID registrado"| T
    T -->|"Estado y referencia"| R
    R -->|"Comprobante"| P
    P -->|"Análisis por ID"| A["Tool de análisis"]
    W -->|"Datos"| A
    A -->|"Agregados y evidencia"| P
```

> Note: the `Modelo pequeño` (small-model executor) leg of this flow is
> **out of scope** for this feature per Round 1.1. Only the
> `Runtime → Tool → Working memory → Comprobante` path is built here.

### Verified Codebase References

All paths below are relative to `packages/ai-parrot/src/`.

#### Classes & Signatures

```python
# From parrot/tools/abstract.py:250
class ToolResult(BaseModel):
    success: bool = Field(default=True, ...)            # line 253
    status: str = Field(default="success", ...)          # line 254
    result: Any = Field(...)                             # line 255
    error: Optional[str] = Field(default=None, ...)      # line 256
    metadata: Dict[str, Any] = Field(default_factory=dict, ...)  # line 257

# From parrot/tools/abstract.py:281
class AbstractTool(EventEmitterMixin, ABC):
    return_direct: bool = False        # line 299
    enable_redaction: bool = False     # line 309
    auto_open: bool = False            # line 321  <- opt-in flag precedent

# From parrot/tools/decorators.py:59
def tool(
    _func: Optional[Callable] = None,
    *,
    name: Optional[str] = None,
    description: Optional[str] = None,
    schema: Optional[Dict[str, Any]] = None,
    auto_register: bool = False,
    requires_confirmation: bool = False,
    confirm_template: Optional[str] = None,
    confirm_window_seconds: int = 0,
    allow_edit: bool = False,
    required_permissions: Optional[Set[str]] = None,
): ...

# From parrot/tools/manager.py:266
class ToolManager:
    self._invocation_observer: Optional[Any] = None          # line 307
    self._compression_tee: CompressionTee = CompressionTee() # line 354

    def set_invocation_observer(self, observer: Optional[Any]) -> None:  # line 1537
    @property
    def invocation_observer(self) -> Optional[Any]:                      # line 1552
    async def _observed(self, observation, tool_name, call, *, sync: bool = False) -> Any:  # line 1556
    def sync(self, other_manager: "ToolManager") -> None:                # line 703
    def clone(self, *, include_search_tool: bool = False) -> "ToolManager":  # line 2609
    def _find_working_memory_toolkit(self) -> Optional[Any]:             # line 2573
    def _bind_compression_tee(self) -> None                              # called at lines 2078, 2112, 2466, 2510

# From parrot/tools/compression/stage.py:42
class CompressionStage:
    async def run(                                        # line 117
        self,
        tool_name: str,
        payload: Any,
        *,
        status: str,
        metadata: dict[str, Any],
        return_direct: bool,
        level_override: Optional[FilterLevel] = None,
    ) -> tuple[Any, dict[str, Any]]: ...

# From parrot/tools/compression/tee.py:93
class CompressionTee:
    def __init__(self, working_memory: Optional["WorkingMemoryToolkit"] = None,
                 *, max_retained: int = 200) -> None:      # line 108
    @property
    def available(self) -> bool:                           # line 131
    def bind_working_memory(self, working_memory) -> None: # line 135
    async def store(self, tool_name: str, payload: Any, reason: str, *,
                    producer_call_id: Optional[str] = None) -> Optional[str]:  # line 163
    def cleanup(self) -> None:                             # line 309

def attach_tee_pointer(payload: Any, key: str, reason: str) -> Any:  # line 326

# From parrot/tools/compression/report.py
class ToolSavings(BaseModel):    # line 33  — bytes_before/bytes_after/est_tokens_saved
class SessionSavings(BaseModel): # line 72  — + pct_saved property (line 83)
class CompressionReport:         # line 99  — docstring: live ToolManager listener is "future work"

# From parrot/tools/working_memory/tool.py:47
class WorkingMemoryToolkit(TaskMemoryToolsMixin, AbstractToolkit):
    @property
    def task_memory_enabled(self) -> bool:   # line 214 -> self._catalog.is_enabled
    async def store_result(self, key: str, data: Any, data_type: str = "auto",
                           description: str = "", metadata: Optional[dict] = None,
                           turn_id: Optional[str] = None) -> dict:      # line 348
    async def get_result(self, key: str, max_length: int = 500,
                         include_raw: bool = False,
                         max_rehydrate_bytes: Optional[int] = None,
                         offset: int = 0, limit: Optional[int] = None) -> dict:  # line 399
    async def summarize_stored(...)  # line 733
    async def import_from_tool(...)  # line 787

# From parrot/tools/working_memory/task_memory/models.py:1765
class InvocationRecord(_TaskModel):
    call_id: str            # line 1801
    attempt: int            # line 1802 (ge=1)
    parent_call_id: Optional[str]   # line 1803
    tool_name: str          # line 1804
    context: TaskContext    # line 1805
    outcome: Optional[CallOutcome]  # line 1806
    executed: bool          # line 1807
    error: Optional[str]    # line 1808
    elapsed_ms: Optional[int]       # line 1809
    started_at: datetime    # line 1810
    finished_at: Optional[datetime] # line 1811
    artifact_receipts: Tuple[EvidenceRef, ...]  # line 1812
    invocation: Optional[Any]       # line 1813
    degraded: bool          # line 1814

# From parrot/tools/working_memory/task_memory/models.py:298
class CallOutcome(str, Enum):
    SUCCESS = "success"; ERROR = "error"; DENIED = "denied"
    CANCELLED = "cancelled"; UNKNOWN = "unknown"; NOT_EXECUTED = "not_executed"
    @property
    def is_resolved(self) -> bool: ...   # line 314; UNKNOWN/CANCELLED are unresolved (line 320)

# From parrot/tools/working_memory/task_memory/models.py:619
class EvidenceRef(_TaskModel):
    artifact_id: str   # line 631
    version: int       # line 632 (ge=1)
    def __str__(self) -> str: ...            # line 634 -> "artifact_id@version"
    @classmethod
    def parse(cls, value: str) -> "EvidenceRef": ...  # line 638

# From parrot/tools/working_memory/task_memory/context.py
class TurnTaskSession:
    def receipt(self, call_id: str) -> Optional[InvocationRecord]:     # line 507
    def add_artifact_receipt(self, call_id: str, ref: EvidenceRef) -> bool:  # line 618

# From parrot/tools/working_memory/task_memory/observer.py:211  (DO NOT MODIFY)
class InvocationObserver:
    async def begin(...)         # line 281
    async def finish(...)        # line 342
    async def cancelled(...)     # line 449
    async def not_executed(...)  # line 490
```

#### Verified Imports

```python
# Confirmed to resolve:
from parrot.tools.working_memory import WorkingMemoryToolkit   # working_memory/__init__.py:3 / :29
from parrot.tools.working_memory import TaskMemory             # working_memory/__init__.py:25 / :30
from parrot.tools.compression.tee import CompressionTee        # imported by manager.py:16
from parrot.tools.compression import CompressionStage          # compression/__init__.py:23
from parrot.tools.compression import CompressionReport, ToolSavings, SessionSavings  # compression/__init__.py:22
from parrot.tools.compression import FilterLevel, cap          # compression/__init__.py:13
```

#### Key Attributes & Constants
- `AbstractTool.return_direct` → `bool` (parrot/tools/abstract.py:299)
- `AbstractTool.enable_redaction` → `bool` (parrot/tools/abstract.py:309)
- `AbstractTool.auto_open` → `bool` (parrot/tools/abstract.py:321)
- `ToolManager._invocation_observer` → `Optional[Any]` (parrot/tools/manager.py:307)
- `ToolManager._compression_tee` → `CompressionTee` (parrot/tools/manager.py:354)
- `WorkingMemoryToolkit.task_memory_enabled` → `bool` (parrot/tools/working_memory/tool.py:214)
- `CompressionTee.__init__(max_retained=200)` → retention cap (parrot/tools/compression/tee.py:108)
- `READ_OMITTED_CONTENT_NAME = "read_omitted_content"` (parrot/memory/compaction/recover.py:27)
- `bind_read_omitted_content(memory) -> Callable[..., Awaitable[str]]` (parrot/memory/compaction/recover.py:60)

### Does NOT Exist (Anti-Hallucination)
- ~~any `voucher` symbol, model, or spec~~ — a case-insensitive search for
  "voucher" across `packages/` and `sdd/specs/` (`*.py`, `*.md`) returns
  **nothing**. The only occurrence in the repo is the source proposal at
  `sdd/proposals/workingmemory_toolcalls.md`. Every name in this document is
  new and unclaimed.
- ~~`parrot.tools.ToolResponse`~~ — no `ToolResponse` class exists anywhere in
  `parrot/tools/`. The standardized result model is `ToolResult`
  (parrot/tools/abstract.py:250).
- ~~`CompressionTee` storing successful results~~ — it stores only on lossy
  compression or error. Call sites at `manager.py:2079` and `manager.py:2467`
  both pass `reason="error"`.
- ~~a live `CompressionReport` listener on `ToolManager`~~ — the report class
  exists but is not wired; its own docstring (report.py:102-104) says wiring a
  live listener "is future work, out of this module's scope".
- ~~`AbstractTool.returns_voucher`~~ — proposed by this brainstorm, does not
  exist yet.
- ~~`read_omitted_content` as a tool-payload recovery path~~ — it recovers
  **conversation-compaction omissions** from an `OmissionStore`
  (parrot/memory/compaction/recover.py), not working-memory datasets. It is a
  sibling channel, not the redemption mechanism.
- ~~a durable / cross-process voucher store~~ — FEAT-538 Delivery A is
  explicitly in-process only (`task_memory/__init__.py` warning block). Nothing
  in this feature survives a restart.

---

## Parallelism Assessment

- **Internal parallelism**: Moderate. Three genuinely separable strands — (1)
  the voucher model plus the generic shape summarizer, a pure leaf module with
  no manager coupling; (2) the `ToolManager` stage plus the `AbstractTool` /
  `@tool` opt-in flag; (3) the savings-and-fidelity harness built on
  `CompressionReport`. Strand 1 is a hard dependency of strands 2 and 3;
  strands 2 and 3 can then proceed concurrently. That said, strands 2 and 3
  both ultimately touch `manager.py`.
- **Cross-feature independence**: `parrot/tools/manager.py` is the contended
  file. Per this repo's memory, FEAT-550 (token-budget-bedrock) is in flight
  with a worktree already created, and it touches budget/compression territory.
  `parrot/tools/working_memory/` and `parrot/tools/compression/` are also the
  home of FEAT-538 and FEAT-380 follow-up work. A collision check against
  in-flight specs is required before `/sdd-task`.
- **Recommended isolation**: `per-spec`
- **Rationale**: The parallelism that exists is shallow and converges on a
  single high-traffic file. Two agents editing `manager.py` concurrently would
  spend more effort reconciling than the overlap saves, and the observer's
  ordering invariants mean a merge conflict there is a correctness risk, not
  just a textual one. One worktree, sequential tasks.

---

## Open Questions

- [x] Does this feature include the small-model executor? — *Owner: Jesus*: No. Contract + voucher only; the executor is a follow-up feature that this one establishes the baseline for.
- [x] Is the voucher a new record or a projection of `InvocationRecord`? — *Owner: Jesus*: A projection. One source of truth, so the voucher and the journal can never disagree.
- [x] Which successful results get vouchered? — *Owner: Jesus*: Opt-in per tool, not a size threshold and not everything.
- [x] How far must a voucher travel to be redeemable? — *Owner: Jesus*: Same turn, same process — matches FEAT-538 Delivery A. No durable or cross-agent redemption in this feature.
- [x] What happens when task memory is off? — *Owner: Jesus*: The opt-in is a silent no-op; the tool returns its full payload exactly as today.
- [x] Who produces the voucher's result summary? — *Owner: Jesus*: The runtime always infers a generic shape summary; a tool may optionally enrich or override it.
- [x] What happens when a voucher's data is gone? — *Owner: Jesus*: A structured `expired` error naming the originating tool and arguments, so the model can deliberately re-run. Never an automatic replay.
- [x] What must the performance contract prove? — *Owner: Jesus*: Context savings (tokens kept out of context per voucher) and fidelity (byte-identical data on redemption).
- [ ] Does the voucher's `dataset_id` carry the working-memory catalog key, the `EvidenceRef` (`artifact_id@version`), or both? The key is the retrieval handle; the ref is the immutable evidence identity. Carrying only the key loses version safety when an alias is overwritten. — *Owner: Jesus*
- [ ] Does the voucher fully *replace* `ToolResult.result`, or ride in `ToolResult.metadata` with the payload stripped? The former is cleaner for the model; the latter is gentler on result hooks and existing consumers. — *Owner: Jesus*
- [ ] Is a new redemption tool needed, or is `WorkingMemoryToolkit.get_result()` (tool.py:399) already the redemption surface? If the latter, where does the structured `expired` error live, given `get_result` has its own established return shape? — *Owner: Jesus*
- [ ] Should a *failed* call (`CallOutcome.ERROR` / `DENIED` / `NOT_EXECUTED`) emit a failure voucher, or keep today's error-tee behavior unchanged? The user's example includes a `status` field, implying non-success vouchers are expected. — *Owner: Jesus*
- [ ] Who owns eviction of voucher-registered entries, and does eviction produce the `expired` error? `CompressionTee` caps at `max_retained=200` and clears on `cleanup()` (tee.py:108, :309) — does the voucher path share that cap or hold its own? — *Owner: Jesus*
- [ ] How do vouchering and the compression tee avoid double-registering the same payload when both are eligible? — *Owner: Jesus*
- [ ] Should `return_direct=True` tools be allowed to opt in? A voucher returned directly to the user shows them JSON instead of an answer. Suggest forbidding the combination at registration. — *Owner: Jesus*
- [ ] Where does the savings/fidelity harness live — `benchmarks/`, or a pytest suite under `packages/ai-parrot/tests/`? Benchmarks imply a runner and stored baselines; tests imply pass/fail thresholds. — *Owner: Jesus*
- [ ] Does voucher state need to follow `ToolManager.clone()` (manager.py:2609) and `sync()` (manager.py:703), and with what sharing semantics? — *Owner: Jesus*
