<!--
  sdd/templates/design_research.prompt.md — neutral design-research brief (FEAT-545).
  Rendered by /sdd-spec section 3b and piped to `codex exec ... --output-schema
  design_research.schema.json`.
  FORBIDDEN INPUTS: never paste the spec draft, the spec author's reasoning, a preferred
  conclusion, or any text written by the model that will author the spec. The brief carries
  ONLY the accepted exploration document (brainstorm/proposal) and verified code anchors.
  Placeholders (double-curly-brace tokens, deliberately NOT written with literal braces in
  this comment — a renderer that does a naive whole-document string replace must not also
  rewrite this sentence): problem_statement, constraints_and_goals,
  recommended_option_or_scope, code_context_paths, open_questions, question.
-->
# Independent design review — read-only

You are an independent design reviewer for **ai-parrot**, an async-first Python
framework for AI agents (aiohttp, Pydantic v2, `uv` workspace under `packages/`).
You have read-only access to the repository in your working directory.

## Rules
1. Read the code you cite. Every `affected_paths` entry must be a repo-relative
   path you actually opened; suggestions with unverifiable paths are discarded.
2. Judge the design intent below against what exists in the repository: what is
   missing, what is risky, what would be simpler, what the codebase already
   provides that the intent re-invents.
3. Do not restate the intent, do not praise it, do not write code. Propose at
   most 12 concrete, falsifiable suggestions, each tagged with a kind
   (`architecture` | `api` | `testing` | `risk` | `alternative`), a risk level and
   your confidence.
4. Output exactly ONE JSON object conforming to the schema you were given — no
   markdown fences, no prose before or after.

## Accepted design intent (verbatim from the exploration document)

### Problem statement
The Tool-Call Delegate is a well-scoped extension to the existing execution-plan
architecture at `packages/ai-parrot/src/parrot/bots/flows/plan/`. The plan
module already provides `PlanToolNode`, `make_tool_node_factory`,
`ExecutionPlan`, `ArtifactRef`, CEL guards, a static validator, and the
`NODE_REGISTRY` registration mechanism — all landed and working (FEAT-419,
TASK-2179). The delegate adds a `DelegateToolNode` that interposes a
local-model proposal step before the same `ToolManager.execute_tool` dispatch.
The interface location proposed as `parrot/interfaces/delegate.py` is incorrect
— `parrot.interfaces.*` is a bot-capability mixins package, not a contracts
home — and should co-locate in the `plan/` module. Two claims are low
confidence: Needle 3's accuracy on non-mobile toolkits and the
ProcessPoolExecutor latency profile — both gated on the spike (§10).

Origin:
The original design document, authored as a follow-up to the plan-then-execute
architecture (FEAT-419). The full source is at `sdd/state/FEAT-590/source.md`.

> Add a third kind of executable step to the plan language, between PlanToolNode
> (templates, 0 tokens) and AgentNode (full LLM). A tiny local model (Needle 3,
> 121M parameters) proposes tool calls from a short instruction plus runtime
> facts, validated by schema and dispatched through ToolManager — identical to
> PlanToolNode from the dispatch point onward.

### Constraints and goals
- **`parrot.interfaces.*` is a mixins package.** Its docstring defines it as
  "Mixins for bot functionality" — connection/capability interfaces (aws,
  database, http). Placing `ToolCallDelegate` there breaks the convention.
  The protocol and models belong in `parrot/bots/flows/plan/delegate.py` or a
  `plan/delegate/` subpackage.
  *Evidence*: F004

- **FEAT-585 (plan-then-execute-hardening) is active but non-conflicting.**
  16 tasks (TASK-3589..3604) add checkpointing, `plan_resume`, `plan_repair`.
  Explicitly declares changes to `bots/flows/plan/` models/validator/guards/
  compiler as **non-goals**. The delegate safely extends those files.
  *Evidence*: F009

- **NODE_REGISTRY registration requires Node subclass.** `register_node(name)`
  checks `issubclass(cls, Node)` and raises on duplicates. `DelegateToolNode`
  must extend `Node` from `parrot.bots.flows.core.node`.
  *Evidence*: F002

- **make_tool_node_factory closure pattern.** The factory closes over
  `tool_manager`, `working_memory`, `permission_context`, `plan_run_id`,
  `step_mapping` — runtime bindings, not plan text. `make_delegate_node_factory`
  must follow the same pattern, additionally closing over the delegate pool.
  *Evidence*: F001

- **No existing delegate_safe flag or ToolSpec.** AbstractTool has no metadata
  flags for delegation safety. `ToolSchemaAdapter` exists for Bedrock format
  adaptation but is not a standalone schema-export type.
  *Evidence*: F006

- **Design doc reference path was wrong.** The original proposal cited
  `claude/handle-only-execution-design.md` — the actual file is at
  `sdd/proposals/handle-only-execution-design.input.md`. Canonical specs:
  `sdd/specs/execution-plan-tool.spec.md` (FEAT-419) and
  `sdd/specs/plan-then-execute-hardening.spec.md` (FEAT-585).
  *Evidence*: F010

### Recommended option / probable scope
### What's New

- **`ToolCallDelegate` protocol** — `propose_call()`, `extract()`, `aclose()` verbs
- **`ToolSpec` / `ToolCallProposal`** — Pydantic models for the delegate interface
- **`NeedleDelegate`** — backend with instance pool and ProcessPoolExecutor
- **`LlamaCppDelegate`** — backend via HTTP to `llama-server --parallel N`
- **`DelegateToolNode`** — Node subclass for AgentsFlow, registered as `"delegate"`
- **`make_delegate_node_factory`** — closure parallel to `make_tool_node_factory`
- **`ensure_delegate_node_registered`** — idempotent registration helper
- **`DelegatePlanNode`** — model extending PlanNode concept with instruction, facts, tools list, confidence gate, on_reject
- **Validator rules** — tool count ≤ max_tools, side-effect policy, instruction template resolution
- **`delegate_safe`** flag on `AbstractTool` (default `False`)
- **`delegate_description`** optional override on tools
- **`tool_specs()`** — schema adapter function
- **Proposal trace log** — fine-tuning data collection
- **`ai-parrot[needle]`** and **`ai-parrot[llamacpp]`** optional extras

### What Changes

- **`plan/compile.py`** — `to_flow_definition` handles `type="delegate"` nodes
- **`plan/validator.py`** — `validate_plan` adds delegate-specific checks
- **`parrot/tools/abstract.py`** — AbstractTool gains `delegate_safe: bool = False` and `delegate_description: str | None = None`
- **`pyproject.toml`** — new optional extras for needle and llama-cpp-python

### What's Untouched (Non-Goals)

- PlanToolNode behavior — no changes
- AgentNode / AbstractClient — no changes
- Auto-triggering delegates from PlanToolNode failures
- Production fine-tuning pipeline (deferred to post-spike)
- Async support in NeedleDelegate (wait for upstream)

### Patterns to Follow

- PlanToolNode + make_tool_node_factory closure (F001)
- ensure_tool_node_registered idempotent registration (F002)
- PlanNode field structure with `ConfigDict(extra="forbid")` (F003)
- CEL guard compilation for accept_when (F007)
- Optional extras pattern in pyproject.toml (F011)

### Integration Risks

- **Needle accuracy on non-mobile toolkits** — trained on DroidCall/Mobile Actions; scraping/HTTP/DB tools are out of distribution. Spike §10 gates this. *Evidence*: F001
- **ProcessPoolExecutor latency** — safe but adds IPC overhead; `to_thread` may be viable if GIL is released. Spike §10 measures this. *Evidence*: proposal §3
- **Fine-tuned confidence=None** — the accept gate must handle missing confidence gracefully (already addressed in §6). *Evidence*: proposal §6
- **delegate_safe public API change** — default `False` means existing tools are unaffected; opt-in only. *Evidence*: F006
- **5-tool ceiling** — Needle switches to retrieval above 5 tools, making the node unpredictable. Validator must enforce `len(tools) <= delegate.max_tools`. *Evidence*: proposal §5

Original design (appendix):
**Note (research update):** The original placement at `parrot/interfaces/delegate.py` is incorrect. `parrot.interfaces.*` is a bot-capability mixins package (F004). The protocol and models should live at `parrot/bots/flows/plan/delegate.py`.

```python
# parrot/bots/flows/plan/delegate.py  (corrected location)
class ToolSpec(BaseModel):
    name: str
    description: str
    parameters: dict[str, Any]          # JSON Schema, from args_schema.model_json_schema()

class ToolCallProposal(BaseModel):
    name: str | None                    # None => model declined (off-topic / no fit)
    arguments: dict[str, Any] = {}
    confidence: float | None = None     # None => backend cannot score (e.g. fine-tuned Needle)
    backend: str
    latency_ms: float

class ToolCallDelegate(Protocol):
    max_tools: int                      # 5 for Needle; validator enforces it
    max_input_chars: int                # backend-specific budget; node enforces it

    async def propose_call(
        self, instruction: str, tools: Sequence[ToolSpec], facts: Mapping[str, str] | None = None,
    ) -> ToolCallProposal: ...

    async def extract(self, text: str, schema: type[BaseModel] | dict) -> dict | None: ...
    async def aclose(self) -> None: ...
```

Schema adapter, one function, shared by every backend:

```python
def tool_specs(tm: ToolManager, names: Sequence[str]) -> list[ToolSpec]:
    return [ToolSpec(name=t.name, description=t.description,
                     parameters=t.args_schema.model_json_schema())
            for t in (tm.get_tool(n) for n in names)]
```

### A.3. `NeedleDelegate`: concurrency model

The Needle Python API documents neither async support nor thread safety, and the agent object is stateful (`reset()` exists). Assume a blocking, non-reentrant C engine until measured.

- **Instance pool with checkout.** N instances, `asyncio.Queue` as the free list; acquire -> `reset()` -> `complete()` -> release. Pool size is the delegate's own concurrency ceiling, independent of the node's `max_concurrency`.
- **One instance per tool subset.** `Needle(tools=...)` binds the toolset at construction. Pool key = `frozenset(tool_names)`. Plans use few distinct subsets, so this stays small. About 28 MB per instance; 16 instances is under 0.5 GB.
- **Executor.** Start with `ProcessPoolExecutor` (safe regardless of GIL behaviour). Move to `asyncio.to_thread` only if the spike shows the engine releases the GIL.
- **Facts.** `facts` maps onto Needle's fixed `system` keys where they match (`date`, `locale`); anything else is folded into the instruction text.

`LlamaCppDelegate` is simpler: one `llama-server --parallel N` process with continuous batching, called over HTTP with `json_schema` set to a `oneOf` of `{name: const, arguments: <tool schema>}` per tool. Natively async; no pool needed.

### A.4. `DelegateToolNode`

**Note (research update):** Follows `PlanToolNode` pattern from `plan/node.py` (F001). Must extend `Node` from `parrot.bots.flows.core.node` (F002). Uses same `ToolManager.execute_tool()` dispatch path (F005).

```
resolve templates in `instruction` / `facts`      (same resolver as PlanToolNode)
  -> enforce max_input_chars                        (reject, never truncate silently)
  -> delegate.propose_call(instruction, tools, facts)
  -> ACCEPT GATE:
       name in node.tools
       arguments validate against that tool's args_schema
       confidence >= node.min_confidence            (skipped when confidence is None, see §6)
       optional node.`accept_when` guard (CEL, reuses plan/guards.py PlanGuard — F007)
  -> accepted: ToolManager.execute_tool() -> wm.store_result(key) -> ArtifactRef
  -> rejected: apply node.on_reject
```

`on_reject` values:

- `fail`: record a per-item error in the manifest (default).
- `retry_backend`: try the next delegate in the configured chain (Needle -> llama.cpp).
- `escalate`: collect the item into the bounded-replan input.

Every proposal, accepted or not, is appended to a trace log (`instruction, tools, proposal, verdict, final_call`). This is the fine-tuning dataset (§7) and the audit trail.

### A.5. Plan language and validator changes

**Note (research update):** The validator at `plan/validator.py` (F001) already checks tool existence, arg schema shape, guards, paths, for_each sources. Delegate-specific rules extend this.

New node shape (compiles to a `NodeDefinition` with `type: "delegate"`):

```json
{
  "id": "fetch_page",
  "type": "delegate",
  "for_each": "$.load_products.output.rows[*]",
  "instruction": "Fetch the product page for {item.name} at {item.retailer}",
  "facts": {"locale": "en-US"},
  "tools": ["web_fetch", "scrape_with_flow"],
  "min_confidence": 0.8,
  "on_reject": "escalate",
  "store_as": "page_{index}",
  "max_concurrency": 16
}
```

Validator additions (all static, 0 tokens):

1. Every name in `tools` exists in the `ToolManager`.
2. `1 <= len(tools) <= delegate.max_tools`. Above five, Needle switches to retrieval; split the step instead.
3. **Side-effect policy.** Tools carry a `delegate_safe: bool` flag, default `False`. Read-only or idempotent tools opt in. A plan listing a non-safe tool in a delegate node is rejected unless the node sets `allow_side_effects: true` *and* the agent's config permits it.
4. `instruction` and `facts` templates resolve (reuse `TemplateResolutionError`).
5. The tool-only contract is unchanged: a delegate is not an agent, recursion remains impossible.

Registration mirrors `ensure_tool_node_registered`: `register_node("delegate")(DelegateToolNode)`, with `make_delegate_node_factory` closing over the live `ToolManager`, `WorkingMemory` and delegate pool.

### A.6. The confidence problem

The design would like `min_confidence` to be the main gate. Needle's docs say fine-tuned weights return `confidence: None`, and §7 argues a fine-tune is likely needed. Options, to be decided by the spike:

- **A. Base weights + confidence gate.** Works only if base accuracy is acceptable.
- **B. Fine-tuned weights, no confidence.** Gate is schema validation + `accept_when` guards + (optionally) agreement between two backends on the tool name.
- **C. llama.cpp backend with token logprobs** as a crude confidence.

The node treats `confidence is None` as "gate not available", never as zero and never as one.

### Verified code anchors (paths only — open them yourself)
packages/ai-parrot/src/parrot/bots/flows/plan/compile.py
packages/ai-parrot/src/parrot/bots/flows/plan/guards.py
packages/ai-parrot/src/parrot/bots/flows/plan/models.py
packages/ai-parrot/src/parrot/bots/flows/plan/node.py
packages/ai-parrot/src/parrot/bots/flows/plan/validator.py
packages/ai-parrot/src/parrot/tools/abstract.py
packages/ai-parrot/src/parrot/tools/manager.py
packages/ai-parrot/src/parrot/tools/working_memory/tool.py
packages/ai-parrot/src/parrot/tools/execution_plan/checkpoint.py
packages/ai-parrot/src/parrot/tools/execution_plan/toolkit.py
packages/ai-parrot/src/parrot/tools/execution_plan/planner.py
packages/ai-parrot/src/parrot/tools/execution_plan/repair.py

### Questions still open in the exploration document
- [ ] **Should the spike be the first task of FEAT-590 or a separate pre-feature experiment?** — *Owner*: tbd
- [ ] **Is the Epson 5-15% residue estimate based on observed data?** — *Owner*: tbd
- [ ] **Should the delegate support standalone use outside execution plans (e.g., in AgentCrew or ad-hoc triage)?** — *Owner*: tbd

## Question
Given this accepted design intent and these verified code anchors, how would you build it? What is missing, risky, or better done another way?
