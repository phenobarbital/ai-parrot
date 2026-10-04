# Tool-Call Delegate (FEAT-590)

## What it is (and is not)

The **Tool-Call Delegate** is a specialized, lightweight, on-device tool-calling component designed to make a single, grammar-constrained tool proposal from a short instruction and a list of candidate tools.

*   **What it is**: A fast, local, single-purpose model (such as a fine-tuned 1B–3B parameter model) that maps a natural language instruction and a set of tool schemas directly to a structured tool call proposal. It is natively integrated into the execution plan subsystem to allow dynamic, runtime tool selection within a declarative DAG.
*   **What it is not**: It is **not** an `AbstractClient`. It does not support general-purpose chat, multi-turn conversation, or free-text generation. It does not execute tools itself; it merely proposes a call (specifying the tool name and arguments) which the execution plan engine validates and dispatches.

---

## When to use it — PlanToolNode vs DelegateToolNode vs AgentNode

| Feature / Node Type | `PlanToolNode` (type: `"tool"`) | `DelegateToolNode` (type: `"delegate"`) | `AgentNode` (type: `"agent"`) |
| :--- | :--- | :--- | :--- |
| **Decision Maker** | None (Static Plan) | Local Delegate Model | Large Thinking LLM |
| **Token Cost** | Zero (Deterministic) | Extremely Low (Local) | High (Cloud/API) |
| **Latency** | Minimal (I/O only) | Very Low (Local inference) | High (Multi-turn/Thinking) |
| **Flexibility** | Hardcoded tool & arguments | Dynamic tool & arguments | Full conversational autonomy |
| **Best For** | Known, static pipelines | Routing & simple extraction | Complex reasoning & planning |

---

## Node shape

A delegate node is represented in an `ExecutionPlan` as a `DelegatePlanNode` (where `type` is `"delegate"`). It extends the base plan node structure, adding fields for the instruction, facts, candidate tools, and confidence/rejection policies.

Below is a valid example of a delegate node that uses `for_each` to iterate over a list of items retrieved by a prior node, using the `{artifacts.<id>}` reference and a `select` path:

```json
{
  "id": "triage_items",
  "type": "delegate",
  "depends_on": ["fetch_alerts"],
  "store_as": "triage_result_{index}",
  "instruction": "Analyze this alert and select the most appropriate action: {item.summary}",
  "facts": {
    "severity": "{item.severity}",
    "environment": "production"
  },
  "tools": [
    "escalate_to_pagerduty",
    "file_jira_ticket",
    "ignore_alert"
  ],
  "min_confidence": 0.8,
  "on_reject": "escalate",
  "allow_side_effects": false,
  "for_each": {
    "source": "{artifacts.fetch_alerts}",
    "select": "alerts[]",
    "as": "item",
    "max_items": 50,
    "max_concurrency": 4,
    "on_item_error": "collect",
    "skip_existing": true
  }
}
```

---

## The accept gate

Every proposal returned by a delegate backend passes through an **accept gate** before execution. The gate evaluates the proposal against the node's constraints (such as `min_confidence` and `accept_when` CEL guards) and the host's policies.

The gate produces one of the following **verdicts**:

*   `accepted`: The proposal is valid, meets all criteria, and is cleared for execution.
*   `declined`: The delegate model explicitly declined to call any tool (e.g., returned `name=None`).
*   `unknown_tool`: The proposed tool name is not in the node's `tools` list or is not registered in the `ToolManager`.
*   `invalid_args`: The proposed arguments failed Pydantic validation against the tool's schema.
*   `low_confidence`: The proposal's confidence score is below the node's `min_confidence` threshold.
*   `unscored`: The proposal has no confidence score (`None`), but `min_confidence` is set (which requires a score).
*   `guard_false`: The node's `accept_when` CEL guard evaluated to `False`.
*   `input_too_long`: The rendered instruction and facts exceeded the backend's `max_input_chars` limit.
*   `side_effect_denied`: The proposed tool has side effects, but either the node's `allow_side_effects` or the host's `allow_delegate_side_effects` policy is `False`.
*   `backend_error`: The delegate backend failed to respond or raised a `DelegateBackendError`.

---

## on_reject: fail | retry_backend | escalate

When a proposal is rejected (any verdict other than `accepted`), the node's `on_reject` policy determines the outcome:

*   `fail`: The node immediately fails, aborting execution (or marking the item as failed under `for_each`).
*   `retry_backend`: The engine retries the delegate backend (up to the node's retry limit) to obtain a new proposal.
*   `escalate`: The execution is halted, and the node publishes an escalated `ArtifactRef` status. In v1, escalation is terminal and triggers a flow-level pause/failure, allowing a human or a larger planner model to intervene.

---

## Side-effect policy

To prevent local, unaligned models from executing destructive actions without explicit consent, side effects are governed by a strict double-key policy:

1.  **Tool Safety**: Tools must be decorated or registered with `delegate_safe=True` to be eligible for delegate execution by default.
2.  **Node Flag**: A `DelegatePlanNode` must set `allow_side_effects: true` to permit calling non-safe tools.
3.  **Host Flag**: The toolkit/host must be initialized with `allow_delegate_side_effects=True`.

If a delegate proposes a tool with side effects and either the node or host flag is `False`, the proposal is rejected with `side_effect_denied`.

---

## Backends: LlamaCppDelegate · NeedleDelegate (`ai-parrot[needle]`)

The delegate subsystem supports two concrete backends satisfying the `ToolCallDelegate` protocol:

### 1. LlamaCppDelegate
An HTTP client that communicates with a local `llama-server` instance running with grammar-constrained sampling.
*   **Configuration**:
    ```python
    from parrot.bots.flows.plan.delegate import LlamaCppDelegate

    delegate = LlamaCppDelegate(
        base_url="http://localhost:8080",
        max_tools=5,
        max_input_chars=4000,
        use_logprobs=True,
    )
    ```
*   **Pros**: Natively async, lightweight, and does not require heavy local Python dependencies.

### 2. NeedleDelegate
An on-device backend utilizing the Needle 3 engine. It manages an instance pool and offloads inference to an executor.
*   **Installation**: Requires the `needle` extra:
    ```bash
    pip install "ai-parrot[needle]"
    ```
*   **Configuration**:
    ```python
    from parrot.bots.flows.plan.delegate import NeedleDelegate

    delegate = NeedleDelegate(
        weights="/path/to/needle/weights.bin",
        pool_size=4,
        executor="thread",  # "thread" or "process"
        max_input_chars=1000,
    )
    ```

---

## Toolkit configuration

To enable delegate nodes in your execution plans, configure the `ExecutionPlanToolkit` with your delegate instances, trace sinks, and side-effect policies:

```python
from parrot.tools.execution_plan import ExecutionPlanToolkit
from parrot.bots.flows.plan.delegate import LlamaCppDelegate, JsonlTraceSink

# Initialize the delegate backend
local_delegate = LlamaCppDelegate(base_url="http://localhost:8080")

# Configure the toolkit
toolkit = ExecutionPlanToolkit(
    tool_manager=tool_manager,
    working_memory=working_memory,
    delegates=[local_delegate],
    delegate_trace_sink=JsonlTraceSink("logs/delegate_traces.jsonl"),
    allow_delegate_side_effects=False,
)
```

---

## Traces and fine-tuning data

All delegate proposals, accept-gate decisions, and latencies can be captured using an opt-in trace sink. This is highly useful for auditing and collecting fine-tuning datasets to train smaller local models.

*   **`JsonlTraceSink`**: Appends structured `DelegateTrace` records to a local JSON Lines file.
*   **Redaction & Caps**: Traces are automatically redacted to prevent leaking sensitive arguments, and file sizes are capped to prevent disk exhaustion.
*   **Exclusion**: Trace payloads are kept strictly out of execution checkpoints to preserve privacy and minimize checkpoint size.

---

## Limitations (v1)

*   **No Standalone Use**: In v1, delegates cannot be executed as standalone tools; they must run as part of an `ExecutionPlan` DAG.
*   **No Repair of Delegate Nodes**: If a delegate node fails or escalates, the plan repair subsystem (`PlanDelta`) cannot replace or repair the delegate node itself. Only standard `"tool"` nodes are eligible for runtime repair.
