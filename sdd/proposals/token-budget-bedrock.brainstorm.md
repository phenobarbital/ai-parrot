---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Brainstorm: Cumulative Per-Question Token Budgets for Bedrock and Mantle

**Date**: 2026-09-11
**Author**: Jesus Lara / Codex
**Status**: open questions resolved (2026-09-11) — ready for `/sdd-spec`
**Recommended Option**: B (confirmed by user)
**Research baseline**: `dev`, commit `2edc2eb9d`

---

## Problem Statement

A user question can require several model requests: tool selection, tool-result
processing, retries, fallback, and a final answer. A per-request output limit does
not bound their cumulative consumption. AI-Parrot needs an application-owned token
allowance whose lifetime is the complete question operation.

The confirmed requirement is that all turns used to answer one question consume
the same allowance. The intended users are applications using AI-Parrot's Bedrock
Converse/Nova and Mantle clients, including agents that loop over tools.

The provider premise needs qualification: AWS exposes service quotas, and Mantle
documents token throughput quotas for some models while other models use internal
capacity limits. These are distinct from an application-defined cumulative budget
for one question. This proposal does not depend on subscription limits in coding
tools, provider account spending controls, or a context-window size.
[AWS Mantle quotas](https://docs.aws.amazon.com/bedrock/latest/userguide/quotas-mantle.html).

### Discovery Q&A

Two question rounds were presented during exploration without answers; the
draft recommendations were then reviewed with the user on 2026-09-11 and every
open question was decided. Flow metadata uses the skill's defaults: feature,
based on dev.

| Topic | Decision (2026-09-11, Jesus Lara) |
|---|---|
| Token metric | Input plus output, all categories: repeated history, tool schemas, system prompt, cache read/write, reasoning. |
| Guarantee | `estimated` mode by default (broad Mantle coverage, overrun reported); `strict` mode opt-in, rejects unverified model/endpoint combinations before inference. |
| v1 provider scope | Shared contracts in core; adapters for Bedrock Converse/Nova text and Mantle only. Other clients are explicitly uncovered. |
| Exhaustion outcome | Reserve a **final-answer request** inside the same ceiling. If even the finalization input does not fit, return the partial result with an exhausted status and no model call. |
| Final reserve sizing | `final_answer_reserve` configurable as a fraction of the budget (default proposed: 15%) or as an absolute integer; covers input plus output of the closing request. |
| Durability | In-process only in v1. `resume()` in the same process reattaches to the live ledger; a resume with no live ledger fails typed unless the caller supplies a settled snapshot. No cross-worker coordinator. |
| Vocabulary | One cumulative ceiling, `token_budget`. The final reserve is an internal partition of it, not a second limit. No soft warning threshold in v1. |

Success means that repeated model requests cannot silently restart the question's
allowance, callers can see what consumed it, and every supported request path
either enforces its declared guarantee or explicitly rejects unsupported use.

## Constraints & Requirements

- A question is an execution scope, not a session, individual SDK request, or
  single tool round. A later independent user question gets a fresh allowance.
- Recommended token metric: all input and output tokens processed across requests.
  Repeated history, tool schemas, system prompts, and re-sent tool results count
  each time they are included. Cache reads/writes count as input, with no monetary
  weighting. Reasoning tokens count once through the provider's output semantics.
- Keep `max_tokens` as the existing per-request output control. A new question
  budget must also pay for input and all subsequent requests. A thinking budget
  and `ContextBudget` are separate controls.
- Optional configuration: no question budget means existing behavior. Zero means
  no model requests; reject negative/non-integral configuration. Do not select an
  arbitrary default token allowance for every application. When a budget is set,
  `final_answer_reserve` defaults to a fraction of it (proposed 15%); an absolute
  integer is accepted; zero disables the reserve. The reserve is carved out of
  `token_budget`, never added on top of it.
- v1 scope is a single process: the ledger lives in memory and is shared through
  explicit arguments plus a ContextVar. Cross-worker or cross-restart budget
  sharing is out of scope and must fail explicitly, never silently re-mint.
- First implementation recommendation: text/tool workflows on Converse, inherited
  Nova text methods, and Mantle Chat Completions. Cover `ask`, `ask_stream`,
  `resume`, and text `invoke`, including internal continuations and fallback.
  Other providers, native media generation, and direct third-party SDK calls are
  outside initial enforcement coverage and must not silently appear covered.
- Propagate one operation identifier through supported child calls. Shared mutable
  client-instance counters are unsuitable because clients can serve concurrent
  independent questions.
- No new dependency is proposed. Use existing Pydantic, provider SDKs, and Python
  concurrency primitives. No implementation code is part of this brainstorm.
- Do not advertise a strict total-token ceiling from a tokenizer heuristic. The
  guarantee depends on complete input bounds, output caps, and control over every
  request attempt.

---

## Options Explored

### Option A: Check Accumulated Usage Between Rounds

After each model response, add usage and stop the tool loop if the allowance is
spent. Apply the existing output cap to each request. Share a counter across the
question when invoking multiple clients.

**Pros:** Small initial change; reuses existing Bedrock and OpenAI-compatible
round accounting; useful as a runaway-loop circuit breaker.

**Cons:** A request can cross the remaining allowance before the application sees
usage. Large repeated inputs amplify overshoot. Concurrent requests can all pass
the same check. Final-result accounting alone misses interrupted executions and
resumed operations. Cannot satisfy a strict cumulative ceiling.

**Effort:** Medium for complete streaming/resume coverage; Low for `ask()` only.

**Libraries / Tools:** Existing `pydantic==2.12.5`, `openai==3.3.1`,
`aioboto3>=13.2.0`; no additions. Dependency anchors are in Code Context.

**Existing Code to Reuse:** Bedrock accumulation [C2], OpenAI tool loop [C4], and
`CompletionUsage` [C6]. Lifecycle events may report consumption but cannot safely
act as the admission gate [C9].

### Option B: Shared Question Ledger with Request Reservations

Create one ledger for a question. Before every provider request attempt, calculate
the input requirement, atomically reserve input plus a bounded output allocation,
then admit the request. Reconcile the reservation with actual usage when the
response completes. All tool rounds and supported descendants debit that ledger.

Expose two honest enforcement modes: strict admission only with trustworthy
bounds; estimated admission with declared uncertainty for wider model coverage.
The same ledger and output-limiting machinery serve both modes.

**Pros:** Explicit cumulative semantics; accounts for growing prompts; supports
parallel children without oversubscribing the known allowance; reusable across
providers; directly supports exhaustion reporting and interrupted requests.

**Cons:** More integration work at request/retry/stream boundaries. Exact counting
depends on model and endpoint support. Preserving state across process restarts
needs a durable owner. Shared base-client changes require regression coverage for
the other providers that inherit them.

**Effort:** High for the full scope, including streaming, resume, retry, and child
propagation. A sequential non-streaming slice is Medium but is not the complete
feature described here.

**Libraries / Tools:** Existing Pydantic and SDKs; standard-library `asyncio` and
`contextvars`; existing `tiktoken` only for explicitly estimated counting. AWS
CountTokens where supported. Mantle's Claude-specific count endpoint is a possible
adapter, subject to the request-format limitations described below.

**Existing Code to Reuse:** Request funnels [C1, C3], round loops [C2, C4], bot call
boundary [C8], existing text estimators [C7], and response usage models [C6].

### Option C: Allocate Token Leases to Rounds or Child Agents

The question owner partitions its remaining allowance into fixed leases before
dispatching workers or rounds. Each lease includes its own input and output
allowance. Unspent tokens return to the owner only after completion is settled.
Workers cannot independently increase their lease.

This is a less obvious alternative to a constantly shared mutable ledger: one
owner can distribute conservative allowances to separate processes without a
global counter update for every generated chunk.

**Pros:** Clear ownership; bounded concurrent allocations; useful for fan-out and
distributed work; no mandatory external proxy or new infrastructure for a
single-process prototype.

**Cons:** Stranded allocations can stop one worker while another has spare tokens.
Crash recovery, lease replay, and uncertain completion require coordination.
Fixed partitions can reduce answer quality. Each worker still needs the request
counting/capping controls of Option B; leasing alone does not provide exact counts.

**Effort:** High for durable distributed leases; Medium for local fixed partitioning.

**Libraries / Tools:** Existing Pydantic and Python concurrency primitives. Keep
durable transport/storage as a later design decision; no new package recommended.

**Existing Code to Reuse:** Bot dispatch and model-switching boundaries [C8], plus
the same provider funnels and counters [C1, C3, C7].

---

## Recommendation

**Option B** is recommended. It places enforcement where usage is created and
gives a precise meaning to the cumulative allowance. Option A can only provide an
after-the-fact cutoff; Option C becomes useful when distributed descendants are a
confirmed requirement.

Confirmed: `estimated` enforcement is the default for broad Mantle support, and
`strict` mode is opt-in for verified model/endpoint combinations. In strict mode
an unverified combination is rejected before inference rather than admitted on an
estimate. An estimated budget may overrun on an admitted request; it reports the
overrun and prevents further admissions after exhaustion is known.

Confirmed: one canonical cumulative ceiling, `token_budget`. "Budget" and "limit"
are the same number. A **final-answer reserve** is part of v1 (see Feature
Description); it is a partition of that ceiling, not extra capacity. A soft
warning threshold is out of scope for v1.

---

## Feature Description

### User-Facing Behavior

An application configures a question token allowance on a bot/client and may
override it per operation. Proposed names such as `token_budget`, `budget_mode`,
and `budget_exhausted` are design vocabulary, not existing APIs.

A direct client call creates its own question scope unless an outer caller
supplies one. Nested calls inherit the existing scope. A new top-level question
starts a new scope even if it shares conversation history with a previous one.
User input supplied to a suspended operation through `resume()` continues the
original scope; it is not automatically a new question.

Example, counting input plus output without caching:

| Request | Input | Output | Question consumption | Remaining from 10,000 |
|---|---:|---:|---:|---:|
| Initial tool-selection round | 2,000 | 500 | 2,500 | 7,500 |
| Tool-result round | 3,000 | 700 | 6,200 | 3,800 |
| Proposed next round | 3,200 | At most 600 | At most 10,000 | At least 0 |

The third request receives an output allowance no larger than 600, also bounded
by its model and configured per-request cap. If its required input instead costs
4,000, the request is denied before inference. Compaction can reduce a future
request's input; it never refunds tokens already processed.

Decided exhaustion behavior: a **final-answer reserve** plus a partial-result
fallback.

- Ordinary rounds (tool selection, tool-result processing, retries) may only draw
  on `token_budget - final_answer_reserve`. When the next ordinary round cannot be
  admitted from that working allowance, the tool loop stops.
- The loop then issues exactly one **finalization request**: tools disabled, input
  is the rendered history plus every completed tool result, output cap is whatever
  remains of the whole ceiling after the finalization input. This is the only
  request allowed to draw on the reserve. Its result is returned with
  `budget_exhausted=True` and `finalized=True`.
- If the finalization input alone does not fit in the remaining ceiling, no model
  call is made: return the partial output already obtained, with
  `budget_exhausted=True`, `finalized=False`, and the budget report.
- `final_answer_reserve` is a fraction of `token_budget` (default 15%) or an
  absolute integer, validated at configuration time; zero disables the reserve
  and the behavior collapses to the partial-result fallback.

Structured output must not label a partial, invalid object as a successful
validated result. Low-level admission failures may use a typed exception that an
outer boundary translates to the requested result contract; that exception must
not trigger fallback or become an ordinary tool error that the model keeps
retrying.

The report distinguishes configured limit, actual settled input/output, outstanding
or uncertain reservations, available tokens, rounds/attempts, counting mode, and
any observed overrun. Existing provider usage retains its documented meaning.

### Internal Behavior

1. Establish the operation scope before any covered LLM work for the question,
   including any LLM-based preprocessing. Use explicit context propagation and
   optionally a ContextVar for in-process inheritance; restore it on exit.
2. Fully prepare the next model request: rendered history, system content, current
   tool definitions/results, structured-output instructions, and model-specific
   parameters. Count the actual request shape after these transformations.
3. Under a short ledger lock, calculate available allowance as total limit minus
   settled debits and outstanding reservations, minus `final_answer_reserve` for
   ordinary rounds (the finalization request skips that subtraction). For input
   estimate/bound `I` and per-call output maximum `M`, allocate
   `O = min(M, available - I)`; reject if it cannot satisfy the model's minimum
   valid output/reasoning configuration. Atomically reserve `I + O`. Do not hold
   the lock during network I/O.
4. Pass the admitted output cap through the actual endpoint's supported parameter.
   Converse uses `inferenceConfig.maxTokens` [C1]; the current Mantle client sends
   `max_tokens` [C3]. Verify model-specific alternatives rather than assuming one
   parameter works for every model. For multiple completions, reserve the combined
   output maximum or reject that request shape initially.
5. Reconcile each physical attempt once against its authoritative response usage.
   Release unused reservation, preserving an explicit uncertain debit when usage
   is missing. Never count both round deltas and their final accumulated response.
6. Before further tool execution, stop if the working allowance is exhausted.
   Recheck after tool results change the next input. When an ordinary round is
   denied, transition to the single finalization request described above; when
   the finalization input does not fit either, return the partial result. A child
   LLM call needs its own reservation from the same parent ledger; non-LLM tool
   execution itself consumes no model tokens.
7. v1 keeps the ledger in process, keyed by the operation identifier that
   `resume()` state already carries. A resume in the same process reattaches to
   the live ledger. A resume with no live ledger (restart, other worker) fails
   with a typed error unless the caller passes a settled budget snapshot taken
   from a previous report; a snapshot can only raise settled consumption, never
   lower it. Concurrent resumes of one operation must not duplicate reservations
   or reset consumption. Restored state never silently mints a fresh allowance.
8. Emit observability after ledger transitions. The ledger is authoritative;
   asynchronous lifecycle subscribers remain reporting mechanisms [C9].

#### Counting support and normalization

- Bedrock Runtime `CountTokens` counts model-specific inputs for Converse or
  InvokeModel. The documented Converse counting schema includes messages, system,
  tool configuration, and additional model fields. Verify the installed SDK's
  service model and the selected model/region support before relying on it.
  [CountTokens API](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_CountTokens.html),
  [Converse counting schema](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_ConverseTokensRequest.html).
- Mantle has a Claude-specific `/anthropic/v1/messages/count_tokens` endpoint;
  the runtime SDK method does not target it. It accepts Anthropic message/tool
  shapes and is not a generic counter for every Mantle model. Our Mantle client
  uses Chat Completions, so converting that payload for counting is not proof of
  equivalent tokenization. Strict support needs verified equivalence or another
  exact/bounded counting path. Treat arbitrary Mantle models as unsupported for
  strict admission until verified.
  [AWS counting guide](https://docs.aws.amazon.com/bedrock/latest/userguide/count-tokens.html).
- For Bedrock prompt caching, AWS documents total input as `inputTokens +
  cacheReadInputTokens + cacheWriteInputTokens`. Existing `from_bedrock()` keeps
  the cache terms separately [C6]. The proposed all-token ledger adds those terms
  once; it cannot use current `CompletionUsage.total_tokens` alone for this policy.
  [AWS prompt caching](https://docs.aws.amazon.com/bedrock/latest/userguide/prompt-caching.html).
- For each Mantle model, verify whether cached/reasoning detail fields are subsets
  of reported input/output totals before normalization. Never blindly add detail
  counters to totals. Preserve provider raw usage and record unknown semantics.
- Existing `TiktokenCounter` and `HeuristicCounter` count text, not complete
  provider requests [C7]. Neither a different model's tokenizer nor bytes divided
  by four establishes a strict upper bound. Estimation margins can improve
  admission decisions but cannot establish an absolute guarantee.

### Edge Cases & Error Handling

- **Retries and fallback:** There is a retry loop inside `_chat_completion()`
  [C3], as well as outer fallback paths. Every attempt must be controlled. Audit
  and disable hidden SDK retries in strict mode, or reserve for their complete
  worst case; a guard only outside the retry funnel is insufficient. Recount when
  the fallback model changes. Budget termination is never a retryable error.
- **Ambiguous timeout/cancellation:** A request may have been processed without
  returned usage. Keep its maximum reservation charged/uncertain until settled;
  do not assume zero consumption. Strict guarantees additionally require that the
  admitted request's actual input/output cannot exceed its reservation.
- **Streaming:** Reserve before opening each stream and reconcile terminal usage
  per round. Retain the reservation if terminal usage never arrives. Chunk count
  and visible text omit some token categories; stopping a local iterator does not
  prove the server stopped generating. Keep the server-side output cap in force.
- **Parallel children:** Reserve atomically. In-process ContextVar inheritance
  carries the ledger reference but does not make compound updates atomic; the
  ledger's own lock does. Cross-process shared budgets are out of scope for v1
  and are rejected explicitly; a durable coordinator is a separate future design.
  Unknown provider descendants must not bypass enforcement silently.
- **Exhaustion during a tool chain:** Preserve already-completed tool results and
  distinguish unexecuted calls. Never replay side-effecting tools solely because
  the final answer did not fit. Check budget-control exceptions through broad tool
  and model-switching exception handlers [C4, C8].
- **Missing/malformed usage:** Validate fields; missing usage is not zero. Retain
  a conservative debit and report incomplete accounting. In estimated mode,
  reconcile an observed overrun honestly and stop subsequent admissions.
- **Final answer:** The finalization reserve is enabled by default (15% of
  `token_budget`, or an absolute integer) and covers both input and output of the
  closing request, inside the same total allowance. It is not free additional
  capacity. The finalization request runs with tools disabled so it cannot start
  another round; if its input alone exceeds what remains, it is skipped and the
  partial result is returned. A budget too small to ever fit a finalization
  input is a valid configuration that simply always ends in the partial path.
- **Compaction and thinking:** Context retention can improve the next request's
  fit but does not reset the ledger. A thinking-token allocation must remain valid
  under the reduced request output cap or the request must be rejected.

### Verification Targets for a Future Spec

- Numeric example above, exact exhaustion, zero budget, and input too large before
  the first request; no provider call occurs for a denied request.
- Finalization path: ordinary round denied while the reserve still fits → exactly
  one tools-disabled request, `finalized=True`; finalization input too large →
  no request, `finalized=False`; `final_answer_reserve=0` → partial path only;
  fraction and integer forms validate and resolve to the same ledger partition.
- Resume without a live ledger fails typed; resume with a settled snapshot
  continues from that consumption and cannot lower it.
- Multiple tool rounds, repeated input, cache reads/writes, reasoning details,
  and final-response aggregation without duplicate debits.
- Streaming disconnects, missing usage, request failure after possible processing,
  fallback to another model, and each retry attempt.
- Same-budget resume, independent-question reset on a reused client, concurrent
  children contending for the last allocation, and duplicate-resume protection.
- Unsupported strict model/request combinations fail before inference; estimated
  mode reports uncertainty and any overrun.
- Existing unbudgeted behavior remains compatible across inheriting clients.
  Mock provider responses for deterministic tests; use opt-in live probes only to
  qualify exact model/endpoint counting contracts.

---

## Capabilities

### New Capabilities

- `question-token-budget`: one cumulative allowance for a question operation.
- `token-budget-admission`: reserve input plus capped output before requests.
- `token-budget-reporting`: distinguish settled usage, reservations, and exhaustion.

### Modified Capabilities

- `bedrock-per-round-token`: its usage accounting supplies reconciliation data.
- `bedrock-mantle-client`: budget enforcement across inherited request paths.
- `tokens-observability`: optional budget context, keeping telemetry separate from
  request admission. Existing feature artifacts have some stale pre-extraction
  paths; the verified current locations below take precedence.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| Core budget module, proposed location `packages/ai-parrot/src/parrot/clients/budget.py` | adds | Policy, ledger, scope, reservation and error/report contracts; module does not exist today |
| `AbstractClient` | potentially extends | Common opt-in configuration/capability contract; foundational changes must be discussed during spec design |
| `BaseBot` / `AbstractBot` | modifies | Establish whole-question scope, forward configuration, retain resume identity [C8] |
| `BedrockConverseBase` | modifies | Admission on create/stream/native text invoke; reconcile every request [C1, C2] |
| `OpenAIBaseClient` | modifies | Shared wire/retry/stream hooks and resume accounting; unbudgeted inherited clients stay compatible [C3, C4] |
| `BedrockMantleClient` | extends | Model/endpoint capabilities and provider normalization [C5] |
| `CompletionUsage` and result metadata | depends on / optionally extends | Prefer a separate budget report over changing established total semantics [C6] |
| Memory compaction | depends on | Count after rendering; no refund of historical consumption [C7] |
| Model switching / supported child calls | modifies | Share allowance; do not retry exhaustion; prevent unsupported-provider bypass [C8] |

No deployment changes for local in-process scope. Durable cross-worker resumes
would add state coordination and require a separate explicit design decision.

---

## Code Context

### User-Provided Code

No code snippets were supplied. Original feature notes, preserved verbatim:

> Claude Code and Codex (and Anthropic API and OpenAI APIs) have limits for token budgets, but Amazon Bedrock and Mantle doesn't have usage limits, how to apply usage limits (in tokens) and token budgets for usage? the token budget / token limit is per-question (in a multi-turn operation, is the cumulative of all turns)

### Verified Codebase References

References were checked in current source after querying the wiki and reading its
Mantle documentation and Bedrock per-round usage spec. The wiki's older provider
paths are stale after extraction into the Amazon satellite package.

#### Classes & Signatures

| ID | Verified symbol / contract | Source |
|---|---|---|
| C1 | `BedrockConverseBase`; `async def _sdk_create(self, payload: dict) -> Dict[str, Any]`; `_sdk_stream` dispatches `converse_stream`; `_inference_config` sets `maxTokens` | `packages/ai-parrot-client-amazon/src/parrot/clients/amazon/bedrock.py:141`, `:393`, `:397`, `:523` |
| C2 | `ask()` has an internal tool loop and accumulated usage; `resume(self, session_id: str, user_input: str, state: Dict[str, Any]) -> AIMessage` starts a new local accumulator; streaming reads round metadata | `packages/ai-parrot-client-amazon/src/parrot/clients/amazon/bedrock.py:723`, `:895`, `:1265`, `:1374`, `:1454`, `:1587` |
| C3 | `async def _chat_completion(self, model: str, messages: Any, use_tools: bool = False, stream: bool = False, **kwargs) -> Any`; retries wrap the SDK invocation; per-request `max_tokens` is set by ask/stream | `packages/ai-parrot/src/parrot/clients/openai_base.py:216`, `:252`, `:641`, `:987` |
| C4 | `_run_tool_call_loop` defaults `track_usage=False`; `resume()` calls it without enabling accumulation and does not stamp a cumulative result; normal ask does stamp accumulated usage | `packages/ai-parrot/src/parrot/clients/openai_base.py:295`, `:308`, `:510`, `:748`, `:771`, `:795` |
| C5 | `class BedrockMantleClient(OpenAIBaseClient)`; inherits request machinery; `_fallback_model: str \| None = None`. `NovaClient` inherits `BedrockConverseBase` | `packages/ai-parrot-client-amazon/src/parrot/clients/amazon/nova/mantle.py:35`, `:101`; `packages/ai-parrot-client-amazon/src/parrot/clients/amazon/nova/client.py:34` |
| C6 | `CompletionUsage.from_openai(cls, usage: Any)` uses SDK attributes for three aggregate counts; `from_bedrock(cls, usage: Dict[str, Any])` retains cache counts in `extra_usage`; `__add__` shallow-merges extra fields | `packages/ai-parrot/src/parrot/models/basic.py:115`, `:147`, `:273` |
| C7 | `ContextBudget` controls retained context; `TokenCounter.count(self, text: str) -> int`, `TiktokenCounter`, `HeuristicCounter` are synchronous text counters | `packages/ai-parrot/src/parrot/memory/compaction/models.py:161`; `packages/ai-parrot/src/parrot/memory/compaction/tokens.py:30`, `:40`, `:70` |
| C8 | `BaseBot.ask` creates explicit `llm_kwargs`; `AbstractBot.execute_llm_call(self, client: AbstractClient, method: str = "ask", **llm_kwargs: Any) -> Any` delegates; bot resume delegates separately; model-switching fallback directly invokes secondary client | `packages/ai-parrot/src/parrot/bots/base.py:983`, `:1351`, `:1386`; `packages/ai-parrot/src/parrot/bots/abstract.py:1202`, `:4219`; `packages/ai-parrot/src/parrot/bots/mixins/model_switching.py:204`, `:228` |
| C9 | Before-client-call event is explicitly fire-and-forget and may run after inference begins | `packages/ai-parrot/src/parrot/clients/base.py:529` |

#### Verified Imports

These are source-verified exports/imports; no live authenticated client was created
and no import smoke test is claimed.

- `from parrot.clients.amazon import BedrockConverseClient, BedrockMantleClient, NovaClient`:
  exports at `packages/ai-parrot-client-amazon/src/parrot/clients/amazon/__init__.py:1`,
  backed by `amazon/client.py:14` and `:15` in that same source directory.
- `from parrot.clients.openai_base import OpenAIBaseClient`: class at
  `packages/ai-parrot/src/parrot/clients/openai_base.py:65`; relative import used
  by Mantle at `packages/ai-parrot-client-amazon/src/parrot/clients/amazon/nova/mantle.py:31`.
- `CompletionUsage` is imported from `parrot.models` by the existing shared
  client at `packages/ai-parrot/src/parrot/clients/openai_base.py:38`.

#### Key Attributes & Dependencies

- `CompletionUsage.extra_usage["rounds"]` is a local invocation round count, not
  a durable question budget; current Bedrock stamp at `amazon/bedrock.py:1084`
  under `packages/ai-parrot-client-amazon/src/parrot/clients/`.
- `BedrockConverseBase.ask(..., thinking_budget: Optional[int] = None, ...)` at
  `packages/ai-parrot-client-amazon/src/parrot/clients/amazon/bedrock.py:738`
  configures reasoning, not total question consumption.
- `pydantic==2.12.5`, `tiktoken>=0.9.0`, `openai==3.3.1`, and `tenacity>=8.2`
  are declared in `packages/ai-parrot/pyproject.toml:54`, `:64`, `:70`, `:52`.
- `aioboto3>=13.2.0` is declared in
  `packages/ai-parrot-client-amazon/pyproject.toml:17`. Current AWS documentation
  can exceed the installed SDK schema; upgrading a dependency is not authorized
  by this brainstorm and must be raised if implementation needs it.

### Does NOT Exist (Anti-Hallucination)

- No `TokenBudget`, `QuestionBudget`, `TokenBudgetExceeded`, `BudgetExceeded`,
  `usage_limit`, `question_id`, or `count_tokens` implementation was found in the
  searched core client/model trees and Amazon provider tree. Proposed budget API
  names above must be implemented, not imported as existing features.
- No cumulative question-level budget argument exists in the inspected Bedrock
  `ask()` signature. Its `max_tokens` and `thinking_budget` do not provide it.
- No enforcement barrier exists in `BeforeClientCallEvent` dispatch [C9].
- `packages/ai-parrot/src/parrot/clients/bedrock.py` and
  `packages/ai-parrot/src/parrot/clients/nova/mantle.py` no longer exist at the
  locations cited by the older wiki documents. Use the satellite paths above.
- No generic exact Mantle Chat Completions token-counting path was established
  by this research. The documented Claude Messages endpoint is not evidence that
  all Mantle models or Chat Completions payloads can be counted exactly.

---

## Parallelism Assessment

- **Internal parallelism:** First define ledger, reservation, normalization, and
  error contracts together. Provider adapters and their tests can then be developed
  independently; bot/resume propagation and shared-base integration should remain
  coordinated. This is a decomposition assessment, not a request to launch agents.
- **Cross-feature independence:** Shared surfaces overlap with
  `tokens-observability`, `bedrock-per-round-token`, `bedrock-mantle-client`, and
  memory/bot changes described in `.agent/CONTEXT.md`. This investigation does not
  establish that those historical features are currently in flight. Recheck active
  indexes before implementation, especially owners of the two base-client files.
- **Recommended isolation:** per-spec.
- **Rationale:** Budget identity, retry behavior, and terminal results cross core
  and satellite boundaries and need one coherent contract and integration review.

---

## Open Questions

- [x] What is the budget lifetime? — *Owner: Jesus Lara*: Per question, cumulative across every turn required to answer it; supplied explicitly in the original request.
- [x] What flow metadata is recorded? — *Owner: Codex*: `type: feature`, `base_branch: dev`, using the skill defaults because no override was supplied; these are not claimed as explicit user selections.
- [x] Should tokens mean input plus output including cache/repeated history, output only, or separate limits? — *Owner: Jesus Lara* (2026-09-11): **Input plus output, all categories.** Repeated history, tool schemas, system prompt, cache read/write and reasoning tokens all debit the ledger every time they are processed.
- [x] Is an absolute ceiling mandatory, or is explicitly estimated enforcement acceptable for unsupported counting paths? — *Owner: Jesus Lara* (2026-09-11): **`estimated` by default, `strict` opt-in.** Strict rejects unverified model/endpoint combinations before inference; estimated admits on tiktoken/heuristic counts and reports any observed overrun.
- [x] Is first-version scope Bedrock/Nova text and Mantle, or must other providers be implemented immediately? — *Owner: Jesus Lara* (2026-09-11): **Shared contracts in core plus Bedrock Converse/Nova text and Mantle adapters only.** Other clients remain uncovered and must say so; extending `OpenAIBaseClient` siblings is a later feature.
- [x] Should exhaustion return a partial result/status, raise publicly, or reserve a final-answer request? — *Owner: Jesus Lara* (2026-09-11): **Reserve a final-answer request** (`final_answer_reserve`, default 15% of the budget or an absolute integer, inside the same ceiling). One tools-disabled finalization request when ordinary rounds can no longer be admitted; if its input does not fit, return the partial result with `budget_exhausted=True` and no model call. No public exception on the bot boundary.
- [x] Must descendants and resumes work across process restarts/workers in v1? — *Owner: Jesus Lara* (2026-09-11): **In-process only.** Same-process `resume()` reattaches to the live ledger; a resume without a live ledger fails typed unless a settled snapshot is supplied. Durable cross-worker coordination is a separate future design.
- [x] Which exact models, endpoint routes, request shapes, and SDK versions qualify for strict input counting and output caps? — *Owner: Implementer* (resolved procedurally 2026-09-11): the spec must carry a **strict-qualification matrix** (model × endpoint × request shape × installed SDK) populated only by opt-in live probes; every entry not in the matrix runs in `estimated` mode. Strict support for Bedrock Converse via `CountTokens` is the first candidate; Mantle Chat Completions ships estimated-only until equivalence with the Claude count endpoint is proven.
- [x] Do "token budget" and "token limit" denote one ceiling, or is a separate soft planning target desired? — *Owner: Jesus Lara* (2026-09-11): **One cumulative ceiling, `token_budget`.** The final reserve is an internal partition of it. No soft warning threshold in v1.
