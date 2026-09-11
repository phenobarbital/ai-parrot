# Question Token Budgets (Bedrock Converse, Nova text, Bedrock Mantle)

**Audience**: Engineers who need a cumulative token ceiling for one user question — every model request, tool round, retry, fallback and same-process child call — with a protected final-answer reserve.

**Related files**:
- `packages/ai-parrot-client-amazon/src/parrot/clients/amazon/budget.py` — Bedrock / Mantle adapters
- `packages/ai-parrot-client-amazon/src/parrot/clients/amazon/budget_qualifications.py` — strict registry (empty)
- `packages/ai-parrot/src/parrot/clients/budget.py` — `QuestionBudget` ledger + public re-exports
- `packages/ai-parrot/src/parrot/clients/budget_scope.py` — `BudgetScope`, `BudgetRegistry`, entry adapters
- `packages/ai-parrot/src/parrot/models/token_budget.py` — records (`TokenBudgetPolicy`, `BudgetReport`, `BudgetSnapshot`, …)
- `examples/clients/smoke/smoke_token_budget_qualification.py` — opt-in qualification probe
- `sdd/specs/token-budget-bedrock.spec.md` — full design (FEAT-550)

---

## What This Is

In multi-turn agentic workflows, tool-use loops, and complex retrieval-augmented generation (RAG) pipelines, a single user question can trigger a cascade of downstream LLM calls. Without strict boundaries, a looping agent or an unexpectedly large tool payload can silently consume millions of tokens, leading to massive cloud bills and latency spikes.

To solve this, the Question Token Budget system provides a process-local, cumulative token ceiling that spans every model request, tool round, retry, fallback, and same-process child call initiated under a single user question. It is NOT a global rate-limiter or a multi-user quota system; rather, it is a precise, single-question guardrail designed to protect applications from runaway loops while guaranteeing a dedicated **final-answer reserve** so the user always receives a clean, structured termination message instead of an abrupt network cut.

---

## Configuration

The token budget is configured via the `TokenBudgetPolicy` model or passed directly to client constructors and invocation methods.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `token_budget` | `int | None` | `None` | The total cumulative token ceiling (input + output) for the question. If `None`, budgeting is disabled. |
| `budget_mode` | `str` | `"estimated"` | Budget enforcement mode: `"estimated"` (local estimation/fallback) or `"strict"` (refuses to run if exact token counting is unavailable). |
| `final_answer_reserve` | `int | float` | `0.15` | Reserve for the final answer. If `float` (e.g., `0.15`), it is a percentage of `token_budget`. If `int` (e.g., `1500`), it is an absolute token count. |
| `budget_scope` | `str | None` | `None` | Optional scope identifier to isolate or group nested calls. |
| `budget_snapshot` | `BudgetSnapshot | None` | `None` | A serialized snapshot to resume a previously suspended budget across process boundaries. |

### Omission vs. None Rule
- If `token_budget` is omitted or explicitly set to `None`, no budget is enforced, and downstream calls proceed without tracking.
- If a child call is initiated within an active budget scope, it automatically inherits the parent's remaining budget unless a new explicit budget is specified, which must be a strict subset of the parent's remaining budget.

### Code Sample

```python
from parrot.clients.amazon import BedrockConverseClient
from parrot.models.token_budget import TokenBudgetPolicy

# Configure a client with a default policy
client = BedrockConverseClient(
    region="us-east-1",
    token_budget=10_000,
    budget_mode="estimated",
    final_answer_reserve=1500,
)

# Or pass a policy dynamically per-request
policy = TokenBudgetPolicy(token_budget=10000, final_answer_reserve=1500)
response = await client.ask(
    "Analyze this dataset...",
    model="anthropic.claude-3-haiku",
    token_budget=policy,
)
```

---

## Worked Example (default 15% reserve)

Consider a question budget configured with:
- Total Budget ($B$) = `10,000` tokens
- Final Answer Reserve ($F$) = `1,500` tokens (15% of 10,000)
- Working Budget ($W = B - F$) = `8,500` tokens

### Step-by-Step Execution:

1. **Round 1 (Tool Call)**:
   - The agent makes an initial call. Input is `2,000` tokens, and the model outputs a tool call of `500` tokens.
   - Cumulative usage ($C$) = `2,500` tokens.
   - Remaining working budget = `8,500 - 2,500 = 6,000` tokens.

2. **Round 2 (Tool Execution & Response)**:
   - The tool executes and returns a large payload. The next model call takes `3,000` input tokens and outputs `700` tokens.
   - Cumulative usage ($C$) = `2,500 + 3,700 = 6,200` tokens.
   - Remaining working budget = `8,500 - 6,200 = 2,300` tokens.

3. **Round 3 (Final Answer Attempt)**:
   - The agent prepares to generate the final answer.
   - The input prompt for this final round is `3,200` tokens.
   - The system checks the admission rule:
     $$\text{Admission } O = \min(M, A - I) \ge m$$
     Where $A$ is the total remaining budget (`10,000 - 6,200 = 3,800`), $I$ is the input size (`3,200`), and $m$ is the minimum output reserve (typically `100` tokens).
     $$\text{Admission } O = \min(M, 3,800 - 3,200) = 600 \text{ tokens}$$
   - Since $600 \ge 100$, the request is admitted, but the model's `max_tokens` parameter is strictly capped at `600` to prevent exceeding the total budget of `10,000`.
   - The resulting `BudgetReport` will show:
     - `total_budget`: `10000`
     - `cumulative_tokens`: `9400` (assuming the model used exactly 600 output tokens)
     - `budget_exhausted`: `True`
     - `finalization_attempted`: `True`
     - `finalized`: `True`

4. **Alternative Round 3 (Overrun Blocked)**:
   - If the input prompt for the final round was `4,000` tokens instead of `3,200`:
     $$A - I = 3,800 - 4,000 = -200 \text{ tokens}$$
     Since $-200 < 100$, the request is rejected before inference. The system raises a `BudgetExhaustedError` and returns a partial result containing the accumulated history.

---

## How Accounting Works

The budget ledger tracks five core variables:
- **$B$**: Total Budget
- **$F$**: Final Answer Reserve
- **$C$**: Cumulative Tokens Used
- **$U$**: Unclamped Overrun (tokens consumed beyond limits during estimated mode)
- **$R$**: Remaining Budget ($B - C$)

### Admission Formula
Before any model request is sent to the provider, the adapter evaluates:
$$O = \min(M, A - I)$$
Where:
- $M$ is the user's requested `max_tokens` (or the model's default limit).
- $A$ is the remaining budget (either the working budget $W - C$ if not finalising, or the total remaining budget $B - C$ if finalising).
- $I$ is the estimated input token count.

If $O < m$ (where $m$ is the minimum output reserve, default `100`), the request is blocked.

### Per-Provider Normalization

| Provider | Input Normalization | Output Normalization |
|---|---|---|
| **Bedrock Converse** | Sum of prompt text, tool results, and Converse cache points. | Native output token usage from response metadata. |
| **Nova Client** | Native body input tokens. | Native body output tokens. |
| **Bedrock Mantle** | Aggregate input tokens from OpenAI-compatible response. | Aggregate output tokens from OpenAI-compatible response. |

### Estimated Overrun
In `"estimated"` mode, if a provider returns usage that exceeds the local estimate, the actual usage is recorded. The ledger allows the remaining budget to go negative (recorded in $U$), but blocks all subsequent requests.

---

## Finalization and Partial Results

When the working budget is exhausted, the system enters the **Finalization** phase. It attempts to make one last call to the model to generate a clean, truncated final answer using the remaining reserve ($F$).

| Condition | Action | Resulting Flags |
|---|---|---|
| Working budget exceeded, remaining budget $\ge I + m$ | Admit final request with capped `max_tokens` | `budget_exhausted=True`, `finalization_attempted=True`, `finalized=True` |
| Working budget exceeded, remaining budget $< I + m$ | Block request before inference | `budget_exhausted=True`, `finalization_attempted=False`, `finalized=False` |

When a budget is exhausted, the client returns an `InvokeResult` or `AIMessage` with:
- `stop_reason`: `"budget_exhausted"`
- `metadata["token_budget"]`: The final `BudgetReport`
- Partial output generated up to the exhaustion point.

---

## Streaming, Cancellation, Retries

### Streaming
During streaming (`ask_stream`), the adapter tracks tokens chunk-by-chunk. If the cumulative count exceeds the allowed limit, the stream is immediately aborted, a final sentinel chunk is emitted, and the connection is closed.

### Cancellation
If a stream or request is cancelled by the client, the ledger records the tokens consumed up to the cancellation point. Because cancellation is asynchronous, a sentinel chunk is not guaranteed.

### Retries and SDK Ownership
To prevent hidden retries from consuming tokens outside the ledger's awareness:
- SDK-level retries should be disabled or restricted (e.g., `max_retries=0` or BotoConfig `total_max_attempts=1`).
- The application-level loop must manage retries, ensuring each attempt reserves its input tokens against the active `QuestionBudget` before dispatching.

---

## Scopes, Children, Suspension and Snapshots

### ContextVar Scope
The active budget is bound to the current execution context using a `ContextVar`. Nested tasks or child threads automatically inherit the active budget.

### Registry and Retention
The `BudgetRegistry` manages active budgets in memory:
- **Active Retention**: 1,024 seconds.
- **Max Idle Retention**: 3,600 seconds.
- Budgets must be explicitly released using `release()` to free resources.

### Snapshots and Trust Boundary
Budgets can be serialized into a `BudgetSnapshot` to resume tracking across process boundaries (e.g., in distributed agent networks).
> ⚠️ **Security Warning**: Snapshots are process-local trust boundaries. After a process restart, the application is the only authority. **Do not accept snapshots from untrusted public HTTP or tool inputs**, as a malicious actor could forge a snapshot to bypass token limits.

---

## Coverage

| Client | ask | ask_stream | resume | invoke | Notes |
|---|---|---|---|---|---|
| `BedrockConverseClient` | ✅ | ✅ | ✅ | ✅ | Converse + native `invoke_model` text guarded |
| `NovaClient` (text) | ✅ | ✅ | ✅ | ✅ | Inherited; audio/image/video out of scope |
| `BedrockMantleClient` | ✅ | ✅ | ✅ | ✅ | Estimated mode only |
| Every other client | ❌ | ❌ | ❌ | ❌ | Raises `BudgetUnsupported` before inference |

---

## Strict Mode Status

The strict-qualification registry ships **empty** by default.

On the standard environment with `botocore 1.35.36`, the SDK lacks native `CountTokens` support. Consequently, strict-mode requests will fail with `BudgetUnsupported` before inference.

### Qualification Procedure
To qualify a model/SDK combination for strict mode:
1. Run the opt-in qualification probe script:
   ```bash
   python examples/clients/smoke/smoke_token_budget_qualification.py \
       --provider bedrock --model anthropic.claude-3-haiku --region us-east-1 --budget 4000 --i-accept-paid-inference
   ```
2. Review the sanitized findings JSON written to `artifacts/logs/`.
3. If the counted inputs match the actual inputs across all variants, copy the printed `QualificationKey` and add it manually to the strict registry in `packages/ai-parrot-client-amazon/src/parrot/clients/amazon/budget_qualifications.py`.
4. Run the test suite to verify.

---

## Error Reference

- `budget_exhausted`: The token budget has been fully consumed.
- `budget_mode_invalid`: The requested budget mode is not supported.
- `budget_scope_conflict`: A child scope attempted to claim more tokens than the parent remaining budget.
- `budget_state_missing`: No active budget found in the current context.
- `budget_unsupported`: The client or model does not support token budgeting.
- `resume_conflict`: Attempted to resume a budget that is already active or has expired.
- `snapshot_invalid`: The provided budget snapshot is corrupt or forged.
- `finalization_failed`: An error occurred during the final answer reserve generation.
