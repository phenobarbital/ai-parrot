---
kind: file
jira_key: null
fetched_at: 2026-09-21T22:00:00+00:00
summary_oneline: "Tool-Call Delegate: local tool-calling-only model as a Flow step between PlanToolNode and AgentNode"
---

# Tool-Call Delegate — a local, tool-calling-only model as a Flow step

> Context: follow-up to `claude/handle-only-execution-design.md` (plan-then-execute). That design removed the LLM from the execution loop for steps whose arguments are known at plan time. This doc covers the remaining gap: steps whose arguments depend on runtime data in a fuzzy way, which today would force an `AgentNode` (full LLM) per item.
>
> Status: **design, pre-spike.** Nothing here is implemented. §9 lists what is unverified; §10 is the spike gate that must pass before this goes to `/sdd-spec`.

## Key Design Points

- Add `DelegateToolNode`: a third kind of executable step between `PlanToolNode` (0-token templates) and `AgentNode` (full LLM)
- Delegate is NOT an `AbstractClient` — exposes only `propose_call()` and `extract()` verbs
- Primary backend: Needle 3 (121M params, 8–29 MB, Apache-2.0)
- Fallback backend: GGUF model via llama.cpp with JSON Schema grammar
- Interface follows `parrot.interfaces.*` contract pattern (Pydantic-only, lazy loading)
- Instance pool concurrency model for Needle (stateful, non-reentrant assumed)
- Plan language extends with `type: "delegate"` node
- Confidence gating with three options (base weights, fine-tuned, logprobs)
- Fine-tuning path via distillation from Claude traces
- First application: Epson price freshness triage (Best Buy / Target)

## Dependencies

- `register_node("tool")(PlanToolNode)` (pending per plan-then-execute doc)
- `run_execution_plan` tool with `build_manifest()` (pending)
- `ResultPolicy`, bounded replan (pending)

## Explicitly Does Not Exist

`ToolCallDelegate`, `NeedleDelegate`, `LlamaCppDelegate`, `DelegateToolNode`, `make_delegate_node_factory`, delegate node type, `delegate_safe` flag, `delegate_description`, proposal trace log — all new.
