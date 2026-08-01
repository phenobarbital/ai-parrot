# AI-Parrot Benchmarks

Three related benchmarks live in this directory:

| Script | What it measures | Needs credentials |
|--------|------------------|-------------------|
| `perf_eval.py` | Plain `Chatbot.ask()` latency/memory/tokens across LLM providers | yes (per provider) |
| `tool_perf_eval.py` | **Tool-calling** agents: AI-Parrot `Agent` vs **LangChain** head-to-head under identical conditions | yes (per provider) |
| `run_benchmark.py` | Hermetic `parrot.eval` harness demo (FEAT-217) — no LLM at all | no |

## Tool-calling benchmark (`tool_perf_eval.py`)

Continues `perf_eval.py` into the tool-use phase: three deterministic
in-memory tools (`get_weather`, `calculator`, `get_stock_price`) are exposed
to BOTH frameworks from the **same Python functions** (same names, docstrings
and schemas), with the same system prompt, tasks, and models. Each task has
an expected value, so the tables report accuracy alongside latency, memory,
token usage and tool-call counts, plus a final head-to-head delta table.

LangChain is optional and benchmark-only (ai-parrot does NOT depend on it):

```bash
source .venv/bin/activate
uv pip install langchain langchain-anthropic langchain-google-genai langchain-groq

python examples/benchmarks/tool_perf_eval.py                     # both frameworks
python examples/benchmarks/tool_perf_eval.py --frameworks parrot # parrot only
python examples/benchmarks/tool_perf_eval.py --models haiku,groq --iterations 1
python examples/benchmarks/tool_perf_eval.py --with-guardrails   # keep parrot's injection guard ON
```

Fairness notes:

- Parrot's per-call **prompt-injection detection** (production guard with no
  LangChain equivalent) is disabled by default; `--with-guardrails` restores
  parrot's production posture (no longer like-for-like).
- **Token caveat**: LangChain sums usage across every LLM round-trip of the
  tool loop; parrot's `AIMessage.usage` currently reports only the *final*
  round of the client's internal tool loop, so token columns are directly
  comparable only on single-tool-call tasks.
- To add more models, extend the `MODELS` triple list; xai / NVIDIA rows are
  pre-wired in comments (need `langchain-xai` / `langchain-nvidia-ai-endpoints`).

---

# Generic Agent Evaluation Benchmark (FEAT-217)

A runnable, **hermetic** example of the `parrot.eval` harness: it benchmarks a
toolkit-style agent against a dataset of CRUD tasks, scores the final *world
state* (not exact strings), and reports `pass^k` reliability — with **no LLM,
no database, and no credentials required**.

## The five axes

`EvalRunner` is agent-agnostic. You assemble a run from five independent pieces:

| Axis | This example uses | File |
|------|-------------------|------|
| **WHAT** — the dataset | `JSONLDatasetLoader` → `EvalDataset` | `inventory_crud.jsonl` |
| **WHO** — the agent | `make_inventory_agent` (`AgentFactory`) | `agent_factory.py` |
| **HOW (exec)** — the rollout | `SingleTurnRollout` (one `bot.ask()`) | harness |
| **HOW (score)** — the evaluator | `StateBasedEvaluator` (subset diff vs `goal_state`) | harness |
| **ENV** — the sandbox | `InMemoryStateSandbox` + `DictStateBackend` | harness |

Swapping any one axis (e.g. a real `DatabaseAgent`, a `ConversationalRollout`
with an LLM user simulator, a Postgres sink) leaves the other four untouched.

## Run it

```bash
source .venv/bin/activate
python examples/benchmarks/run_benchmark.py            # k=1 (local)
python examples/benchmarks/run_benchmark.py --k 4      # reliability gate (CI-style)
python examples/benchmarks/run_benchmark.py --k 4 --concurrency 8
```

Expected output (k=1):

```
=== Benchmark: inventory_crud  (k=1) ===
  tasks       : 4
  attempts    : 4
  pass^k      : 1.00   <- headline reliability
  pass@1      : 1.00
  per-tag pass^k:
    delete        : 1.00
    insert        : 1.00
    update        : 1.00
  per-attempt results:
    [PASS] inv-insert-keyboard (attempt 1)
    ...
```

- **`pass^k`** = fraction of tasks where **all `k`** attempts passed (reliability).
  Not `pass@k` (any-of-k). With `k=1` it equals `pass@1`.
- A failing task prints its `MetricScore.detail` (mismatched / forbidden fields).

## Dataset format (`inventory_crud.jsonl`)

One JSON object per line, each validating as an `EvalTask`:

```json
{
  "task_id": "inv-update-status",
  "inputs": {"query": "Update product 'P-100' in the inventory: set status to 'active'."},
  "expected": {"goal_state": {"inventory": {"P-100": {"status": "active"}}}},
  "sandbox_spec": {"kind": "in_memory_state", "seed_state": {"inventory": {"P-100": {"name": "Keyboard", "status": "draft"}}}},
  "tags": ["inventory", "update"]
}
```

- `expected.goal_state` — **subset** match: only the listed fields are asserted;
  extra state is ignored (many tool paths can reach the same correct world).
- `expected.forbidden` — entities that must **not** exist (e.g. after a delete):
  `{"forbidden": {"inventory": ["P-200"]}}`.
- `sandbox_spec.seed_state` — initial backend state for the task.

## Benchmarking a *real* agent

`agent_factory.py` ships a deterministic mock so the example runs anywhere. To
benchmark a real `DatabaseAgent` instead, only the **WHO** axis changes — bind a
real toolkit to the sandbox (the binder injects a fake connection, so no I/O):

```python
async def make_inventory_agent(sandbox):
    toolkit = PostgresToolkit(dsn="postgresql://unused")  # never opened
    sandbox.bind(toolkit)                                  # DatabaseToolkitBinder
    return DatabaseAgent(toolkits=[toolkit])
```

See the commented block at the bottom of `agent_factory.py`.

## Seeding

`sandbox_spec.seed_state` from the dataset is applied automatically: `EvalTask`
annotates `sandbox_spec` as `SandboxSpec | None` (resolved via
`EvalTask.model_rebuild()`), so dicts loaded from JSONL/YAML are coerced to a
real `SandboxSpec` and `EvalRunner` seeds the backend before each attempt. No
manual seeding wrapper is needed.
