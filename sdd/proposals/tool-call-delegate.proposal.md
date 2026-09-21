# Tool-Call Delegate — a local, tool-calling-only model as a Flow step

> Context: follow-up to `claude/handle-only-execution-design.md` (plan-then-execute). That design removed the LLM from the execution loop for steps whose arguments are known at plan time. This doc covers the remaining gap: steps whose arguments depend on runtime data in a fuzzy way, which today would force an `AgentNode` (full LLM) per item.
>
> Status: **design, pre-spike.** Nothing here is implemented. §9 lists what is unverified; §10 is the spike gate that must pass before this goes to `/sdd-spec`.

## 0. Conclusion first

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

## 1. Why Needle 3 is the first backend (and why it must not be the only one)

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

## 2. Interface

Follows the `parrot.interfaces.*` contract pattern: Pydantic-only, always importable, implementations loaded lazily behind optional extras (`ai-parrot[needle]`, `ai-parrot[llamacpp]`).

```python
# parrot/interfaces/delegate.py
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

Tool descriptions become part of the model's behaviour (Needle cannot be steered by a system prompt). A per-tool `delegate_description` override may be needed so that descriptions tuned for Claude are not degraded to suit a 121M model.

## 3. `NeedleDelegate`: concurrency model

The Needle Python API documents neither async support nor thread safety, and the agent object is stateful (`reset()` exists). Assume a blocking, non-reentrant C engine until measured.

- **Instance pool with checkout.** N instances, `asyncio.Queue` as the free list; acquire -> `reset()` -> `complete()` -> release. Pool size is the delegate's own concurrency ceiling, independent of the node's `max_concurrency`.
- **One instance per tool subset.** `Needle(tools=...)` binds the toolset at construction. Pool key = `frozenset(tool_names)`. Plans use few distinct subsets, so this stays small. About 28 MB per instance (from the documented example response); 16 instances is under 0.5 GB.
- **Executor.** Start with `ProcessPoolExecutor` (safe regardless of GIL behaviour). Move to `asyncio.to_thread` only if the spike shows the engine releases the GIL. This is a legitimate `to_thread`/process use: the work is CPU-bound, unlike the I/O fan-out discussed in §3 of the plan-then-execute doc.
- **Facts.** `facts` maps onto Needle's fixed `system` keys where they match (`date`, `locale`); anything else is folded into the instruction text.

`LlamaCppDelegate` is simpler: one `llama-server --parallel N` process with continuous batching, called over HTTP with `json_schema` set to a `oneOf` of `{name: const, arguments: <tool schema>}` per tool. Natively async; no pool needed.

## 4. `DelegateToolNode`

```
resolve templates in `instruction` / `facts`      (same resolver as PlanToolNode)
  -> enforce max_input_chars                        (reject, never truncate silently)
  -> delegate.propose_call(instruction, tools, facts)
  -> ACCEPT GATE:
       name in node.tools
       arguments validate against that tool's args_schema
       confidence >= node.min_confidence            (skipped when confidence is None, see §6)
       optional node.`accept_when` guard (CEL, same engine as `when`)
  -> accepted: ToolManager.execute_tool() -> wm.store_result(key) -> ArtifactRef
  -> rejected: apply node.on_reject
```

`on_reject` values:

- `fail`: record a per-item error in the manifest (default).
- `retry_backend`: try the next delegate in the configured chain (Needle -> llama.cpp).
- `escalate`: collect the item into the bounded-replan input (§5 of the plan-then-execute doc). The planner sees the instruction, the rejected proposal and the reason, never the payload.

Every proposal, accepted or not, is appended to a trace log (`instruction, tools, proposal, verdict, final_call`). This is the fine-tuning dataset (§7) and the audit trail.

## 5. Plan language and validator changes

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
2. `1 <= len(tools) <= delegate.max_tools`. Above five, Needle switches to retrieval and the node stops being predictable; split the step instead.
3. **Side-effect policy.** Tools carry a `delegate_safe: bool` flag, default `False`. Read-only or idempotent tools (web fetch, scrape, read queries) opt in. A plan that lists a non-safe tool in a delegate node is rejected unless the node sets `allow_side_effects: true` *and* the agent's config permits it. A wrong fetch is retried; a wrong `UPDATE` is not.
4. `instruction` and `facts` templates resolve (reuse `TemplateResolutionError`).
5. `instruction` is written in English (convention, not enforced; Needle's language support is undocumented).
6. The tool-only contract is unchanged: a delegate is not an agent, so rule (c) of the plan-then-execute doc (reject `type: "agent"`) still holds and recursion remains impossible.

Registration mirrors the pending `register_node("tool")(PlanToolNode)`: `register_node("delegate")(DelegateToolNode)`, with a `make_delegate_node_factory` that closes over the live `ToolManager`, `WorkingMemory` and delegate pool.

## 6. The confidence problem

The design would like `min_confidence` to be the main gate. Needle's docs say fine-tuned weights return `confidence: None`, and §7 argues a fine-tune is likely needed. Both cannot be relied on at once. Options, to be decided by the spike:

- **A. Base weights + confidence gate.** Works only if base accuracy on ai-parrot toolkits is acceptable. Cheapest; keeps calibrated abstention.
- **B. Fine-tuned weights, no confidence.** Gate is schema validation + `accept_when` guards + (optionally) agreement between two backends on the tool name. Higher accuracy, no abstention signal.
- **C. llama.cpp backend with token logprobs** as a crude confidence. Uncalibrated; would need its own calibration set.

The node treats `confidence is None` as "gate not available", never as zero and never as one. A plan that sets `min_confidence` against a backend that cannot score is flagged by the validator as a warning.

## 7. Fine-tuning path (distillation from Claude)

The training data already exists in principle: every tool call Claude makes through the `ToolManager` is an `(instruction-ish context, tools offered, call emitted)` triple. Steps:

1. Log delegate-shaped traces from real agent runs (tools offered restricted to <= 5, context reduced to a one-line instruction). Where the original context is long, have Claude write the one-line instruction it would have given a delegate; that is a one-off labelling cost.
2. Add the delegate's own rejected proposals with the corrected final call (§4 trace log).
3. `needle finetune data.jsonl --epochs 10 --lora-rank 16`, export `.cact`, load with `weights=`.
4. Hold out 20% by *tool*, not by row, to measure generalization to toolkits the model never saw.

Reference point for what to expect: distil labs report LFM2.5-350M going from 34–63% to 96–98% on three narrow tool-calling tasks after fine-tuning, and FunctionGemma-270M from 10–39% to 91–97%. Narrow, stable tool sets fine-tune very well; open-ended ones do not.

## 8. First application: Epson price freshness (Best Buy / Target)

The happy path needs **no delegate**: product list in WM -> `for_each` `PlanToolNode` over `WebScrapingToolkit` with the saved DSL flow -> pydantic validation (price > 0, currency, delta vs last price) -> WM/DB. The delegate covers the residue:

```json
{"id": "triage", "type": "delegate",
 "for_each": "$.validate.output.rejected[*]",
 "instruction": "Page for {item.sku}: status {item.http_status}, title '{item.title}', selectors found {item.selectors_found}, text '{item.text_head}'",
 "tools": ["retry_with_proxy", "run_alt_flow", "send_to_jev", "mark_unavailable"],
 "on_reject": "escalate", "store_as": "triage_{index}"}
```

The instruction is a digest (status, title, which DSL selectors matched, about 300 characters of visible text), never the HTML. Long text goes to Jev. With a 5–15% residue over hundreds of products this is tens of local decisions per run instead of tens of Claude calls, and the bounded replan shrinks to the items the delegate itself rejects.

## 9. Does NOT exist / unverified

Stated explicitly so that nothing below is assumed during spec or implementation.

**Does not exist in ai-parrot today:** `ToolCallDelegate`, `NeedleDelegate`, `LlamaCppDelegate`, `DelegateToolNode`, `make_delegate_node_factory`, the `delegate` node type, the `delegate_safe` tool flag, `delegate_description`, the proposal trace log.

**Pending per the plan-then-execute doc as of 2026-08-04 (repo state not re-checked):** `register_node("tool")(PlanToolNode)`, the `run_execution_plan` tool with `build_manifest()`, bounded replan, `ResultPolicy`. `DelegateToolNode` depends on the first two.

**Unverified about the plan runner (inferred from the doc, not from code):**

- whether `paths.py` can select from a WorkingMemory key directly, or only from an upstream node's output;
- whether a `for_each` node is a single DAG node (downstream waits for all items, i.e. a stage barrier) or expands to N nodes (per-item pipelining);
- whether checkpoint/resume granularity is per item or per node;
- whether a failing item fails the whole `for_each` node.

**Unverified about Needle 3:** context window and max input length; sync vs async and thread safety; whether the engine releases the GIL; `error_code` values; supported languages; Linux x86_64/aarch64 wheels (platform list is not enumerated on the model card); accuracy on any non-mobile toolset; whether `confidence` is really `None` for every fine-tuned export or only some.

**Not read:** Jev / typesafe.ai documentation (fetch was not authorized in the session that produced this doc). Everything said about Jev comes from its description as "text in, always-structured output out".

## 10. Spike gate (one day, before `/sdd-spec`)

Build the smallest `NeedleDelegate` (no pool, no node) and run it against 50–100 cases taken from real traces, tools restricted to <= 5 per case.

Measure:

1. Exact match on tool name, and on tool name + arguments, against the call Claude actually made.
2. Abstention quality: on cases with no fitting tool, does it return an empty `function_calls`, and is `confidence` separable between right and wrong proposals (AUROC)?
3. Latency p50/p95 per proposal and throughput at N = 1, 4, 16 concurrent, threads vs processes (answers the GIL question).
4. Behaviour as the instruction grows: 100, 250, 500, 1000 characters (answers the window question empirically).
5. Same cases through Granite-4.0-1B + grammar on llama.cpp as the comparison arm.

Decision rule:

- Needle base >= 90% name+args and confidence separable -> option A, proceed with Needle as primary.
- Needle base below that but llama.cpp arm >= 90% -> llama.cpp primary, Needle deferred to after a fine-tune.
- Both below -> fine-tune first (§7) and re-run; if still below, the step stays a `PlanToolNode` + heuristics and this feature is dropped.

## 11. Roadmap

1. Spike (§10) and decision on §6.
2. Close the two pending items of the plan-then-execute roadmap that this depends on (`register_node("tool")`, `run_execution_plan`).
3. `parrot/interfaces/delegate.py` + schema adapter + `delegate_safe` flag on `AbstractTool`.
4. Winning backend with pool/executor as measured; second backend behind the same protocol.
5. `DelegateToolNode`, factory, registration, validator rules (§5), trace log.
6. Apply to the Epson triage step (§8); collect traces.
7. Fine-tune from traces (§7) if the spike pointed there; re-evaluate on the held-out-by-tool split.

## Sources

- Needle API: https://github.com/cactus-compute/needle/blob/main/doc/apis.md
- Needle 3 model card: https://huggingface.co/Cactus-Compute/needle3
- Needle environment best practices: https://cactuscompute.com/blog/needle-environment-best-practices
- Granite 4.0 Nano: https://huggingface.co/ibm-granite/granite-4.0-h-1b
- Qwen3.5-2B GGUF: https://huggingface.co/unsloth/Qwen3.5-2B-GGUF
- LittleLamb-ToolCalling: https://huggingface.co/MultiverseComputingCAI/LittleLamb-ToolCalling
- distil labs, fine-tuning LFM2.5-350M for tool calling: https://www.distillabs.ai/blog/fine-tuning-liquids-lfm25-accurate-tool-calling-at-350m-parameters/
- CPU reliability benchmark for MCP-style tool calling in sub-2B SLMs: https://arxiv.org/html/2609.07370
- Project doc: `claude/handle-only-execution-design.md`
