---
type: feature
base_branch: dev
projects: [ai-parrot]
tags: [execution-plan, delegate, needle, llama-cpp, tool-calling, local-model]
---

# Feature Specification: Tool-Call Delegate

**Feature ID**: FEAT-590
**Date**: 2026-09-23
**Author**: Jesus Lara (spec drafted by Claude from `sdd/proposals/tool-call-delegate.proposal.md`)
**Status**: approved
**Target version**: next minor

---

## 1. Motivation & Business Requirements

### Problem Statement

The plan-then-execute architecture (FEAT-419, hardened by FEAT-585) has two
kinds of executable step:

| Node | Who decides the arguments | Marginal cost | Failure mode |
|---|---|---|---|
| `PlanToolNode` | The plan (templates such as `{item.url}`) | 0 tokens | none at runtime; caught by the validator |
| `AgentNode` | A full LLM | tokens, seconds | everything an LLM loop can do wrong |

Nothing sits between them. A step that needs a *small runtime decision* has to
become an `AgentNode`, even though it is tool-only. Examples: picking one of k
tools based on an upstream result, deriving arguments from a short text
("BB" → `bestbuy`, "next Friday" → ISO date), or per-item triage and recovery.
That costs full-LLM tokens and latency for a decision a 121M-parameter local
model can make.

This feature adds a third step, **`DelegateToolNode`**. A tiny local model
(Needle 3 first, a llama.cpp-served GGUF model as a mandatory second backend)
proposes a tool call from a short instruction plus runtime facts. The proposal
is validated by schema and dispatched through `ToolManager.execute_tool()`.
From the dispatch point onward it behaves exactly like `PlanToolNode`. The
delegate proposes; code disposes.

The delegate is **not** an `AbstractClient`. It cannot chat, summarize or
produce free text. It exposes exactly two verbs: `propose_call()` and
`extract()` (short text only).

### Goals
- G1: A backend-agnostic `ToolCallDelegate` protocol (`propose_call`,
  `extract`, `aclose`) plus `ToolSpec` / `ToolCallProposal` Pydantic models,
  co-located in `parrot/bots/flows/plan/delegate/`. Not in `parrot/interfaces/`.
- G2: A `"delegate"` node type in the `ExecutionPlan` language. It supports
  `for_each`, `when`, `facets`, `retry` and `store_as` exactly as a tool node
  does. It adds `instruction`, `facts`, `tools`, `min_confidence`,
  `accept_when`, `on_reject` and `allow_side_effects`.
- G3: Static, zero-token validation of delegate nodes: tools exist,
  `1 ≤ len(tools) ≤ delegate.max_tools`, side-effect policy, template references.
- G4: An accept gate. The proposed name must be in `node.tools`, the
  arguments must validate against that tool's `args_schema`, the confidence
  gate must pass (only when `min_confidence` is set; an unscored proposal,
  `confidence=None`, is then **rejected**, verdict `unscored`), and the optional CEL
  `accept_when` must pass. Rejected proposals follow `on_reject`
  (`fail` | `retry_backend` | `escalate`).
- G5: Two backends behind the same protocol: `LlamaCppDelegate` (HTTP to
  `llama-server`, natively async) and `NeedleDelegate` (instance pool +
  executor). The spike (M0) decides which one is primary.
- G6: Every proposal, accepted or not, is appended to a trace log. The log is
  the audit trail and the fine-tuning dataset.
- G7: Zero behaviour change for existing tool-only plans. That includes their
  `plan_fingerprint`, so checkpointed FEAT-585 runs still resume.

### Non-Goals (explicitly out of scope)
- Any change to `PlanToolNode` *behaviour* (M5 does a signature-only refactor
  that threads the tool name through; see §7).
- Any change to `AgentNode` / `AbstractClient`.
- Auto-triggering a delegate from a `PlanToolNode` failure.
- A production fine-tuning pipeline (proposal §A.7). Traces are collected;
  training is deferred until after the spike.
- Async support inside `NeedleDelegate` beyond executor offload (wait for upstream).
- Automatic replanning on `escalate`. Escalations are recorded and surfaced
  in the manifest. They do **not** feed FEAT-585's `plan_repair`
  automatically (resolved during /sdd-spec, §8).
- Repairing delegate nodes via `plan_repair`. `PlanDelta.nodes` stays
  `List[PlanNode]`, and a delta that targets a delegate node is rejected.
- Standalone use of the delegate outside execution plans (AgentCrew, ad-hoc
  triage). The protocol is plan-agnostic, but only the plan integration ships
  (§8 Q3).
- Alternative local models beyond Needle and llama.cpp GGUF (FunctionGemma,
  Granite Nano as a separate backend). The proposal's `/sdd-brainstorm`
  alternative was not taken.

---

## 2. Architectural Design

### Overview

Everything downstream of the proposal is identical to `PlanToolNode`: validate
against the tool's `args_schema`, dispatch through
`ToolManager.execute_tool()`, write to `WorkingMemory` under the key the plan
assigned, and publish an `ArtifactRef`.

Division of labour once this exists:

```
Claude (planner)   one call, writes the ExecutionPlan
PlanToolNode       steps with args known at plan time            0 tokens
DelegateToolNode   steps that need a small decision at runtime   local CPU
Claude (analyst)   reads the manifest, never the payloads
```

**When NOT to use it.** If the arguments can be written as templates at plan
time, `PlanToolNode` is cheaper and cannot fail. The delegate earns its place
only where the alternative is an `AgentNode`.

**Spike first (resolved during /sdd-spec).** M0 is the feature's first task.
It builds the smallest `NeedleDelegate` and `LlamaCppDelegate` probes (no
pool, no node) and runs them against 50–100 cases drawn from real ai-parrot
toolkits. It then commits a decision record. Only the backend modules (M6, M7)
and the extras pin (M9) depend on it. The protocol, plan language, validator
and node (M1–M5, M8) do not, because they are backend-independent by design.
Decision rules, encoded as AC1:

- Needle base ≥ 90% exact-match → Needle is primary, confidence gate
  (option A).
- Needle < 90% but llama.cpp ≥ 90% → llama.cpp is primary. The confidence
  gate uses token logprobs if exposed, otherwise `None` (option C).
- Both < 90% → fine-tune first (option B, no confidence). If still below, the
  feature is **dropped**: M6/M7/M9 are cancelled and M1–M5/M8 are reverted or
  parked. The decision record says which.

**Plan language: discriminated union (resolved during /sdd-spec).**
`ExecutionPlan.nodes` becomes `List[AnyPlanNode]`, where
`AnyPlanNode = Annotated[Union[PlanNode, DelegatePlanNode], Discriminator(_node_kind)]`.
`_node_kind` returns the `type` key when present and `"tool"` when absent, so
every existing plan (JSON files, planner output, checkpoints) still parses.
`PlanNode.type` is `Literal["tool"]` with `exclude=True`, so a tool-only
plan's `model_dump()` and therefore its `plan_fingerprint()` stay
byte-identical (G7). `DelegatePlanNode.type` is `Literal["delegate"]` and *is*
serialised. Shared fields live on `_PlanNodeBase`. Both concrete models expose
`tool_names() -> frozenset[str]`, and every consumer that read `.tool` to
enumerate a plan's tools switches to it.

**Escalation (resolved during /sdd-spec).** `on_reject="escalate"` records
the item in `ArtifactRef.errors` with the prefix `escalate:` and counts it in
a new `ArtifactRef.escalated: int = 0`. The node reports `status="partial"`
(fan-out) or `status="error"` (single). Escalations are **always** recorded,
even under `for_each.on_item_error="skip"`, because they exist to be seen.
The analyst or `plan_repair` sees them in the manifest. Nothing replans
automatically.

### Component Diagram
```
ExecutionPlanToolkit(delegates=[primary, fallback...], delegate_trace_sink, allow_delegate_side_effects)
   │ validate_with_allowlist(plan, tm, allowed, delegates=…)            (M4, M8)
   │ build_plan_flow(plan, …, delegates=…) ── node_factories {"tool": …, "delegate": …}
   ▼
AgentsFlow ──► DelegateToolNode (subclass of PlanToolNode)                  (M5)
                 resolve instruction/facts templates (same resolver)
                 enforce delegate.max_input_chars  (reject, never truncate)
                 delegate.propose_call(instruction, tool_specs, facts)       (M1, M6/M7)
                 ACCEPT GATE: name ∈ tools · args validate · confidence · accept_when
                   ├─ accepted → _call_with_retry(args, tool=name) → execute_tool → WM.store → ArtifactRef
                   └─ rejected → on_reject: fail | retry_backend (next delegate) | escalate
                 trace_sink.record(DelegateTrace)                            (M1)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `PlanToolNode` (`plan/node.py`) | extends | `DelegateToolNode` subclasses it and reuses resolution, fan-out, storage, receipts and retry. M5 threads a `tool` name through the private dispatch helpers without changing behaviour. |
| `ExecutionPlan` / `PlanNode` (`plan/models.py`) | modifies | Discriminated union; `_PlanNodeBase`; `DelegatePlanNode`; `ArtifactRef.escalated`. |
| `validate_plan` (`plan/validator.py`) | modifies | New `delegates=` / `allow_delegate_side_effects=` kwargs; delegate rules. |
| `to_flow_definition` (`plan/compile.py`) | modifies | Emits `type="delegate"` for delegate nodes; `ensure_delegate_node_registered`. |
| `PlanGuard` (`plan/guards.py`) | uses | `accept_when` compiles with `compile_guard`. The activation gains a `proposal` map (see M5). |
| `ToolManager.execute_tool` (`tools/manager.py:1632`) | uses | The dispatch target, unchanged. |
| `AbstractTool` (`tools/abstract.py`) | modifies | `delegate_safe: bool = False` and `delegate_description: Optional[str] = None` class attributes. |
| `AbstractTool.get_schema()` (`tools/abstract.py:591`) | uses | Source of `ToolSpec.parameters`. It already strips `_context_fields`. Raw `args_schema.model_json_schema()` would leak `_permission_context` etc. |
| `build_plan_flow` (`tools/execution_plan/checkpoint.py:76`) | modifies | Adds the `"delegate"` factory. All three call sites (`toolkit.py` run, resume, child) inherit it. |
| `check_allowlist` / `validate_with_allowlist` (`catalog.py`) | modifies | Allowlist uses `tool_names()`; forwards delegate kwargs. |
| `validate_delta` (`repair.py`) | modifies | Rejects a delta targeting a delegate node (`delta_delegate_not_repairable`). |
| `ExecutionPlanToolkit` (`toolkit.py`) | modifies | New constructor kwargs; `_assert_policy` uses `tool_names()`. |
| `PlanPlanner` (`planner.py`) | modifies | Appends delegate authoring rules to the prompt **only** when delegates are configured. |

### Data Models
```python
# plan/models.py
class _PlanNodeBase(BaseModel):          # id, store_as, depends_on, when, for_each, facets, timeout, retry, description
class PlanNode(_PlanNodeBase):           # type: Literal["tool"] (exclude=True), tool, args
class DelegatePlanNode(_PlanNodeBase):   # type: Literal["delegate"], instruction, facts, tools,
                                         # min_confidence, accept_when, on_reject, allow_side_effects
AnyPlanNode = Annotated[Union[PlanNode, DelegatePlanNode], Discriminator(_node_kind)]

# plan/delegate/protocol.py
class ToolSpec(BaseModel):          # name, description, parameters (JSON Schema)
class ToolCallProposal(BaseModel):  # name | None, arguments, confidence | None, backend, latency_ms
class DelegateTrace(BaseModel):     # plan/node/item ids, instruction, tools, proposal, verdict, final_call, backend chain
```

### New Public Interfaces
See the §3 Interface Skeletons. Public entry points: `ToolCallDelegate`,
`ToolSpec`, `ToolCallProposal`, `tool_specs`, `DelegateTrace`,
`DelegateTraceSink`, `JsonlTraceSink`, `DelegateToolNode`,
`make_delegate_node_factory`, `ensure_delegate_node_registered`,
`DelegatePlanNode`, `AnyPlanNode`, `LlamaCppDelegate`, `NeedleDelegate`.

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M0: Spike + decision record | no | — | Needs judgment, model downloads and interpretation of the results |
| M1: Delegate protocol & trace | yes | Skeleton below; Pydantic v2; `JsonlTraceSink` appends through `asyncio.to_thread` | — |
| M2: AbstractTool delegate flags | yes | Two class attributes, default `False` / `None` | — |
| M3: Plan-language union | yes | `_node_kind` callable discriminator; `PlanNode.type` `exclude=True`; fingerprint AC | — |
| M4: Validator, compiler, allowlist, repair | yes | Issue codes fixed in skeleton | — |
| M5: DelegateToolNode + factory | no | Skeleton fixed | Accept-gate/on_reject interplay with `on_item_error` and receipts needs care; thinking model |
| M6: LlamaCppDelegate | no | Skeleton fixed | Depends on the M0 decision (logprobs, schema shape) |
| M7: NeedleDelegate | no | Skeleton fixed | Depends on M0 (executor choice, thread safety, confidence) |
| M8: Toolkit + planner wiring | yes | kwargs fixed below | — |
| M9: Extras + docs | yes | `needle` extra, version pinned from the M0 record | — |

### Module 0: Spike + decision record
- **Path**: `scripts/spikes/tool_call_delegate_spike.py` (new), `sdd/state/FEAT-590/spike/cases.jsonl` (new), `sdd/state/FEAT-590/spike/decision.md` (new)
- **Responsibility**: Minimal Needle and llama.cpp probes (no pool, no node)
  over 50–100 cases from real ai-parrot toolkits (web scraping, HTTP, DB,
  working memory), including abstention cases. It measures exact match
  (name + args), abstention quality, latency p50/p95 (executor vs.
  `to_thread`), instruction-length behaviour and confidence calibration. The
  output is a decision record naming the primary backend, the option (A/B/C),
  the executor choice for Needle, observed `max_input_chars` / context limits,
  and the `cactus-needle` version tested.
- **Depends on**: nothing. Gates M6, M7 and M9 only.
- **Interface Skeleton**:
  ```python
  # scripts/spikes/tool_call_delegate_spike.py  (new)
  async def run_spike(cases_path: Path, *, needle: bool, llamacpp_url: str | None) -> SpikeReport:
      """Run every case against each enabled backend; return per-backend metrics."""
  class SpikeReport(BaseModel):
      """exact_match, abstention_precision/recall, latency_p50_ms, latency_p95_ms per backend."""
  ```

### Module 1: Delegate protocol, schema adapter, trace
- **Path**: `packages/ai-parrot/src/parrot/bots/flows/plan/delegate/__init__.py`, `.../delegate/protocol.py` (new)
- **Responsibility**: The backend-agnostic contract, the `ToolManager` →
  `ToolSpec` adapter and the trace sink.
- **Depends on**: M2 (`delegate_description`)
- **Interface Skeleton**:
  ```python
  # parrot/bots/flows/plan/delegate/protocol.py  (new)
  class ToolSpec(BaseModel):
      """One tool as a delegate sees it."""
      model_config = ConfigDict(extra="forbid")
      name: str
      description: str
      parameters: Dict[str, Any]          # JSON Schema; from AbstractTool.get_schema()["parameters"]  # verified: parrot/tools/abstract.py:591

  class ToolCallProposal(BaseModel):
      """A delegate's proposed call. ``name=None`` means the model declined."""
      model_config = ConfigDict(extra="forbid")
      name: Optional[str]
      arguments: Dict[str, Any] = Field(default_factory=dict)
      confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)   # None => backend cannot score
      backend: str
      latency_ms: float = Field(ge=0.0)

  @runtime_checkable
  class ToolCallDelegate(Protocol):
      """Tool-calling-only local model. Never chats, never produces free text."""
      backend_name: str
      max_tools: int            # validator enforces 1 <= len(node.tools) <= max_tools
      max_input_chars: int      # node rejects (never truncates) longer instructions
      async def propose_call(self, instruction: str, tools: Sequence[ToolSpec],
                             facts: Optional[Mapping[str, str]] = None) -> ToolCallProposal:
          """Propose ONE call. Must not execute anything. Raises DelegateBackendError on backend failure."""
      async def extract(self, text: str, schema: Union[Type[BaseModel], Dict[str, Any]]) -> Optional[Dict[str, Any]]:
          """Short-text structured extraction; None when nothing fits."""
      async def aclose(self) -> None:
          """Release pools, processes, sessions. Idempotent."""

  class DelegateBackendError(RuntimeError):
      """The backend itself failed (process died, HTTP error, bad response). Distinct from a rejected proposal."""

  def tool_specs(tool_manager: Any, names: Sequence[str]) -> List[ToolSpec]:
      """Build specs from the live manager. AbstractTool → get_schema()["parameters"] (context fields stripped,
      $defs preserved); ToolDefinition → input_schema. Prefers delegate_description over description.
      Raises KeyError naming the missing tool."""   # get_tool: manager.py:1287; ToolDefinition.input_schema: manager.py:31-37

  class DelegateTrace(BaseModel):
      """One proposal's audit record = one fine-tuning row."""
      plan_run_id: Optional[str]; node_id: str; item_index: Optional[int]
      instruction: str; facts: Dict[str, str]; tools: List[str]
      proposal: ToolCallProposal
      verdict: Literal["accepted", "declined", "unknown_tool", "invalid_args", "low_confidence", "unscored", "guard_false", "input_too_long", "side_effect_denied", "backend_error"]
      final_call: Optional[Dict[str, Any]]   # {"name", "arguments"} actually dispatched, if any
      created_at: datetime
      # Bounded: string fields capped at the sink's max_field_chars with a "…[truncated]" marker
      # (the INPUT budget still rejects rather than truncates; only the audit copy is capped).

  class DelegateTraceSink(Protocol):
      async def record(self, trace: DelegateTrace) -> None: ...

  class JsonlTraceSink:
      """Append-only JSONL file sink. Writes via asyncio.to_thread; never raises into the node (logs instead).
      Opt-in only (default: no sink). Traces are NEVER written into FlowContext, checkpoints or the manifest."""
      def __init__(self, path: Union[str, Path], *, max_field_chars: int = 2000,
                   redact: Optional[Callable[[DelegateTrace], DelegateTrace]] = None) -> None: ...
      async def record(self, trace: DelegateTrace) -> None: ...
  ```

### Module 2: AbstractTool delegate flags
- **Path**: modifies `packages/ai-parrot/src/parrot/tools/abstract.py:333`
- **Responsibility**: The opt-in side-effect policy flag and an optional short
  description tuned for tiny models.
- **Depends on**: nothing
- **Interface Skeleton**:
  ```python
  # parrot/tools/abstract.py  (modifies, after `a2ui_hidden: bool = False`  # verified: parrot/tools/abstract.py:333)
  class AbstractTool(EventEmitterMixin, ABC):   # verified: parrot/tools/abstract.py:281
      # FEAT-590: read-only / idempotent tools opt in to being chosen by a
      # tool-call delegate. Default False — existing tools are unaffected.
      delegate_safe: bool = False
      # FEAT-590: optional short description for tiny local models; falls
      # back to `description` when None.
      delegate_description: Optional[str] = None
  ```
  Toolkit-generated tools (`ToolkitTool`) inherit the defaults. A toolkit
  marks individual methods safe with a `delegate_safe=True` attribute set on
  the generated tool instance. No decorator change in v1.

### Module 3: Plan-language discriminated union
- **Path**: modifies `packages/ai-parrot/src/parrot/bots/flows/plan/models.py`
- **Responsibility**: `_PlanNodeBase`, `PlanNode.type`, `DelegatePlanNode`,
  `AnyPlanNode`, `ExecutionPlan.nodes` union, `tool_names()`,
  `ArtifactRef.escalated`.
- **Depends on**: nothing
- **Interface Skeleton**:
  ```python
  # parrot/bots/flows/plan/models.py  (modifies)
  class _PlanNodeBase(BaseModel):
      """Fields shared by every executable plan node (moved verbatim from PlanNode)."""
      model_config = ConfigDict(extra="forbid")
      id: str; store_as: str; depends_on: List[str]; when: Optional[str]; for_each: Optional[ForEach]
      facets: FacetSpec; timeout: Optional[float]; retry: RetryPolicy; description: Optional[str]
      def _check_common(self) -> None: """id/store_as/for_each-key/self-dep/dup-dep rules, moved from PlanNode._check_node (models.py:218)."""
      def referenced_nodes(self) -> set[str]: """Overridden per subclass; base covers for_each.source."""
      def tool_names(self) -> frozenset[str]: """Every tool this node may dispatch."""

  class PlanNode(_PlanNodeBase):             # verified: models.py:173
      type: Literal["tool"] = Field(default="tool", exclude=True)   # exclude => plan_fingerprint unchanged
      tool: str
      args: Dict[str, Any] = Field(default_factory=dict)

  class DelegatePlanNode(_PlanNodeBase):
      """A runtime-decided tool call proposed by a ToolCallDelegate."""
      type: Literal["delegate"] = "delegate"
      instruction: str = Field(..., min_length=1)       # may contain {nodes.x.output}/{artifacts.x}/{item...}/{index}
      facts: Dict[str, str] = Field(default_factory=dict)  # values are templates too
      tools: List[str] = Field(..., min_length=1)       # unique; upper bound checked by validator (delegate.max_tools)
      min_confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
      accept_when: Optional[str] = None                 # CEL over ctx.proposal.* + ctx.artifacts/status/errors
      on_reject: Literal["fail", "retry_backend", "escalate"] = "fail"
      allow_side_effects: bool = False
      def referenced_nodes(self) -> set[str]: """Placeholders in instruction + facts values + for_each.source."""

  def _node_kind(value: Any) -> str:
      """Discriminator: value['type'] / value.type, defaulting to 'tool' when absent."""
  AnyPlanNode = Annotated[Union[Annotated[PlanNode, Tag("tool")], Annotated[DelegatePlanNode, Tag("delegate")]],
                          Discriminator(_node_kind)]

  class ExecutionPlan(BaseModel):            # verified: models.py:268
      nodes: List[AnyPlanNode] = Field(..., min_length=1)   # was List[PlanNode] (models.py:298)
      def node(self, node_id: str) -> AnyPlanNode: ...      # return type widened

  class ArtifactRef(BaseModel):              # verified: models.py:406
      escalated: int = 0   # items escalated by a delegate node (on_reject="escalate"); added after tracking_degraded (models.py:447)
  ```

### Module 4: Validator, compiler, allowlist, repair
- **Path**: modifies `plan/validator.py`, `plan/compile.py`,
  `tools/execution_plan/catalog.py`, `tools/execution_plan/repair.py`
- **Responsibility**: Delegate-aware static validation, compilation to
  `type="delegate"`, registration helper, allowlist over `tool_names()`, and
  refusing repair of delegate nodes.
- **Depends on**: M3 (models), M1 (`ToolCallDelegate` for `max_tools`), M2 (`delegate_safe`)
- **Interface Skeleton**:
  ```python
  # plan/validator.py  (modifies validate_plan, validator.py:112)
  def validate_plan(plan: ExecutionPlan, tool_manager: Optional[ToolManagerLike] = None, *,
                    check_guards: bool = True,
                    delegates: Optional[Sequence[ToolCallDelegate]] = None,
                    allow_delegate_side_effects: bool = False) -> ValidationReport:
      """Existing checks, plus, for each DelegatePlanNode:
        unknown_tool (per name in tools, with 'did you mean')
        duplicate_delegate_tools
        no_delegate_configured       — delegate node present but delegates is None/empty
        too_many_delegate_tools      — len(tools) > delegates[0].max_tools
        delegate_side_effect         — a tool with delegate_safe False and not (node.allow_side_effects and allow_delegate_side_effects)
        bad_accept_when              — accept_when fails compile_guard
        guard checks (_check_guard) applied to `when` unchanged
      _check_tool is skipped for delegate nodes (args are decided at run time)."""

  # plan/compile.py
  DELEGATE_NODE_TYPE = "delegate"
  def to_flow_definition(plan: ExecutionPlan) -> Any:  # verified: compile.py:38
      """type = PLAN_NODE_TYPE for PlanNode, DELEGATE_NODE_TYPE for DelegatePlanNode;
      label = description or tool or 'delegate:'+ '|'.join(tools); metadata['tools'] = sorted(tool_names())."""
  def ensure_delegate_node_registered(node_cls: Any) -> None:
      """Mirror of ensure_tool_node_registered (compile.py:133) for 'delegate'. Idempotent; raises on a foreign class."""

  # tools/execution_plan/catalog.py — check_allowlist iterates node.tool_names() (was node.tool, catalog.py:133)
  def validate_with_allowlist(plan, tool_manager, allowed_tools=None, *, check_guards: bool = True,
                              delegates: Optional[Sequence[Any]] = None,
                              allow_delegate_side_effects: bool = False) -> ValidationReport: ...

  # tools/execution_plan/repair.py — in validate_delta, after `original_node = original[node.id]` (repair.py:130):
  #   isinstance(original_node, DelegatePlanNode) -> ValidationIssue(code="delta_delegate_not_repairable")
  ```

### Module 5: DelegateToolNode + factory
- **Path**: `packages/ai-parrot/src/parrot/bots/flows/plan/delegate/node.py` (new); modifies `plan/node.py` (signature-only refactor)
- **Responsibility**: Execute a `DelegatePlanNode`: resolve templates, enforce
  the input budget, propose, gate, dispatch via the inherited path, apply
  `on_reject`, and record traces.
- **Depends on**: M1, M3
- **Interface Skeleton**:
  ```python
  # plan/node.py  (modifies — NO behaviour change; every existing test must pass unmodified)
  #   _call_with_retry(self, args, *, index=None, tool: Optional[str] = None)   # verified: node.py:645
  #   _dispatch(self, args, *, tool: str)                                       # verified: node.py:717
  #   _begin_attempt(self, session, *, attempt, index, tool: str)               # verified: node.py:735
  #   _refuse_unknown_retry(..., tool: str) ; _store(..., tool: str)            # verified: node.py:836, 443
  #   `tool` defaults to self.plan_node.tool inside PlanToolNode; all 8 `self.plan_node.tool` reads
  #   (node.py:213,473,476,679,713,727,756,854) go through the threaded name.
  #   New overridable hook used by _run_single (node.py:230) and run_item (node.py:303):
  async def _invoke(self, prior: Mapping[str, ArtifactRef], bodies: Mapping[str, Any], *,
                    item: Any = None, index: Optional[int] = None) -> "_Attempt":
      """PlanToolNode: resolve args, _call_with_retry(args, tool=self.plan_node.tool). Returns _Attempt."""
  #   _Attempt (node.py:887) gains `tool: str` so _store records the tool actually dispatched.

  # plan/delegate/node.py  (new)
  class DelegateRejectedError(ToolExecutionError):
      """Proposal failed the accept gate and on_reject='fail' (or the chain was exhausted)."""
  class DelegateEscalation(DelegateRejectedError):
      """on_reject='escalate'; always recorded, message prefixed 'escalate:'."""

  class DelegateToolNode(PlanToolNode):     # PlanToolNode verified: plan/node.py:108
      plan_node: DelegatePlanNode           # type: ignore[assignment] — narrowed field
      delegates: Tuple[Any, ...]            # ordered chain; [0] primary
      trace_sink: Optional[Any] = None
      async def _invoke(self, prior, bodies, *, item=None, index=None) -> "_Attempt":
          """resolve instruction+facts (self._resolve_args) → len check vs max_input_chars → tool_specs →
          propose_call → gate → _call_with_retry(args, index=index, tool=proposal.name).
          Gate order: declined(name None) → unknown_tool → invalid_args → side_effect_denied
          → confidence gate: skipped entirely when node.min_confidence is None; otherwise
            confidence None → `unscored` (REJECT, §8 Q-S8), confidence < min → `low_confidence`
          → guard_false (accept_when).
          invalid_args = any key not in the tool's schema properties, missing required keys, or
          AbstractTool.validate_args(**args) raising (abstract.py:719); ToolDefinition → shape check only.
          The ORIGINAL proposal arguments (not a model dump) are dispatched, so ToolManager.execute_tool
          coerces/validates exactly once as it does for PlanToolNode.
          side_effect_denied = runtime re-check of the static policy against the LIVE tool object
          (delegate_safe, or node.allow_side_effects AND host allow_delegate_side_effects) — mutable
          tool metadata can never widen authority between validation and dispatch.
          on_reject: fail → DelegateRejectedError; retry_backend → next delegate in chain, then fail;
          escalate → DelegateEscalation. DelegateBackendError counts as a rejection (verdict backend_error).
          One DelegateTrace per proposal (including each retry_backend hop)."""
      # _run_fan_out override: escalations are recorded even when on_item_error='skip'
      #   and counted into ArtifactRef.escalated; status 'partial'.
      # single node: escalation → ArtifactRef(status='error', errors=['escalate: …'], escalated=1), NOT raised.
      # Escalation is INTENTIONALLY TERMINAL in v1: fan-out → 'partial' (not repair-eligible,
      # repair.py:49-60); single → 'error' but delegate nodes are refused by validate_delta (M4).

  def make_delegate_node_factory(tool_manager: Any, working_memory: Any, delegates: Sequence[Any], *,
                                 trace_sink: Optional[Any] = None, permission_context: Optional[Any] = None,
                                 plan_run_id: Optional[str] = None, step_mapping: Optional[Mapping[str, str]] = None
                                 ) -> Callable[[Any, Set[str], Set[str]], DelegateToolNode]:
      """Mirror of make_tool_node_factory (plan/node.py:1072), additionally closing over the delegate chain."""
  ```
  `accept_when` activation: the existing `PlanGuard.evaluate` activation
  (`artifacts`, `status`, `errors`, guards.py:117) plus
  `proposal = {"name", "arguments", "confidence"}`. `PlanGuard.evaluate`
  gains an optional `extra: Mapping[str, Any] | None = None` keyword that
  merges into the activation. This is additive, and `when` callers are
  unchanged.

### Module 6: LlamaCppDelegate
- **Path**: `packages/ai-parrot/src/parrot/bots/flows/plan/delegate/llamacpp.py` (new)
- **Responsibility**: An HTTP client for `llama-server --parallel N`. Each call
  sets `json_schema` to a `oneOf` of `{name: const, arguments: <tool schema>}`
  per tool, plus a `{name: null}` decline branch. Natively async over
  `aiohttp`; no pool. Confidence comes from token logprobs if M0 shows they
  are usable, otherwise `None`.
- **Depends on**: M1, M0 (decision record)
- **Interface Skeleton**:
  ```python
  class LlamaCppDelegate:   # satisfies ToolCallDelegate
      backend_name = "llamacpp"
      def __init__(self, base_url: str, *, model: Optional[str] = None, max_tools: int = 5,
                   max_input_chars: int = 4000, timeout: float = 30.0, use_logprobs: bool = False) -> None: ...
      async def propose_call(self, instruction, tools, facts=None) -> ToolCallProposal: ...
      async def extract(self, text, schema) -> Optional[Dict[str, Any]]: ...
      async def aclose(self) -> None: """Close the aiohttp.ClientSession (lazily created)."""
  ```
  No `llama-cpp-python` dependency. The pyproject comment near the
  `security` extra records why that package is avoided (native compile).

### Module 7: NeedleDelegate
- **Path**: `packages/ai-parrot/src/parrot/bots/flows/plan/delegate/needle.py` (new)
- **Responsibility**: Needle 3 via `cactus-needle`. An instance pool keyed by
  `frozenset(tool_names)` with `asyncio.Queue` checkout (acquire → `reset()`
  → `complete()` → release). Executor per the M0 record (`ProcessPoolExecutor`
  by default, `asyncio.to_thread` only if M0 shows the GIL is released). Facts
  map onto Needle's fixed `system` keys (`date`, `locale`, …); other facts
  are folded into the instruction text. It never calls `agent.run()`.
  Process-executor work runs in a **top-level, picklable** worker function
  that owns a per-process instance cache, because bound methods and live
  Needle objects are not pickled. Shutdown is idempotent and owned by the
  toolkit (via `aclose`), never by a node.
  `needle` is imported lazily, and a missing extra raises an `ImportError`
  naming `ai-parrot[needle]`.
- **Depends on**: M1, M0
- **Interface Skeleton**:
  ```python
  class NeedleDelegate:   # satisfies ToolCallDelegate
      backend_name = "needle"
      max_tools = 5
      def __init__(self, *, weights: Optional[str] = None, pool_size: int = 4,
                   executor: Literal["process", "thread"] = "process", max_input_chars: int = 1000) -> None: ...
      async def propose_call(self, instruction, tools, facts=None) -> ToolCallProposal: ...
      async def extract(self, text, schema) -> Optional[Dict[str, Any]]: ...
      async def aclose(self) -> None: """Shut the executor down and drop pools. Idempotent."""
  ```

### Module 8: Toolkit + planner wiring
- **Path**: modifies `tools/execution_plan/checkpoint.py`, `tools/execution_plan/toolkit.py`, `tools/execution_plan/planner.py`
- **Responsibility**: Thread the delegate chain from the toolkit into
  validation and every `build_plan_flow` call site, and teach the planner the
  delegate node only when delegates are configured.
- **Depends on**: M4, M5
- **Interface Skeleton**:
  ```python
  # checkpoint.py — build_plan_flow(..., delegates: Sequence[Any] = (), delegate_trace_sink: Optional[Any] = None)  # verified: checkpoint.py:76
  #   when delegates: ensure_delegate_node_registered(DelegateToolNode); node_factories["delegate"] = make_delegate_node_factory(...)
  #   (node_factories={"tool": factory} at checkpoint.py:103)
  # toolkit.py — ExecutionPlanToolkit.__init__(..., delegates: Optional[Sequence[ToolCallDelegate]] = None,
  #   delegate_trace_sink: Optional[DelegateTraceSink] = None, allow_delegate_side_effects: bool = False, **kwargs)
  #   (after `task_memory_runtime: Optional["TaskMemoryRuntime"] = None,` toolkit.py:136)
  #   forwards to validate_with_allowlist and all build_plan_flow sites (toolkit.py:337, 593, 1072);
  #   _assert_policy uses node.tool_names() (toolkit.py:581). Toolkit teardown awaits delegate.aclose().
  # planner.py — _DELEGATE_RULES appended to _PLANNING_RULES (planner.py:42) only when delegates configured;
  #   the catalog marks delegate_safe tools.
  ```

### Module 9: Extras + docs
- **Path**: modifies `packages/ai-parrot/pyproject.toml` (new `needle` extra; **not** added to `all`); new `docs/execution_plan/tool-call-delegate.md`
- **Responsibility**: Optional dependency, pinned to the version M0 tested.
  User docs: when to use it and when not, the node shape, the accept gate,
  `on_reject`, the side-effect policy and trace collection.
- **Depends on**: M0, M7

---

## 4. Test Specification

Tests live in `packages/ai-parrot/tests/bots/flows/plan/` (existing
`test_node.py`, `test_plan.py`) and `packages/ai-parrot/tests/tools/execution_plan/`.
Backends are replaced by a `FakeDelegate` (scripted proposals). No test needs
Needle or a live `llama-server`. Live backend tests are marked
`@pytest.mark.integration` and skip without `NEEDLE_WEIGHTS` / `LLAMACPP_URL`.

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_tool_specs_uses_get_schema_and_strips_context` | M1 | No `_permission_context` in parameters; `delegate_description` wins |
| `test_tool_specs_unknown_tool_raises` | M1 | `KeyError` names the tool |
| `test_proposal_confidence_bounds` | M1 | 0..1 or None |
| `test_jsonl_sink_appends_and_never_raises` | M1 | I/O error is logged, not raised |
| `test_abstract_tool_delegate_defaults` | M2 | `delegate_safe is False`, `delegate_description is None` |
| `test_plan_without_type_parses_as_tool` | M3 | Legacy JSON plans are still valid |
| `test_tool_plan_fingerprint_unchanged` | M3 | `plan_fingerprint` of a tool-only plan equals a hash frozen from the current code |
| `test_delegate_node_roundtrip` | M3 | Dump → validate keeps `type="delegate"` |
| `test_delegate_referenced_nodes_include_instruction_and_facts` | M3 | Undeclared placeholder → ValueError |
| `test_delegate_store_as_for_each_rules` | M3 | Inherits the per-item key rules |
| `test_validator_delegate_rules` | M4 | One test per issue code in M4 |
| `test_compile_emits_delegate_type` | M4 | NodeDefinition type/label/metadata |
| `test_ensure_delegate_node_registered_idempotent` | M4 | Second call no-op; foreign class raises |
| `test_allowlist_covers_delegate_tools` | M4 | `tool_not_allowed` per disallowed delegate tool |
| `test_delta_targeting_delegate_rejected` | M4 | `delta_delegate_not_repairable` |
| `test_plan_tool_node_unchanged_after_refactor` | M5 | Existing `test_node.py` passes unmodified |
| `test_delegate_accept_dispatches_proposed_tool` | M5 | `execute_tool` called with the proposed name/args; ArtifactRef ok |
| `test_delegate_gate_verdicts` | M5 | declined / unknown_tool / invalid_args / low_confidence / unscored / guard_false / input_too_long each rejected with the right trace verdict |
| `test_confidence_gate_unscored` | M5 | `min_confidence=None` → gate skipped for any confidence; `min_confidence` set + `confidence=None` → rejected `unscored`, never coerced to 0 or 1 |
| `test_on_reject_retry_backend_uses_next_delegate` | M5 | Chain hop, then fail when exhausted |
| `test_on_reject_escalate_recorded_even_with_skip` | M5 | `escalated` count, `escalate:` prefix, status partial |
| `test_single_node_escalate_returns_error_ref` | M5 | Not raised |
| `test_backend_error_is_rejection` | M5 | verdict `backend_error` |
| `test_rejected_proposal_never_dispatches` | M5 | `execute_tool` not awaited for every rejection verdict |
| `test_extra_arg_keys_rejected` | M5 | `invalid_args` on unknown keys (pydantic would ignore them) |
| `test_side_effect_rechecked_at_dispatch` | M5 | Tool flipped to unsafe after validation → `side_effect_denied` |
| `test_tool_specs_supports_tooldefinition` | M1 | `input_schema` path |
| `test_checkpoint_holds_no_traces` | M8 | Checkpoint projection carries no proposal/trace payloads |
| `test_trace_per_proposal` | M5 | One trace per hop |
| `test_llamacpp_schema_oneof` | M6 | Request body built correctly (aiohttp mocked) |
| `test_needle_lazy_import_error_message` | M7 | Mentions `ai-parrot[needle]` |
| `test_needle_pool_keyed_by_toolset` | M7 | One pool per frozenset (engine stubbed) |
| `test_toolkit_threads_delegates_to_all_build_sites` | M8 | Run, resume and child flows get the delegate factory |
| `test_planner_rules_only_with_delegates` | M8 | Prompt has no delegate rules by default |

### Integration Tests
| Test | Description |
|---|---|
| `test_plan_with_delegate_fan_out_end_to_end` | Tool node → delegate `for_each` triage (FakeDelegate) → manifest carries refs, escalations, traces |
| `test_checkpointed_tool_plan_resumes_after_upgrade` | A FEAT-585 checkpoint written before M3 resumes (fingerprint stable) |
| `test_live_llamacpp_delegate` (integration marker) | Live `llama-server` when `LLAMACPP_URL` is set |

---

## 5. Acceptance Criteria

- [ ] **AC1 (spike gate)**: `sdd/state/FEAT-590/spike/decision.md` exists
  with ≥ 50 cases, per-backend exact-match / abstention / p50 / p95 latency,
  and a decision under the rules in §2: primary backend, option A/B/C,
  Needle executor, tested `cactus-needle` version. If the outcome is "drop",
  M6/M7/M9 are cancelled and the record says what happens to M1–M5/M8.
- [ ] AC2: A tool-only `ExecutionPlan` without a `type` key parses, and its
  `plan_fingerprint()` is byte-identical to the pre-feature value.
- [ ] AC3: A plan with a `"type": "delegate"` node validates, compiles to a
  `NodeDefinition(type="delegate")` and runs through `AgentsFlow` using
  `FakeDelegate`.
- [ ] AC4: `validate_plan` reports every delegate issue code in M4 in one pass,
  and `len(tools) > delegate.max_tools` is an error.
- [ ] AC5: A delegate node listing a tool with `delegate_safe=False` fails
  validation unless `allow_side_effects: true` **and** the toolkit has
  `allow_delegate_side_effects=True`.
- [ ] AC6: Instructions over `max_input_chars` are rejected (verdict
  `input_too_long`), never truncated.
- [ ] AC7: With `min_confidence` unset, the confidence gate is skipped. With
  it set, a proposal with `confidence is None` is rejected (verdict
  `unscored`, then `on_reject` applies). `None` is never coerced to 0 or 1.
- [ ] AC8: Accepted proposals are dispatched **only** through
  `ToolManager.execute_tool()`, with the node's `permission_context`, and
  stored exactly as a `PlanToolNode` stores them.
- [ ] AC9: `on_reject` semantics hold: `fail` and `retry_backend` (then
  fail), and `escalate` always recorded with an `escalated` count.
- [ ] AC9b: A rejected proposal (any verdict) **never** calls
  `ToolManager.execute_tool`. Proposals with unknown or extra argument keys
  are rejected as `invalid_args`.
- [ ] AC9c: The side-effect policy is re-checked at dispatch time against the
  live tool (`side_effect_denied`), in addition to static validation.
- [ ] AC10: Every proposal (including each `retry_backend` hop) produces
  exactly one `DelegateTrace` when a sink is configured. A failing sink never
  fails the node. Traces never appear in `FlowContext.results`, checkpoints
  or the manifest, and trace string fields are capped at `max_field_chars`.
- [ ] AC11: The existing `packages/ai-parrot/tests/bots/flows/plan/` and
  `packages/ai-parrot/tests/tools/execution_plan/` suites pass **unmodified**.
- [ ] AC12: `plan_repair` refuses a delta targeting a delegate node
  (`delta_delegate_not_repairable`).
- [ ] AC13: The planner prompt contains no delegate rules unless the toolkit
  has delegates.
- [ ] AC14: Importing `parrot.bots.flows.plan` does not import `needle` or
  open network connections. Backends are lazy.
- [ ] AC15: `ruff check` is clean on changed files; `pytest
  packages/ai-parrot/tests/bots/flows/plan/ packages/ai-parrot/tests/tools/execution_plan/ -v` passes.
- [ ] AC16: `docs/execution_plan/tool-call-delegate.md` covers when to use
  the delegate and when not, the node shape, the gate, `on_reject`, the
  side-effect policy and traces.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor.** Verified against `d689c43c8` (dev, 2026-09-23).

### Verified Imports
```python
from parrot.bots.flows.plan import (   # verified: plan/__init__.py:13-44
    ArtifactRef, ExecutionPlan, ForEach, PlanNode, PlanToolNode, ToolExecutionError,
    compile_guard, ensure_tool_node_registered, make_tool_node_factory,
    to_flow_definition, validate_plan, ValidationIssue, ValidationReport,
)
from parrot.bots.flows.plan.guards import PlanGuard, GuardCompilationError   # guards.py:35
from parrot.bots.flows.plan.models import ARTIFACT_REF_RE, NODE_REF_RE, _iter_strings  # models.py:64,66,511
from parrot.bots.flows.plan.node import _Attempt, _artifact_refs            # node.py:887,1021 (private; same package only)
from parrot.bots.flows.core.node import Node                               # imported as _BaseNode at node.py:88
from parrot.bots.flows.flow.flow import NODE_REGISTRY, register_node       # flow.py:133,158
from parrot.bots.flows.flow.definition import NodeDefinition, EdgeDefinition, FlowDefinition, FlowMetadata  # compile.py:55
from parrot.tools.execution_plan import ExecutionPlanToolkit               # execution_plan/__init__.py:33
from parrot.tools.execution_plan.checkpoint import build_plan_flow         # checkpoint.py:76
from parrot.tools.execution_plan.catalog import check_allowlist, validate_with_allowlist  # catalog.py:113,145
from parrot.tools.execution_plan.runs import plan_fingerprint              # runs.py:71
```

### Existing Class Signatures
```python
# plan/models.py
class ForEach(BaseModel):   # line 111; extra="forbid", populate_by_name; source must fullmatch ARTIFACT_REF_RE; alias "as"
class PlanNode(BaseModel):  # line 173; extra="forbid"; fields lines 205-215; _check_node line 218; referenced_nodes line 242
class ExecutionPlan(BaseModel):  # line 268; nodes: List[PlanNode] line 298; _check_plan line 302 (dup ids, deps, undeclared refs, static key collisions, acyclic)
class ArtifactRef(BaseModel):    # line 406; status Literal["ok","skipped","partial","error"]; tracking_degraded line 447

# plan/node.py
class PlanToolNode(_BaseNode):   # line 108; frozen; fields plan_node: PlanNode (134), tool_manager, working_memory, permission_context, plan_run_id, step_mapping
    async def execute(self, ctx, deps=None, **kwargs) -> ArtifactRef          # line 179
    async def _run_single(self, prior) -> ArtifactRef                          # line 230
    async def _run_fan_out(self, prior) -> ArtifactRef                         # line 250; per-item run_item line ~292, guarded() applies on_item_error
    def _resolve_args(self, value, prior, bodies, *, item=None, index=None)    # line 361 (sync)
    async def _artifact_bodies(self, value) -> Dict[str, Any]                  # line 422
    async def _store(self, key, payload, *, index, producer_call_id=None)      # line 443
    async def _call_with_retry(self, args, *, index=None) -> _Attempt          # line 645
    async def _dispatch(self, args) -> Any                                     # line 717 — execute_tool(self.plan_node.tool, args, permission_context=...)
    def _begin_attempt(self, session, *, attempt, index)                       # line 735
    def _refuse_unknown_retry(self, session, receipt, exc)                     # line 836
class _Attempt(NamedTuple)   # line 887: payload, producer_call_id, degraded
def make_tool_node_factory(tool_manager, working_memory, *, permission_context=None, plan_run_id=None, step_mapping=None)  # line 1072

# plan/guards.py
class PlanGuard:  # line 70; evaluate(artifacts, statuses=None, errors=0) -> bool line 95; activation dict line 117
def compile_guard(expression: Optional[str]) -> Optional[PlanGuard]   # line 128

# plan/compile.py
PLAN_NODE_TYPE = "tool"  # line 33
def to_flow_definition(plan) -> FlowDefinition   # line 38; per-node loop line 71
def node_config(plan_node) -> Dict               # line 112 — model_dump(mode="json", exclude_none=False)
def ensure_tool_node_registered(node_cls) -> None  # line 133

# plan/validator.py
def validate_plan(plan, tool_manager=None, *, check_guards=True) -> ValidationReport   # line 112; per-node loop line 149-154
def _check_tool(node, tool_manager, report)   # line 159
_CONTEXT_ARGS = frozenset({...})              # line 385

# tools/manager.py
class ToolManager:
    def get_tool(self, tool_name: str) -> Optional[Any]   # line 1287
    def list_tools(self) -> List[str]                     # line 1307
    async def execute_tool(self, tool_name: str, parameters: Dict[str, Any],
                           permission_context: Optional["PermissionContext"] = None, *,
                           return_tool_result: bool = False) -> Any   # line 1632

# tools/abstract.py
class AbstractTool(EventEmitterMixin, ABC):   # line 281; name 296, description 297, args_schema 298, a2ui_hidden 333
    def get_schema(self) -> Dict[str, Any]    # line 591 — {"name","description","parameters"}; strips args_schema._context_fields (line 648)

# tools/execution_plan/checkpoint.py
def build_plan_flow(plan, *, run, tool_manager, working_memory, agent_registry, permission_context,
                    step_mapping, store, durable_store) -> PlanFlow   # line 76; node_factories={"tool": factory} line 103

# tools/execution_plan/toolkit.py
class ExecutionPlanToolkit(AbstractToolkit):   # line 83; __init__ line 120 (kwargs-only); build_plan_flow calls at 337, 593, 1072; _assert_policy line 578

# tools/execution_plan/runs.py
def plan_fingerprint(plan: ExecutionPlan) -> str   # line 71 — sha256(json.dumps(plan.model_dump(mode="json"), sort_keys=True, separators=(",",":")))

# tools/execution_plan/models.py
class PlanDelta(BaseModel): nodes: List[PlanNode]   # line 195 — stays PlanNode-only
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `DelegateToolNode` | `PlanToolNode._call_with_retry` | inheritance + `tool=` kwarg | `plan/node.py:645` |
| `DelegateToolNode` | `ToolManager.execute_tool` | inherited `_dispatch` | `tools/manager.py:1632` |
| `tool_specs` | `ToolManager.get_tool` → `AbstractTool.get_schema` | call | `manager.py:1287`, `abstract.py:591` |
| accept gate args check | `tool.args_schema.model_validate` | call | `abstract.py:298` |
| `accept_when` | `compile_guard` / `PlanGuard.evaluate` | call (+ `extra=`) | `guards.py:128`, `guards.py:95` |
| delegate factory | `build_plan_flow` `node_factories` | dict entry | `checkpoint.py:103` |
| registration | `register_node("delegate")` | call | `flow/flow.py:158` |

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot.interfaces.delegate`~~. `parrot.interfaces` is a mixins package, so the delegate lives in `parrot.bots.flows.plan.delegate`.
- ~~`ToolCallDelegate`, `NeedleDelegate`, `LlamaCppDelegate`, `DelegateToolNode`, `make_delegate_node_factory`, `ensure_delegate_node_registered`, `DelegatePlanNode`, `AnyPlanNode`, `_PlanNodeBase`~~. All new.
- ~~`AbstractTool.delegate_safe` / `delegate_description`~~. New in M2.
- ~~`PlanNode.type`~~ and ~~`ArtifactRef.escalated`~~. New in M3.
- ~~`TemplateResolutionError` in `plan/`~~. It lives in `parrot.bots.flows.crew.tool_node` (line 74) and is **not** raised by `PlanToolNode._resolve_args`. Delegate template errors surface as `ToolExecutionError`.
- ~~JSONPath (`$.x.output.rows[*]`) in `for_each`~~. The proposal's example is wrong: `for_each.source` must be exactly `{artifacts.<id>}`, and the path goes in `select` (`rows[]`).
- ~~`ToolSchemaAdapter` as a schema-export type~~. Use `AbstractTool.get_schema()`.
- ~~`llama-cpp-python` dependency~~. `LlamaCppDelegate` speaks HTTP to `llama-server`.
- ~~`agent.run()` in NeedleDelegate~~. It executes Python functions itself and is forbidden here. Only `complete()` is used.
- `cactus-needle` API (`needle.Needle(tools=, system=, weights=)`, `.complete()`, `.reset()`, response keys): **unverified — check before use**, taken from proposal §A.1 (docs read 2026-09-20). M0 verifies it.

### Edit Sites (Blueprint Anchors)

Verified against: `d689c43c8`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/bots/flows/plan/models.py` | MODIFY | `class PlanNode(BaseModel):` | `models.py:173` | 1 |
| `packages/ai-parrot/src/parrot/bots/flows/plan/models.py` | MODIFY | `    nodes: List[PlanNode] = Field(..., min_length=1)` | `models.py:298` | 1 |
| `packages/ai-parrot/src/parrot/bots/flows/plan/models.py` | MODIFY | `    tracking_degraded: bool = False` | `models.py:447` | 1 |
| `packages/ai-parrot/src/parrot/bots/flows/plan/compile.py` | MODIFY | `    for plan_node in plan.nodes:` | `compile.py:71` | 1 |
| `packages/ai-parrot/src/parrot/bots/flows/plan/compile.py` | MODIFY | `def ensure_tool_node_registered(node_cls: Any) -> None:` | `compile.py:133` | 1 |
| `packages/ai-parrot/src/parrot/bots/flows/plan/validator.py` | MODIFY | `def validate_plan(` | `validator.py:112` | 1 |
| `packages/ai-parrot/src/parrot/bots/flows/plan/validator.py` | MODIFY | `        _check_tool(node, tool_manager, report)` | `validator.py:150` | 1 |
| `packages/ai-parrot/src/parrot/bots/flows/plan/guards.py` | MODIFY | `        activation: Dict[str, Any] = {` | `guards.py:117` | 1 |
| `packages/ai-parrot/src/parrot/bots/flows/plan/node.py` | MODIFY | `    async def _run_single(self, prior: Mapping[str, ArtifactRef]) -> ArtifactRef:` | `node.py:230` | 1 |
| `packages/ai-parrot/src/parrot/bots/flows/plan/node.py` | MODIFY | `                args = self._resolve_args(self.plan_node.args, prior, bodies, item=item, index=index)` | `node.py:303` | 1 |
| `packages/ai-parrot/src/parrot/bots/flows/plan/node.py` | MODIFY | `    async def _call_with_retry(self, args: Dict[str, Any], *, index: Optional[int] = None) -> "_Attempt":` | `node.py:645` | 1 |
| `packages/ai-parrot/src/parrot/bots/flows/plan/node.py` | MODIFY | `    async def _dispatch(self, args: Dict[str, Any]) -> Any:` | `node.py:717` | 1 |
| `packages/ai-parrot/src/parrot/bots/flows/plan/node.py` | MODIFY | `self.plan_node.tool` (all reads) | `node.py:213` first | 8 — replace every one; no single anchor |
| `packages/ai-parrot/src/parrot/bots/flows/plan/__init__.py` | MODIFY | `from .validator import (` | `__init__.py:39` | 1 |
| `packages/ai-parrot/src/parrot/bots/flows/plan/delegate/__init__.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/bots/flows/plan/delegate/protocol.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/bots/flows/plan/delegate/node.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/bots/flows/plan/delegate/llamacpp.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/bots/flows/plan/delegate/needle.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/tools/abstract.py` | MODIFY | `    a2ui_hidden: bool = False` | `abstract.py:333` | 1 |
| `packages/ai-parrot/src/parrot/tools/execution_plan/catalog.py` | MODIFY | `        if node.tool not in allowed_set:` | `catalog.py:133` | 1 |
| `packages/ai-parrot/src/parrot/tools/execution_plan/repair.py` | MODIFY | `        original_node = original[node.id]` | `repair.py:130` | 1 |
| `packages/ai-parrot/src/parrot/tools/execution_plan/checkpoint.py` | MODIFY | `        node_factories={"tool": factory},` | `checkpoint.py:103` | 1 |
| `packages/ai-parrot/src/parrot/tools/execution_plan/toolkit.py` | MODIFY | `        task_memory_runtime: Optional["TaskMemoryRuntime"] = None,` | `toolkit.py:136` | 1 |
| `packages/ai-parrot/src/parrot/tools/execution_plan/toolkit.py` | MODIFY | `        needed = {node.tool for node in run.metadata.plan.nodes}` | `toolkit.py:581` | 1 |
| `packages/ai-parrot/src/parrot/tools/execution_plan/planner.py` | MODIFY | `_PLANNING_RULES = """\` | `planner.py:42` | 1 |
| `packages/ai-parrot/pyproject.toml` | MODIFY | `all = [` (line-anchored `^all = \[`; `-F` matches `notify-all = [` too) | `pyproject.toml:869` | 1 (anchored) |
| `scripts/spikes/tool_call_delegate_spike.py` | CREATE | — | — | — |
| `sdd/state/FEAT-590/spike/decision.md` | CREATE | — | — | — |
| `docs/execution_plan/tool-call-delegate.md` | CREATE | — | — | — |
| `packages/ai-parrot/tests/bots/flows/plan/test_delegate_*.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/tools/execution_plan/test_delegate_wiring.py` | CREATE | — | — | — |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- `PlanToolNode` + `make_tool_node_factory` closure. Runtime bindings
  (manager, working memory, delegates, trace sink, `plan_run_id`) travel
  through the factory, **never** through `NodeDefinition.config`.
- `ensure_tool_node_registered`: idempotent registration that raises on a foreign class.
- `ConfigDict(extra="forbid")` on every plan model.
- `compile_guard` at construction, so a broken `accept_when` fails
  validation, not mid-flight.
- Optional extras pattern in `pyproject.toml`: lazy import plus an
  `ImportError` that names the extra.
- aiohttp only (no `httpx`/`requests`); `self.logger`; Google docstrings.

### Known Risks / Gotchas
- **Fingerprint drift.** Any serialised change to `PlanNode` changes
  `plan_fingerprint` and breaks resume of FEAT-585 checkpoints
  (`policy_mismatch`). Mitigations: `PlanNode.type` uses `exclude=True`, and
  AC2 freezes a hash. Do **not** add other defaulted fields to `PlanNode`.
- **Discriminator default.** Pydantic's field-name discriminator requires the
  tag to be present. The callable `Discriminator(_node_kind)` is what lets
  plans without `type` parse. It must handle both dicts and model instances.
- **Frozen node + concurrency.** `PlanToolNode` is frozen and fans out
  concurrently. The chosen tool must travel as a parameter (the M5 refactor),
  never as instance state.
- **Needle accuracy (C8, low).** It is out of distribution for scraping/HTTP/DB
  tools. The M0 gate protects this, and the plan/node surface doesn't change
  if the backend does.
- **Needle executor latency / thread safety (C9, low).** Assume a blocking,
  non-reentrant engine until M0 measures it.
- **5-tool ceiling.** Needle switches to retrieval above 5 tools, which makes
  it unpredictable. This is enforced statically (AC4).
- **Fine-tuned confidence is `None`.** A node that sets `min_confidence`
  rejects unscored proposals (AC7, §8 Q-S8). Plans targeting a fine-tuned
  backend (option B) must leave `min_confidence` unset and rely on schema
  validation and `accept_when`. The planner rules (M8) and the docs (M9) say so.
- **`retry_backend` and `max_tools`.** A fallback delegate whose `max_tools`
  is below `len(tools)` is skipped in the chain, not called.
- **Trace volume.** A large `for_each` triage writes one row per item per hop.
  The sink is append-only and optional, and the default is no sink.
- **Concurrent dev writers.** Other sessions commit to `dev` in the shared
  checkout. Stage explicit paths only.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `cactus-needle` | pinned by M0 | Needle 3 backend (`ai-parrot[needle]`, optional, not in `all`) |
| `aiohttp` | existing | `LlamaCppDelegate` HTTP client |
| `llama-server` (external binary) | any recent with `json_schema` | Out-of-process runtime; not a Python dependency |

---

## 8. Open Questions

- [x] Is PlanToolNode / `register_node("tool")` already implemented? — *Resolved in proposal*: Yes, landed in FEAT-419, TASK-2179 (commit `d7b4819db`).
- [x] Does FEAT-585 conflict with plan/ file changes? — *Resolved in proposal*: No. FEAT-585 declared plan/ changes as non-goals. It has since completed (all 16 tasks done, 2026-09-22), so its `repair.py`/`toolkit.py` are the current baseline.
- [x] Where should the ToolCallDelegate protocol live? — *Resolved in proposal*: NOT in `parrot/interfaces/`. It goes in `parrot/bots/flows/plan/delegate/`.
- [x] Should the spike be the first task of FEAT-590 or a separate experiment? — *Resolved during /sdd-spec*: First task (M0). It gates only M6/M7/M9 (AC1).
- [x] How does a delegate node enter the plan language? — *Resolved during /sdd-spec*: A discriminated union with a callable discriminator defaulting to `tool`, and `PlanNode.type` excluded from the dump.
- [x] What does `on_reject="escalate"` do? — *Resolved during /sdd-spec*: It records the item in the manifest (`escalate:` error prefix, `ArtifactRef.escalated`, status partial/error). There is no automatic replan, and delegate nodes are not repair-eligible in v1.
- [x] **Q-S8 (from design research S8)**: When `min_confidence` is set and a backend returns `confidence=None`, accept or reject? — *Resolved by Jesus Lara, 2026-09-23*: **reject when a threshold is set** (verdict `unscored`). With no threshold, the gate is skipped. This supersedes proposal §A.6's "gate not available" rule.
- [ ] Is the Epson 5–15% residue estimate based on observed data? — *Owner: Jesus Lara*. It doesn't block the architecture. It sets the value of the first application (proposal §A.8).
- [ ] Should the delegate support standalone use outside execution plans (AgentCrew, ad-hoc triage)? — *Owner: Jesus Lara*. v1 is plan-only, and the protocol is kept plan-agnostic so it can be added later without changes.

---

## 9. Design Research Cross-Check

> Model: `gpt-5.6-luna` · Status: completed · Transcript: `sdd/state/FEAT-590/design_research/`
> Every row is a suggestion the reviewer made; the disposition is the spec author's
> call (CONFIRM = folded into the spec, REJECT = reason recorded, ESCALATE = §8 question).

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Backward-compatible discriminated union (architecture) | CONFIRM | Matches the user decision; verified `PlanNode` extra=forbid, `nodes: List[PlanNode]`, compile hardcodes `"tool"` | §2 Overview, M3, M4 |
| S2 | Reuse dispatch/storage pipeline (architecture) | CONFIRM | `DelegateToolNode` subclasses `PlanToolNode`, and an `_invoke` hook keeps receipts/`_store` provenance | M5 |
| S3 | Delegate-pool ownership across fresh/resumed/repaired flows (architecture) | CONFIRM | Verified all 3 `build_plan_flow` sites (toolkit.py:337,593,1072); the toolkit owns `aclose` | M8, M7 |
| S4 | ToolSpec from authoritative schema, incl. `ToolDefinition.input_schema` (api) | CONFIRM | Verified `ToolDefinition` (manager.py:31) has `input_schema`, not `args_schema` | M1 |
| S5 | One runtime arg-validation contract (api) | CONFIRM | Uses `validate_args` (abstract.py:719) + unknown-key rejection, and dispatches the original args once via the manager | M5, AC9b |
| S6 | Side-effect policy from host config + re-check at dispatch (risk) | CONFIRM | Host flag already in design; added the runtime `side_effect_denied` re-check | M5, AC9c |
| S7 | Rejection/escalation as persisted outcomes (risk) | CONFIRM | Made "intentionally terminal" explicit; verified partial is not repair-eligible (repair.py:49-60) | M5, §2 |
| S8 | `confidence=None` must not silently bypass a set threshold (risk) | ESCALATE → resolved | Escalated because it contradicts proposal §A.6; the user chose reject-when-threshold-set | §8 Q-S8, M5, AC7 |
| S9 | Bounded, redacted traces kept out of checkpoints (risk) | CONFIRM | Opt-in sink, `max_field_chars`, `redact` hook, never in context/checkpoint | M1, AC10 |
| S10 | Separate backends; no llama-cpp-python; picklable worker (alternative) | CONFIRM | Already HTTP-only; added the top-level picklable worker for the process executor | M6, M7 |
| S11 | Adversarial boundary tests (testing) | CONFIRM | Added never-dispatch-on-reject, extra-keys, re-check and checkpoint-hygiene tests | §4 |
| S12 | Defer standalone AgentCrew support (alternative) | CONFIRM | Verified crew `ToolNode` calls `tool.execute()` directly; already a Non-Goal | §1 Non-Goals |

Summary: **11** confirmed · **0** rejected · **1** escalated.

---

## Worktree Strategy

- **Isolation**: ONE feature worktree `feat-FEAT-590-tool-call-delegate`. The
  `sdd-coder` engine gives each task its own sub-worktree.
- **Module dependency graph** (edges = imports / gates):
  - M1 → M2 (`tool_specs` reads `delegate_description`)
  - M4 → M1, M2, M3 (validator reads `max_tools`, `delegate_safe`, `DelegatePlanNode`)
  - M5 → M1, M3 (node uses the protocol and `DelegatePlanNode`)
  - M6 → M1, M0 · M7 → M1, M0 (decision record)
  - M8 → M4, M5
  - M9 → M0, M7
  - M0, M2, M3 have no incoming edges and run concurrently. M6/M7 run in
    parallel after M0+M1.
- **Shared files**: `plan/__init__.py` (M3 exports models; M5 exports node
  symbols) → serialize M3 before M5's export step. `plan/delegate/__init__.py`
  (created by M1; M5/M6/M7 add lazy exports) → M1 first, then M5/M6/M7
  append. `guards.py` is only M5. `toolkit.py` is only M8, which includes the
  `_assert_policy` change.
- **Exclusive resources**: M9 edits `pyproject.toml` (lockfile impact) →
  `parallel: false`. M0 downloads models and runs a local `llama-server` →
  `parallel: false`.
- **Cross-feature dependencies**: FEAT-585 (plan-then-execute-hardening) is
  already merged, and this spec's anchors are verified against it. No other
  spec must land first.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-23 | Jesus Lara / Claude | Initial draft from the FEAT-590 proposal; 3 open questions resolved at spec time; codex design research folded in (11 confirmed, 1 escalated) |
| 0.2 | 2026-09-23 | Jesus Lara | Q-S8 resolved: reject unscored proposals when `min_confidence` is set; status → approved |
