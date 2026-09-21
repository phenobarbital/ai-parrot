---
id: FEAT-590
title: "Tool-Call Delegate: local tool-calling-only model as a Flow step"
slug: tool-call-delegate
type: feature
mode: enrichment
status: review
source:
  kind: file
  jira_key: null
  jira_url: null
  fetched_at: 2026-09-21
  summary_oneline: "Local tool-calling-only model as a third execution step between PlanToolNode and AgentNode"
overall_confidence: medium
base_branch: dev
projects: [ai-parrot]
tags: [execution-plan, delegate, needle, llama-cpp, tool-calling, local-model]
research_state: sdd/state/FEAT-590/
created: 2026-09-21
updated: 2026-09-21
---

# FEAT-590 — Tool-Call Delegate

> **Mode**: enrichment
> **Confidence**: medium
> **Source**: `file: sdd/proposals/tool-call-delegate.proposal.md` (original design doc)
> **Audit**: [`sdd/state/FEAT-590/`](../state/FEAT-590/)

---

## 0. Origin

The original design document, authored as a follow-up to the plan-then-execute
architecture (FEAT-419). The full source is at `sdd/state/FEAT-590/source.md`.

> Add a third kind of executable step to the plan language, between PlanToolNode
> (templates, 0 tokens) and AgentNode (full LLM). A tiny local model (Needle 3,
> 121M parameters) proposes tool calls from a short instruction plus runtime
> facts, validated by schema and dispatched through ToolManager — identical to
> PlanToolNode from the dispatch point onward.

**Initial signals**:
- Verbs: "add", "propose", "delegate" → enrichment (new capability)
- Named entities: Needle 3, llama.cpp, DelegateToolNode, PlanToolNode, AgentNode
- Components: `bots/flows/plan/`, `tools/manager.py`, `tools/abstract.py`
- Acceptance criteria provided: yes (§10, spike gate with decision rules)

---

## 1. Synthesis Summary

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

---

## 2. Codebase Findings

> All entries grounded in research findings at `sdd/state/FEAT-590/findings/`.

### 2.1 Localization

| # | Path | Symbol | Lines | Role | Evidence |
|---|------|--------|-------|------|----------|
| 1 | `packages/ai-parrot/src/parrot/bots/flows/plan/node.py` | `PlanToolNode` | 1-1121 | Reference implementation for DelegateToolNode | F001, F002 |
| 2 | `packages/ai-parrot/src/parrot/bots/flows/plan/models.py` | `PlanNode` | 173-254 | Data model the delegate node config extends | F003 |
| 3 | `packages/ai-parrot/src/parrot/bots/flows/plan/models.py` | `ForEach` | 111-170 | Fan-out model reused by delegate nodes | F003 |
| 4 | `packages/ai-parrot/src/parrot/bots/flows/plan/compile.py` | `ensure_tool_node_registered` | 133-154 | Registration pattern to follow | F002 |
| 5 | `packages/ai-parrot/src/parrot/bots/flows/plan/validator.py` | `validate_plan` | full | Extension point for delegate-specific rules | F001 |
| 6 | `packages/ai-parrot/src/parrot/bots/flows/plan/guards.py` | `PlanGuard` | full | Reusable CEL evaluator for accept_when | F007 |
| 7 | `packages/ai-parrot/src/parrot/tools/manager.py` | `ToolManager.execute_tool` | 1609-1668 | Dispatch target for accepted proposals | F005 |
| 8 | `packages/ai-parrot/src/parrot/tools/abstract.py` | `AbstractTool` | 200, 375 | Needs delegate_safe flag + delegate_description | F006 |
| 9 | `packages/ai-parrot/src/parrot/tools/working_memory/tool.py` | `WorkingMemoryToolkit.store_result` | — | Storage target, same path as PlanToolNode | F008 |

### 2.2 Constraints Discovered

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

### 2.3 Recent History (Relevant)

| Commit | When | Message | Touched files |
|--------|------|---------|---------------|
| `8ae42e613` | 2026-09 | feat(workingmemory-toolkit): TASK-2991 — preserve plan and tee artifact provenance | `plan/node.py` |
| `d7b4819db` | 2026-08 | feat(execution-plan-tool): TASK-2179 — Land the plan/ module | `plan/` (all files) |

No changes to `plan/models.py`, `plan/validator.py`, or `plan/guards.py` since
the initial landing — the extension surface is stable.

---

## 3. Probable Scope

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

---

## 4. Confidence Map

| ID | Claim | Evidence | Confidence | Reasoning |
|----|-------|----------|------------|-----------|
| C1 | Plan module (PlanToolNode, ExecutionPlan, ArtifactRef, validate_plan) is landed and working | F001 | high | Direct wiki + file reads confirmed exports, factory, tests |
| C2 | NODE_REGISTRY supports custom node types via register_node | F002 | high | Source confirmed; dev-loop nodes already use same pattern |
| C3 | DelegateToolNode can follow PlanToolNode pattern (Node subclass, factory closure, same dispatch) | F001, F002, F005 | high | Architecture extensible by design |
| C4 | parrot/interfaces/delegate.py is the WRONG location | F004 | high | Established convention confirmed by FEAT-449 F012 |
| C5 | CEL guards reusable for accept_when | F007 | high | Generic evaluator; only variable context changes |
| C6 | delegate_safe flag doesn't conflict with existing AbstractTool API | F006 | high | No existing flags; default False is safe |
| C7 | FEAT-585 does not conflict with delegate additions to plan/ | F009 | high | Spec explicitly lists plan/ changes as non-goals |
| C8 | Needle 3 base model will achieve ≥90% accuracy on ai-parrot toolkits | — | low | Out-of-distribution; spike gates this |
| C9 | ProcessPoolExecutor will achieve acceptable latency at p95 | — | low | Neither thread safety nor GIL behavior documented |
| C10 | on_reject: escalate integrates with plan runner error handling | F001, F003 | medium | ForEach.on_item_error supports fail/collect/skip; escalate is new but infrastructure exists |

Distribution: **7** high, **1** medium, **2** low.

> The two `low` claims (C8, C9) are about the backend implementation, not the
> architecture. The spec's modular backend design means they resolve
> independently via the spike, without affecting the architectural surface.

---

## 5. Open Questions

### Resolved (during proposal phase)

- [x] **Is PlanToolNode / register_node("tool") already implemented?** — *Resolved*: Yes, landed in FEAT-419, TASK-2179 (commit `d7b4819db`). The proposal's §9 "pending" status is outdated.
  *Resolves claims*: C1, C3

- [x] **Does FEAT-585 conflict with plan/ file changes?** — *Resolved*: No. FEAT-585 spec explicitly declares plan/ model/validator/guard/compiler changes as non-goals.
  *Resolves claims*: C7

- [x] **Where should the ToolCallDelegate protocol live?** — *Resolved*: NOT in `parrot/interfaces/` (mixins package). Co-locate in `parrot/bots/flows/plan/delegate.py` or a `plan/delegate/` subpackage.
  *Resolves claims*: C4

### Unresolved (defer to spec / implementation)

- [ ] **Should the spike be the first task of FEAT-590 or a separate pre-feature experiment?** — *Owner*: tbd
  *Blocks claims*: C8, C9
  *Plausible answers*: a) first task — spike results inform later task scope · b) separate branch — results determine whether to proceed to /sdd-spec

- [ ] **Is the Epson 5-15% residue estimate based on observed data?** — *Owner*: tbd
  *Blocks claims*: —
  *Plausible answers*: a) observed production rates · b) estimated · c) needs measurement

- [ ] **Should the delegate support standalone use outside execution plans (e.g., in AgentCrew or ad-hoc triage)?** — *Owner*: tbd
  *Blocks claims*: —
  *Plausible answers*: a) plan-only initially, standalone later · b) protocol designed for both from day one

---

## 6. Recommended Next Step

**`/sdd-spec FEAT-590`** — *Rationale*: Localization is high-confidence (C1–C7)
and the design space is thoroughly explored in the original proposal. The spike
(§10) gates *implementation*, not the spec — the spec should encode the spike
as the first acceptance criterion with explicit decision rules. Two low-confidence
claims (C8, C9) concern the backend, not the architecture, and the modular
backend design means they resolve independently.

### Alternatives

- **`/sdd-brainstorm FEAT-590`** — if you want to explore alternative local
  models beyond Needle/llama.cpp (e.g., FunctionGemma, Granite Nano).
- **Manual review** — if the spike should run *before* specifying (run §10
  first, feed results into the spec).

---

## 7. Research Audit

| Artifact | Path |
|----------|------|
| State checkpoints | `sdd/state/FEAT-590/state.json` |
| Source (raw) | `sdd/state/FEAT-590/source.md` |
| Research plan | `sdd/state/FEAT-590/research_plan.json` |
| Findings (digests) | `sdd/state/FEAT-590/findings/F001-*.md` … `F011-*.md` |
| Synthesis (JSON) | `sdd/state/FEAT-590/synthesis.json` |

**Budget consumed**:
- Files read: 6 / 40
- Grep calls: 0 / 25
- Git calls: 1 / 10
- Wiki queries: 16 (free, uncapped)
- Wiki page reads: 10 (free, uncapped)
- Truncated: **no**

**Mode determination**: `auto` → resolved to `enrichment` (original source is a
detailed feature design, not a bug investigation).

---

## 8. Provenance

| Field | Value |
|-------|-------|
| Generated by | `/sdd-proposal v1.0` |
| Research approach | wiki-first (16 queries, 10 page reads), targeted file reads |
| Schema versions | state=1.0, synthesis=1.0, research_plan=1.0 |
| Operator | Claude Opus 4.6 |

---

## Appendix: Original Design Document

The full original proposal (11 sections, pre-spike design) is preserved below
for reference. The enriched sections above supersede §9 (Does NOT exist /
unverified) with codebase-grounded findings.

---

### A.0. Conclusion first

Add a third kind of executable step to the plan language, between the two that exist:

| Node | Who decides the arguments | Marginal cost | Failure mode |
|---|---|---|---|
| `PlanToolNode` | The plan (templates such as `{item.url}`) | 0 tokens | none at runtime; caught by the validator |
| **`DelegateToolNode`** (new) | A tiny local model, from a short instruction plus runtime facts | local CPU, milliseconds | wrong tool or wrong args: caught by schema validation, then escalated |
| `AgentNode` | A full LLM | tokens, seconds | everything an LLM loop can do wrong |

The delegate is **not** an `AbstractClient`. It cannot chat, summarize or produce free text. It exposes exactly two verbs:

- `propose_call(instruction, tools, facts) -> ToolCallProposal`
- `extract(text, schema) -> dict | None` (short text only)

Everything downstream of the proposal is identical to `PlanToolNode`: validate against the tool's `args_schema`, dispatch through `ToolManager.execute_tool()`, write to `WorkingMemory` under the key the plan assigned, publish an `ArtifactRef`. The delegate proposes and code disposes.

Division of labour once this exists:

```
Claude (planner)   one call, writes the ExecutionPlan
PlanToolNode       steps with args known at plan time            0 tokens
DelegateToolNode   steps that need a small decision at runtime   local CPU
Jev                long text -> structured output                cheap, deterministic
Claude (analyst)   reads the manifest, never the payloads
```

**When NOT to use it.** If the arguments can be written as templates at plan time, `PlanToolNode` is cheaper and cannot fail. The delegate earns its place only where the alternative is an `AgentNode`: choosing among k tools from an upstream result, deriving args from a short text ("BB" -> `bestbuy`, "next Friday" -> ISO date), per-item triage and recovery.

### A.1. Why Needle 3 is the first backend (and why it must not be the only one)

Facts from the Needle docs (`doc/apis.md`, HF model card), verified 2026-09-20:

- 121M parameters, 8–29 MB single file, 2-bit, Apache-2.0. `pip install cactus-needle`.
- Constructor: `needle.Needle(tools=None, system=None, weights=None, tool_index_path=None, buffer_size=65536)`. `tools` takes "decorated functions, Pydantic models, raw JSON schema dicts, or a JSON string". **Decorators are optional**, so ToolManager schemas can be passed directly.
- `agent.complete(text)`: one turn, returns the proposed call **without executing it**. `agent.run()` executes Python functions itself and is not used here.
- Response shape: `{type, success, error, error_code, function_calls: [{name, arguments}], reasoning, confidence, prefill_tps, decode_tps, peak_ram_mb}`.
- Output is grammar-constrained at byte level to the declared schema (`enum`, `pattern`, `minimum`/`maximum`, `required`).
- `confidence` is "the minimum of two signals: a calibrated post-hoc head … and the decoding probability". **Fine-tuned models report `confidence` as `None`.**
- "Five or fewer declared tools render directly. Above that, retrieval engages" (embedding retrieval, top-5).
- `system` accepts fixed keys only (`date`, `locale`, `device`, `battery`, `network`, `location`, `user`, `assistant`), described as "facts, never instructions".
- `needle.extract(text, schema)` returns a Pydantic instance, a dict, or `None`.
- Fine-tuning: LoRA on the frozen base, `needle finetune data.jsonl`, merged into a single `.cact` loaded via `weights=`.

Why a second backend is mandatory: the base model is trained on mobile-action datasets (DroidCall, Mobile Actions). Scraping, HTTP and database toolkits are out of distribution, the context window of Needle 3 is undocumented (Needle 2 documented a 256-token sliding window), and language support is undocumented. If the spike fails, the Flow and plan schema must not change; only the backend does.

Fallback backend: a GGUF model behind llama.cpp with the JSON Schema as grammar. Candidates, all Apache-2.0: Granite-4.0-1B (BFCL v3 54.8, 128K context, multilingual), Qwen3.5-2B (BFCL v4 43.6, about 1.3 GB at Q4), LittleLamb-ToolCalling 290M (BFCL v4 50.5 self-reported). With grammar-constrained decoding the model's native tool-call format is irrelevant, so these are interchangeable.

### A.2. Interface

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

### A.7. Fine-tuning path (distillation from Claude)

Steps:
1. Log delegate-shaped traces from real agent runs.
2. Add rejected proposals with corrected final calls.
3. `needle finetune data.jsonl --epochs 10 --lora-rank 16`.
4. Hold out 20% by *tool*, not by row.

Reference: distil labs report LFM2.5-350M going from 34–63% to 96–98% on narrow tool-calling tasks after fine-tuning.

### A.8. First application: Epson price freshness (Best Buy / Target)

Happy path needs **no delegate**: `PlanToolNode` over `WebScrapingToolkit`. The delegate covers the residue:

```json
{"id": "triage", "type": "delegate",
 "for_each": "$.validate.output.rejected[*]",
 "instruction": "Page for {item.sku}: status {item.http_status}, title '{item.title}', selectors found {item.selectors_found}, text '{item.text_head}'",
 "tools": ["retry_with_proxy", "run_alt_flow", "send_to_jev", "mark_unavailable"],
 "on_reject": "escalate", "store_as": "triage_{index}"}
```

### A.9. Does NOT exist / unverified (UPDATED)

**Updated from research (F001, F010):**

- ~~`register_node("tool")(PlanToolNode)`~~ → **LANDED** (TASK-2179, commit `d7b4819db`)
- ~~`run_execution_plan` tool with `build_manifest()`~~ → **LANDED** as `ExecutionPlanToolkit._run_plan` (TASK-2180)
- ~~`claude/handle-only-execution-design.md`~~ → **actual path: `sdd/proposals/handle-only-execution-design.input.md`**. Canonical specs: `sdd/specs/execution-plan-tool.spec.md`, `sdd/specs/plan-then-execute-hardening.spec.md`
- `ResultPolicy` → FEAT-585 TASK-3597 (`PlanPlanner.replan / repair_delta`), **still active**
- Bounded replan → FEAT-585 TASK-3596/3597, **still active**

**Still does not exist:** `ToolCallDelegate`, `NeedleDelegate`, `LlamaCppDelegate`, `DelegateToolNode`, `make_delegate_node_factory`, delegate node type, `delegate_safe` flag, `delegate_description`, proposal trace log.

**Still unverified about Needle 3:** context window, thread safety, GIL behavior, `error_code` values, supported languages, platform wheels, accuracy on non-mobile toolsets, confidence behavior under fine-tuning.

### A.10. Spike gate (one day, before `/sdd-spec`)

Build the smallest `NeedleDelegate` (no pool, no node) and run it against 50–100 cases.

Measure: exact match, abstention quality, latency, instruction-length behavior, llama.cpp comparison.

Decision rule:
- Needle base ≥ 90% → option A.
- Below that but llama.cpp ≥ 90% → llama.cpp primary.
- Both below → fine-tune first; if still below, feature is dropped.

### A.11. Roadmap

1. Spike (§10) and decision on §6.
2. ~~Close pending plan-then-execute items~~ → **DONE** (F001).
3. `parrot/bots/flows/plan/delegate.py` (corrected location) + schema adapter + `delegate_safe` flag.
4. Winning backend with pool/executor as measured; second backend behind same protocol.
5. `DelegateToolNode`, factory, registration, validator rules, trace log.
6. Apply to Epson triage step; collect traces.
7. Fine-tune from traces if spike pointed there.

### Sources

- Needle API: https://github.com/cactus-compute/needle/blob/main/doc/apis.md
- Needle 3 model card: https://huggingface.co/Cactus-Compute/needle3
- Needle environment best practices: https://cactuscompute.com/blog/needle-environment-best-practices
- Granite 4.0 Nano: https://huggingface.co/ibm-granite/granite-4.0-h-1b
- Qwen3.5-2B GGUF: https://huggingface.co/unsloth/Qwen3.5-2B-GGUF
- LittleLamb-ToolCalling: https://huggingface.co/MultiverseComputingCAI/LittleLamb-ToolCalling
- distil labs, fine-tuning LFM2.5-350M: https://www.distillabs.ai/blog/fine-tuning-liquids-lfm25-accurate-tool-calling-at-350m-parameters/
- CPU reliability benchmark for sub-2B SLMs: https://arxiv.org/html/2609.07370
- FEAT-419 spec: `sdd/specs/execution-plan-tool.spec.md`
- FEAT-585 spec: `sdd/specs/plan-then-execute-hardening.spec.md`
