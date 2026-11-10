---
type: feature
base_branch: dev
projects: [ai-parrot, ai-parrot-client-needle]
tags: [needle, tool-calling, structured-output, local-inference]
docs:
  policy: required
  pages: [wiki/clients/needle.md]
  api_modules: [parrot.clients.needle, parrot.tools.needle_delegation]
---

# Feature Specification: Needle Tool-Calling Client and Delegation

**Feature ID**: FEAT-874
**Date**: 2026-11-10
**Author**: Jesus Lara / Codex
**Status**: approved
**Target version**: next minor

## 1. Motivation & Business Requirements

### Problem Statement

Provide a tool-call-first client in `parrot.clients` for extraction-only agents and a
ToolManager method through which an existing agent delegates a bounded tool request and
receives structured results. Pydantic input and output models must become model schemas
automatically; callers must not redeclare functions using a provider decorator.

FEAT-590 already provides a plan-node `NeedleDelegate` using `cactus-needle==3.0.4`.
It proposes one call, is not an AbstractClient, and deliberately returns None for extraction.
That code is development precedent, not a production compatibility contract. This is a new
product: no legacy API, dependency, behavior or coinstallation compatibility is required.

### Goals

- G1: Discoverable `needle:needle3` client with typed extraction and bounded tool execution.
- G2: Automatic conversion of existing tool input schemas and Pydantic extraction models.
- G3: Internal `search_tool` catalogue stage, followed by inference over at most five concrete tools.
- G4: Direct agent delegation through its existing ToolManager, preserving permissions and result envelopes.
- G5: Async-safe local inference, explicit refusal/error results, deterministic offline tests.

### Non-Goals (explicitly out of scope)

General chat, summarization, free-text fallback, autonomous multi-step planning, training,
speech/vision, embedding-provider integration, and migration of FEAT-590 are out of scope.
Embedding-based catalogue ranking may be a later feature; v1 reuses lexical ranking.
Structured output guarantees a validated representation, not semantic correctness or guaranteed execution.

- G6: Evaluate Needle 3 first, following the provenance and incomplete-run discipline of
  `sdd/state/FEAT-589/verification/evaluation-summary.json`. Production modules depend on
  this evidence gate; this specification does not claim that the evaluation has run.

## Governing Decisions

<!-- decision-audit: input_digest=sha256:e25a47365e2ae0038d1aea6c6d3ff005d9b69fcbfa9a5050a1d5141ed693a2db evaluation_digest=sha256:76c6bc73778992e55cc365819d1e309a00646c8f015d608f450b84190965aed7 rules_version=1 status=pass -->

## 2. Architectural Design

### Overview

Two phases: M0 produces an isolated, runnable evaluation and a measured go/no-go decision;
M1–M4 implement the production integration only after M0 passes. A failed or incomplete
evaluation is a valid research outcome but does not complete this integration feature.

The proposed new distribution is `ai-parrot-client-needle`, contributing
`parrot.clients.needle:NeedleClient` through the existing `parrot.clients` entry-point group.
The runtime targets only `cactus-compute==4.1.0` (`import cactus`), using Needle 3 weights.
This is the latest published release verified on 2026-11-10 against
[PyPI release metadata](https://pypi.org/project/cactus-compute/4.1.0/) (released 2026-11-07).
The user explicitly selected the current API without legacy compatibility. M0 evaluates
this exact pin; M4 uses the same pin and replaces the old `cactus-needle==3.0.4` extra entry.
Do not add legacy adapters, dual SDK selection or compatibility tests. If a newer stable
release appears before M0 begins, refresh and record the exact pin before freezing the run;
any upgrade after measurements requires rerunning M0, never an unbounded dependency range.

Only the client's runtime boundary calls the native SDK. It calls `complete()`, never
`run()`, and never passes executable Python tools to Cactus. The host owns selection,
Pydantic validation and dispatch. Each request starts with reset model state and explicit
facts; hidden SDK conversation memory never spans requests. Nonempty conversation history
is unsupported in v1 and raises a capability error; the owning agent must provide a
self-contained extraction text or delegated instruction. No automatic model fallback.

Tool mode accepts an explicit allowlist of registered names. Missing names fail before
inference; an empty allowlist returns a structured no-match. A client with no explicit
allowlist uses only its supplied ToolManager's registered, non-internal tools. SDK output
cannot expand this set. Recheck membership immediately before dispatch.

For five or fewer eligible tools, infer directly. For larger catalogues, use a request-local
internal tool named `search_tool`, never permanently registered in the shared manager.
Its only input is `query: str`, described as words copied from the current request. Run one
discovery inference with only that schema. Validate its name and arguments; rejection ends
the request. Rank the full allowed catalogue using the existing lexical scoring rules;
filter by allowlist before limiting, discard scores <= 0, break ties by tool name and select
at most five. Then run one fresh inference over those concrete schemas and the ORIGINAL
instruction. The search result contributes schema selection, not invented argument facts.
There is no recursive search, arbitrary tool-loading, or implicit retry. If a registered
tool has the reserved name `search_tool`, report `reserved_tool_name` for this mode.
Report selected names and search timing. This bounds context independently of upstream
retrieval behavior; it does not guarantee catalogue recall.

One concrete inference may emit several independent calls, capped at five per request.
Validate the whole batch before dispatch: allowed names, JSON-object arguments, visible
schema, confidence when configured, and grounding flags. No suppressed call is executed.
Reject malformed, ungrounded or oversized batches without side effects. Execute accepted
calls sequentially through `ToolManager.execute_tool(..., return_tool_result=True)`;
stop on the first non-success result, preserving already completed results. No retries,
rollback claim, automatic replay or model turn using results. This is bounded tool execution,
not a reasoning loop. Cancellation propagates; previously completed side effects remain.

`ToolManager.delegate_tool_call()` is an opt-in thin entry point. It receives an explicit
NeedleClient instance and the caller's PermissionContext, takes a request-local catalogue
view, and returns a typed result envelope. It neither replaces the agent's primary LLM
nor swaps the client's ToolManager reference. Both client mode and manager mode call one
shared orchestration function, avoiding recursion and duplicate dispatch. The caller owns
client cleanup; the manager never closes a supplied client.

Extraction compiles the requested Pydantic model as a single synthetic record tool and
validates accepted arguments with the original class in the parent process. Do not use
the upstream extraction helper's recovery of suppressed calls. No match returns typed
`status='no_match'`, not an invented record. Extraction never executes a business tool.
Tool mode and extraction mode are mutually exclusive. Output validation for business tools
uses an optional caller-supplied `result_models: Mapping[str, type[BaseModel]]`; ai-parrot
does not currently declare a universal output-schema attribute on AbstractTool. Validate
successful ToolResult.result after execution; preserve guard-produced output and report
`output_validation_error` without retrying or pretending the side effect was undone.

### Schema contract

Read AbstractTool.get_schema() so runtime context and hidden arguments remain excluded;
read ToolDefinition.input_schema for plain registered functions. Preserve names, field
descriptions, required lists, defaults, aliases, enum values and numeric/string/list bounds.
Compile acyclic local `$defs` references without mutating source schemas. Support nested
objects, arrays and nullable single-type unions. Reject recursive/remote references,
arbitrary unions and unsupported schema keywords with a JSON-path-bearing
`unsupported_schema` error before native inference; never drop constraints silently.
Original Pydantic models remain the final authority for custom validators. Validate visible
arguments using the existing `jsonschema>=4.20` dependency (Draft 2020-12), including raw
ToolDefinition inputs. The manager then performs normal full-model validation with runtime
context. Do not call full args_schema validation prematurely when hidden required fields
have not been injected. Introducing a new validator is unnecessary.

### Runtime and lifecycle

Use a bounded spawned worker PROCESS for native inference, accessed with asynchronous IPC.
Only JSON-compatible schemas, text, facts and settings cross the boundary; live tools,
credentials, PermissionContext and dynamic Pydantic classes remain in the parent. One
active native call per worker, bounded queue (default 8), startup timeout 120 s, inference
timeout 30 s. Timeout/cancellation terminates and reaps the worker, invalidates its cache,
and cannot later dispatch a late reply. Close is idempotent and reaps workers. Recreate on
the next explicit request; do not replay the cancelled request. Cache at most eight engine
instances per worker, keyed by canonical schema contents, facts, weights revision and
generation settings, not names alone. M0 verifies actual engine close/reset behavior.
M0 also verifies multiprocessing on the target host; do not inherit FEAT-590's thread fallback.

### Component Diagram

```text
M0 evaluation + decision --> schema/models --> process runtime --> NeedleClient
                                                             |        |
existing Agent --> ToolManager.delegate_tool_call --> orchestration <--+
                                      | search_tool -> bounded catalogue
                                      +-> validation -> ToolManager.execute_tool
                                                         -> typed result envelope
```

### Integration Points

| Existing component | Integration | Contract |
|---|---|---|
| AbstractClient | Subclass, no base edit | ask/invoke, lifecycle, supplied ToolManager |
| LLMFactory | Installed entry point | `needle = parrot.clients.needle:NeedleClient` |
| ToolManager | Add one opt-in method | Existing execute_tool remains sole dispatcher |
| AbstractTool / ToolDefinition | Schema readers | No provider decorators or base-schema mutation |
| AIMessage / InvokeResult / ToolResult | Reuse envelopes | Structured output and guard statuses preserved |
| FEAT-590 | Research precedent only | No legacy API or behavior compatibility gate |

### Data Models

New core models in `parrot.tools.needle_models` use Pydantic v2 and `extra='forbid'`.
`NeedleCall` has `name: str` and `arguments: dict[str, Any]`.
`NeedleProposal` has `calls: list[NeedleCall]`, `confidence: float|None`,
`suppressed_count: int`, `ungrounded_fields: list[str]` and `elapsed_ms: float`.
`NeedleExecutionResult` has `status` in `success|no_match|rejected|partial|error`,
`results: list[ToolResult]`, `calls: list[NeedleCall]`, `selected_tools: list[str]`,
`error_code: str|None` and `metadata: dict[str, Any]`. Calls include only validated proposals;
results correspond to the executed prefix. `NeedleExtractionResult` has `status` in
`success|no_match|error`, `value: Any`, `error_code: str|None`; a success value is the
original Pydantic instance. Both result types are structured even on refusal.
Runtime exceptions use `NeedleError(code: str, message: str)`; stable codes are
`unsupported_schema`, `unsupported_capability`, `runtime_unavailable`, `runtime_timeout`,
`runtime_protocol_error`, `queue_full`, `unknown_tool`, `reserved_tool_name`, `invalid_args`,
`ungrounded`, `low_confidence`, `unscored`, `too_many_calls`, `output_validation_error`.
Permission denials retain the existing ToolResult status rather than becoming no-match.

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided contract | Why not |
|---|---|---|---|
| M0 evaluation | no | Evidence and thresholds below | Requires real runtime measurements and disposition |
| M1 schemas/models | yes, after M0 | Strict conversion subset and typed envelopes | — |
| M2 process runtime/client | no | Process isolation and AbstractClient methods | Version/platform compatibility must first be measured |
| M3 manager orchestration | yes, after M0 | Two inference stages, existing dispatch only | — |
| M4 packaging/docs/regressions | yes, after M0 | Current API only, exact 4.1.0 pin, entry point and docs/tests | — |

### Module 0: First evaluation and adoption decision

Paths: `artifacts/needle/{__init__.py,models.py,worker.py,evaluate.py,README.md}`, fixtures
`artifacts/needle/fixtures/{calibration,evaluation}.jsonl`, tests
`packages/ai-parrot/tests/unit/test_needle_evaluation.py`, and evidence
`sdd/state/FEAT-874/verification/{evaluation-summary.json,decision.md}`.
Depends on no production module. The evaluation adapter is an AbstractClient subclass
inside the harness; SDK access remains within that adapter's process boundary. M0 must
not add production entry points or change core dependencies. Use a separate environment
for the evaluated runtime and record exact resolved packages and the command to reproduce it.

```python
class EvaluationConfig(BaseModel):
    """Pinned worker interpreter, model/runtime revisions, timeout, warmup, repeats and output directory."""
    worker_python: Path
    weights_path: Path
    weights_sha256: str
    runtime_version: str
    seed: int = 42
    warmup: int = 1
    repeats: int = 3
    startup_timeout_s: float = 120.0
    inference_timeout_s: float = 30.0
    run_timeout_s: float = 3600.0
    max_input_chars: int = 4000
    max_output_tokens: int = 512
    min_confidence: float | None = None
    output_dir: Path
class EvaluationCase(BaseModel):
    """Unique ID, split, bucket, prompt, catalogue, expected call set or refusal, provenance."""
class EvaluationReport(BaseModel):
    """Complete/incomplete evidence, per-case outputs, quality, timing, resource and gate results."""
async def run_evaluation(config: EvaluationConfig, cases: list[EvaluationCase]) -> EvaluationReport:
    """Run real local inference; errors count in denominators and cannot produce a passing gate."""
def main(argv: list[str] | None = None) -> int:
    """Exit 0 pass, 1 completed no-go, 2 invalid input, 3 incomplete/runtime failure."""
```

### Module 1: Shared schemas and result contracts

Paths: `packages/ai-parrot/src/parrot/tools/needle_models.py`,
`packages/ai-parrot-client-needle/src/parrot/clients/needle/schema.py`;
test `packages/ai-parrot-client-needle/tests/test_schema.py`. Depends on M0.

```python
def compile_tool_schema(name: str, description: str, parameters: dict[str, Any]) -> dict[str, Any]:
    """Return a detached supported Cactus schema or raise NeedleError with the failing JSON path."""
def compile_output_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Compile a Pydantic extraction model as the single synthetic record tool."""
class NeedleError(RuntimeError):
    """Provider-boundary failure with a stable code and no prompt/credential leakage."""
    def __init__(self, code: str, message: str) -> None:
        """Record the stable error code and diagnostic message."""
```
All model fields and status semantics are fixed by §2 Data Models; no new tool output
attribute is added to AbstractTool.

### Module 2: NeedleClient and process runtime

Paths: new satellite `src/parrot/clients/needle/{__init__.py,client.py,runtime.py,worker.py}`;
tests `tests/{test_client.py,test_runtime.py}`. Depends on M0 and M1.
Use the complete base ask/invoke parameter contracts verified in §6; additional parameters
are keyword-only. `model='needle3'` is the default; reject other model names unless configured
as a pinned compatible custom weights path. `use_tools=False` never executes tools.
`ask(structured_output=...)` returns AIMessage with NeedleExtractionResult in output/data;
tool mode returns NeedleExecutionResult. `invoke` is extraction-only in v1, returns
InvokeResult.output as NeedleExtractionResult, and wraps failures in existing InvokeError.
Reject files, deep_research, background, unsupported formats/custom parsers and nonempty
history explicitly. Buffered ask_stream yields one JSON string then the final AIMessage;
it does not claim native token streaming. `resume` raises unsupported_capability.

```python
class NeedleRuntime:
    """Owned process boundary; schemas and scalar configuration only, never executable tools."""
    async def complete(self, text: str, schemas: list[dict[str, Any]], *, facts: dict[str, str]) -> NeedleProposal:
        """Return a normalized proposal; timeout/cancellation reaps the worker before returning."""
    async def aclose(self) -> None:
        """Idempotently terminate and reap all owned workers."""

class NeedleClient(AbstractClient):  # verified: packages/ai-parrot/src/parrot/clients/base.py:297
    """Tool-calling and typed-extraction client; no free-text generation."""
    def __init__(self, *, weights: str | None = None, min_confidence: float | None = None, **kwargs: Any) -> None:
        """Accept base client configuration; do not load weights at construction."""
    async def get_client(self) -> NeedleRuntime:
        """Return the lazily owned runtime for the current event loop."""
    async def propose_calls(self, instruction: str, schemas: list[dict[str, Any]], *, facts: dict[str, str] | None = None) -> NeedleProposal:
        """Infer without dispatch; at most five tool schemas per native request."""
    async def extract(self, text: str, output_type: type[BaseModel], *, facts: dict[str, str] | None = None) -> NeedleExtractionResult:
        """Compile, infer and validate a single record without recovering suppressed calls."""
    async def ask(self, prompt: str, model: str = 'needle3', max_tokens: int | None = None,
                  temperature: float = 0.7, files: list[str | Path] | None = None,
                  system_prompt: str | None = None, history: Sequence[HistoryMessage] | None = None,
                  structured_output: type | StructuredOutputConfig | None = None,
                  tools: list[dict[str, Any]] | None = None, use_tools: bool | None = None,
                  deep_research: bool = False, background: bool = False, lazy_loading: bool = False,
                  *, permission_context: PermissionContext | None = None,
                  allowed_tools: Sequence[str] | None = None,
                  result_models: Mapping[str, type[BaseModel]] | None = None, **kwargs: Any) -> AIMessage:
        """Return a structured extraction or execution envelope; reject unsupported capabilities."""
    async def invoke(self, prompt: str, *, output_type: type | None = None,
                     structured_output: StructuredOutputConfig | None = None, model: str | None = None,
                     system_prompt: str | None = None, max_tokens: int | None = None,
                     temperature: float = 0.0, use_tools: bool = False, tools: list | None = None) -> InvokeResult:
        """Stateless extraction; structured_output wins over output_type; no tool dispatch."""
    async def ask_stream(self, prompt: str, model: str | None = None, max_tokens: int | None = None,
                         temperature: float = 0.7, files: list[str | Path] | None = None,
                         system_prompt: str | None = None, history: Sequence[HistoryMessage] | None = None,
                         tools: list[dict[str, Any]] | None = None, deep_research: bool = False,
                         agent_config: dict[str, Any] | None = None, lazy_loading: bool = False,
                         **kwargs: Any) -> AsyncIterator[str | AIMessage]:
        """Yield one serialized structured response then its AIMessage; buffered streaming."""
    async def resume(self, session_id: str, user_input: str, state: dict[str, Any]) -> MessageResponse:
        """Raise unsupported_capability; no suspended native conversations are retained."""
    async def close(self) -> None:
        """Close the current loop's runtime and retain the base lifecycle contract."""
    async def close_all(self) -> None:
        """Close all owned per-loop runtimes and base resources."""
```

`tools=` only narrows schemas for registered tools; unknown executable definitions are rejected.
Generic system prose is not a substitute for facts; callers supply facts through extract/
propose APIs or constructor configuration. Reject nonempty system_prompt in v1 rather than
silently claiming instruction-following. Sampling parameters that the pinned SDK cannot
honor are recorded as unsupported metadata at their base defaults; nondefault requests fail.
Usage values unavailable from the runtime are marked unavailable in metadata, never fabricated
as measurements. Required numeric envelope fields may use zero only with this explicit flag.

### Module 3: ToolManager delegation and catalogue orchestration

Paths: modify `packages/ai-parrot/src/parrot/tools/manager.py`; create
`packages/ai-parrot/src/parrot/tools/needle_delegation.py` and test
`packages/ai-parrot/tests/tools/test_needle_delegation.py`. Depends on M1 and M2.
Lazy satellite imports occur only when explicitly invoking this feature. Core import works
without Cactus or the satellite installed. The client is caller-owned, no global singleton.

```python
# Method added to ToolManager; verified class: packages/ai-parrot/src/parrot/tools/manager.py:292
async def delegate_tool_call(self, instruction: str, *, client: NeedleClient,
                             allowed_tools: Sequence[str],
                             permission_context: PermissionContext | None = None,
                             facts: Mapping[str, str] | None = None,
                             result_models: Mapping[str, type[BaseModel]] | None = None) -> NeedleExecutionResult:
    """Delegate selection and execute through this manager, returning structured results only."""

async def execute_needle_request(manager: ToolManager, client: NeedleClient, instruction: str, *,
                                 allowed_tools: Sequence[str], permission_context: PermissionContext | None,
                                 facts: Mapping[str, str] | None = None,
                                 result_models: Mapping[str, type[BaseModel]] | None = None) -> NeedleExecutionResult:
    """Shared bounded orchestration; never call client.ask or recursively delegate."""
def search_tool(manager: ToolManager, query: str, allowed_tools: Sequence[str]) -> list[str]:
    """Search the allowed registered catalogue, returning at most five positive lexical matches."""
```

### Module 4: Packaging, documentation and current API installation

Paths: satellite `pyproject.toml`, `README.md`, `tests/test_entry_points.py`, and
`wiki/clients/needle.md`; modify `packages/ai-parrot/pyproject.toml` to replace the obsolete
Needle extra dependency with `cactus-compute==4.1.0` and update its comment. Depends on M0–M3.
Namespace packages follow the existing local
client satellite. Workspace membership is already `packages/*`; no root manifest edit is
needed. Installation is explicit (`uv pip install -e packages/ai-parrot-client-needle` in
an activated environment); update the `needle` runtime extra to the current pin, without adding to `all`.
If workspace lock regeneration is required, M4 owns `uv.lock` exclusively; retain unrelated
resolutions outside this feature. Both manifests pin `cactus-compute==4.1.0`, matching M0;
there is no old-extra resolution or legacy SDK compatibility requirement.
No runtime/model download at import, factory discovery or installation.

```python
# New satellite __init__.py public export and packaging contract:
from .client import NeedleClient
# [project.entry-points."parrot.clients"]
# needle = "parrot.clients.needle:NeedleClient"
```

## 4. Test Specification

### First evaluation: efficiency and suitability (M0)

Follow FEAT-589's evidence shape, not its classification labels: immutable source-report
hashes, complete/incomplete status, limitations, exact configuration, model identity,
fixture hashes, per-scenario denominators, errors, abstentions, prediction flips and separate
inference/roundtrip/end-to-end p50/p95 timings. A successful API call is not a correct answer.
Record CPU model/core count, RAM, OS/architecture, Python/runtime versions, engine and weight
revision/hash, quantization, thread/process settings, cold startup and peak process-tree RSS.

Use 40 calibration cases and at least 200 distinct held-out English cases, with disjoint
IDs and paraphrase families. Freeze fixtures, schemas, expectations and threshold before
held-out inference. Repeated runs do not increase the independent accuracy sample count.
Minimum held-out buckets: 60 positive single calls; 20 independent multi-call requests;
20 missing-required arguments; 20 off-topic; 20 negated/quoted/reported requests; 20 bounds,
enum and ambiguous-input cases; 20 extraction records; 20 large-catalogue requests.
Include ride booking with pickup/dropoff/seats and invoice extraction based on the user's
examples, plus sanitized representative ai-parrot tool schemas with stubbed implementations.
Fixtures include nested objects, nullable fields, aliases and custom validators. Clearly
separate unsupported-schema tests from inference-quality denominators.

Run paired catalogue configurations of 1, 5, 20 and 100 tools where applicable: direct
small-set inference, raw full catalogue as an observational arm, and explicit search stage.
Report discovery recall@5 separately from call accuracy given correct selection and overall
end-to-end accuracy. Include tools outside the lexical top five to expose retrieval misses.
Do not execute real business side effects: only deterministic local fake tools behind an
actual ToolManager. Compare with a deterministic lexical-selection baseline on the same
fixtures; report its coverage and failures rather than presenting it as a general LLM.

Default one warmup and three measured repetitions, seed 42, maximum input 4,000 characters,
512 output tokens, startup 120 s, per-call 30 s, whole-run cap 60 minutes. Reject or record
oversized inputs; do not truncate evidence. Confidence threshold is either disabled or
chosen on calibration only and frozen. Measure concurrency 1 and 4, queue delay, throughput,
event-loop heartbeat delay, worker cleanup after cancellation, and cold versus warm latency.

Metrics: tool-name accuracy; exact arguments with only schema-defined normalization;
unordered call-set exact match for independent calls; field-level extraction accuracy;
schema-valid rate; required-field omission and invented-value rates; correct refusal rate;
false execution rate; conditional accuracy versus coverage at the chosen confidence threshold;
errors/timeouts; end-to-end latency including selection, IPC, validation and fake dispatch.
Use Wilson 95% intervals on case-level proportions. Count errors and unjustified abstentions
as incorrect on positive cases. Preserve raw predictions and per-case execution counts.

Draft go/no-go thresholds, frozen before the first held-out run: at least 90% exact positive
call-set accuracy, 90% exact extraction records, 95% correct refusals, 95% large-catalogue
recall@5, 85% overall catalogue call accuracy, zero dispatched invalid/unknown/disallowed or
negated calls, no process leaks, <= 1% runtime failures, warm end-to-end p95 <= 1,000 ms at
concurrency 1 and peak process-tree RSS <= 1 GiB on the recorded CPU host. These are adoption
targets, not upstream claims or existing measurements. Failure, absent measurements or
missing supported-platform evidence yields no-go/incomplete; M1–M4 remain blocked pending
an explicit revised spec, not a weakened threshold after seeing held-out results.

An optional provider comparison uses an installed AbstractClient, exact requested and returned
model IDs, token usage and explicit call/token caps supplied by the operator. It is not
required for the local gate. Unverified model identity, fallback or unavailable pricing means
no cost/speed superiority claim. Local-only results cannot establish cloud savings. No paid
calls or downloaded weights are required to author this spec or run deterministic CI.

Persist JSON and Markdown raw reports under `artifacts/needle/reports/<run-id>/`, test logs
under `artifacts/logs/`, and a compact hash-linked summary plus decision under
`sdd/state/FEAT-874/verification/`. Record `decision: go|no_go|incomplete`, per-threshold
observations, limitations and the tested package pin. Never synthesize performance numbers.

### Unit Tests

| Area | Required cases |
|---|---|
| Evaluation | Disjoint splits, denominator errors, missing model identity, hash mismatch, incomplete run cannot pass |
| Schemas | Required/default/null, enums/bounds, nested refs, aliases, hidden fields, unsupported keywords, no mutation |
| Runtime | Lazy import, startup failure, bounded queue, cancellation kills worker, late replies ignored, close twice |
| State | Same names/different schema or facts do not reuse stale state; concurrent tenants do not cross-contaminate |
| Client | Typed extraction/no-match, malformed output, invoke precedence, buffered stream sentinel, unsupported modes |
| Catalogue | >5 tools, deterministic ties, zero matches, reserved name, denied tools never selected, original text preserved |
| Execution | Validate whole batch first, exact once, stop on failed result, no retry, context passed unchanged |
| Results | Permission/auth/pending status preserved, output-model failure after execution does not replay |

### Integration Tests

Stub native IPC responses but use real NeedleClient orchestration and real ToolManager with
fake tools. Test the Agent-supplied manager path, extraction model instance identity, permission
denial before side effect, 100-tool catalogue selection, and cancellation before dispatch.
Existing full-result tests guard the manager execution contract. Legacy delegate tests are
not an acceptance gate for this new product. Native M0 evaluation
is separate measured evidence, not a mock-based CI claim.

### Validation Contract

tests:
- packages/ai-parrot/tests/unit/test_needle_evaluation.py
- packages/ai-parrot/tests/tools/test_needle_delegation.py
- packages/ai-parrot/tests/tools/test_toolmanager_full_result.py
- packages/ai-parrot-client-needle/tests/test_schema.py
- packages/ai-parrot-client-needle/tests/test_runtime.py
- packages/ai-parrot-client-needle/tests/test_client.py
- packages/ai-parrot-client-needle/tests/test_entry_points.py
markers: none

New test paths are declared deliverables, not existing tests. Decomposition must stage the
evaluation-only gate first and must not execute later missing test operands before M0 passes.

## 5. Acceptance Criteria

- [ ] M0 real CPU evaluation and hash-linked summary exist; per-bucket metrics and limitations are visible.
- [ ] M0 go/no-go thresholds pass before production implementation is released; no missing measurement is a pass.
- [ ] Factory discovers `needle:needle3` only when the satellite is installed, without importing/loading the native runtime.
- [ ] Pydantic schemas compile automatically and invalid/unsupported schemas fail before inference.
- [ ] Extraction preserves the requested Pydantic type inside a structured result; no-match is explicit.
- [ ] Both client mode and direct manager delegation dispatch solely through execute_tool with caller context.
- [ ] Catalogue path uses search_tool then <=5 concrete schemas, with no recursive search or invented arguments.
- [ ] Suppressed, invalid, disallowed, ungrounded or rejected proposals cause zero tool executions.
- [ ] Tool outputs remain structured; optional result validation failures never trigger duplicate side effects.
- [ ] Native inference does not block the event loop; timeout/cancellation/close leave no orphan worker.
- [ ] Current API and exact evaluated dependency pin are used; no legacy compatibility layer is introduced.
- [ ] Existing manager guards/results remain unchanged; declared CI tests pass.
- [ ] Documentation covers capability limits, installation, evaluation results and reproducible examples.

## 6. Codebase Contract

Verified against `2e35d887fa5d0af626eb06d3da6e3b5bb1c24da9`; relevant source files unchanged
from the initial research commit `9506ea52615ecc3eef4cb158e7db34f426d83409`.

### Verified Imports and Existing Class Signatures

| Import / symbol | Existing contract | Verified at |
|---|---|---|
| `from parrot.clients.base import AbstractClient` | ABC; accepts tool_manager, tools, use_tools, kwargs | `packages/ai-parrot/src/parrot/clients/base.py:297`, constructor :460 |
| AbstractClient.ask | prompt/model/max_tokens/temperature/files/system_prompt/history/structured_output/tools/use_tools/deep_research/background/lazy_loading | `packages/ai-parrot/src/parrot/clients/base.py:1950` |
| AbstractClient.ask_stream / resume / invoke | Abstract methods; invoke returns InvokeResult | `packages/ai-parrot/src/parrot/clients/base.py:1991`, :2019, :2037 |
| `from parrot.tools.manager import ToolManager, ToolDefinition` | ToolDefinition(name, description, input_schema, function, routing_meta, required_permissions) | `packages/ai-parrot/src/parrot/tools/manager.py:34`, :292 |
| ToolManager.rank_tools | `(query: str, limit: int = 15) -> list[tuple[float, Any]]`; lexical score, deterministic name tie-break | `packages/ai-parrot/src/parrot/tools/manager.py:726` |
| ToolManager.get_tool | `(tool_name: str) -> Optional[Any]` | `packages/ai-parrot/src/parrot/tools/manager.py:1395` |
| ToolManager.execute_tool | `(tool_name, parameters, permission_context=None, *, return_tool_result=False) -> Any` | `packages/ai-parrot/src/parrot/tools/manager.py:1799` |
| `from parrot.tools.abstract import ToolResult, AbstractTool` | ToolResult carries success/status/result/error/metadata; args_schema is a Pydantic class | `packages/ai-parrot/src/parrot/tools/abstract.py:252`, :283, :300 |
| AbstractTool.get_schema | `() -> Dict[str, Any]`; hides context fields, preserves $defs | `packages/ai-parrot/src/parrot/tools/abstract.py:617`, :668 |
| `from parrot.models.responses import AIMessage, InvokeResult` | Structured output/data, metadata, tool_calls; InvokeResult requires output/model/usage | `packages/ai-parrot/src/parrot/models/responses.py:94`, :1345 |
| `from parrot.models.outputs import StructuredOutputConfig` | output_type and get_schema(), optional custom_parser | `packages/ai-parrot/src/parrot/models/outputs.py:59` |
| `from parrot.models.basic import ToolCall` | id/name/arguments, optional result/error/execution_time | `packages/ai-parrot/src/parrot/models/basic.py:23` |
| LLMFactory discovery | Installed `parrot.clients` entry points, lazy ep.load | `packages/ai-parrot/src/parrot/clients/factory.py:134` |
| Legacy NeedleDelegate | max_tools=5, propose_call, extraction always None | `packages/ai-parrot/src/parrot/bots/flows/plan/delegate/needle.py:102`, :234 |
| Existing legacy dependency | optional cactus-needle==3.0.4 | `packages/ai-parrot/pyproject.toml:789` |
| Satellite packaging precedent | namespaces, parrot.clients entry point, workspace core dependency | `packages/ai-parrot-client-local/pyproject.toml:25` |
| Evaluation evidence precedent | report hashes/status/config/metrics/limitations, not production suitability | `sdd/state/FEAT-589/verification/evaluation-summary.json:1` |

Other annotations in interface skeletons refer to existing base-method types; downstream
tasks must verify their exact imports from base.py before implementation. New symbols in
§3 are declared additions, never existing APIs.

### Does NOT Exist (Anti-Hallucination)

- `parrot.clients.needle`, NeedleClient and ToolManager.delegate_tool_call do not yet exist.
- Existing `search_tools` (plural) returns JSON text; the proposed `search_tool` is request-local.
- No universal AbstractTool.output_schema contract was found; use the explicit result_models map.
- No `parrot.models.invoke` module: InvokeResult is in `parrot.models.responses`.
- FEAT-590's extraction method does not implement native extraction; do not treat it as usable extraction.
- `cactus-compute==4.1.0` is verified as the latest published release; local platform/runtime
  suitability remains unmeasured until M0.

### User-Provided Examples and Upstream Evidence

The requested ride schema has pickup/dropoff strings described by source spans and integer
seats constrained to 1–6 with default 1. The requested Invoice has vendor:str, total:float,
due_date:str and po_number:str|None=None. Preserve these semantics in M0 fixtures, using
Pydantic models rather than requiring @needle.tool in user applications.

Checked 2026-11-10: the [model card](https://huggingface.co/Cactus-Compute/needle3) now points
to cactus-compute and `cactus.Cactus`. The [Python API](https://cactuscompute.com/blog/needle-python-docs)
documents complete/reset and states Needle 3 has no retrieval head. The
[tool-design guide](https://cactuscompute.com/blog/designing-tools-for-needle) still describes
top-five retrieval above five tools. Treat this as conflicting documentation, not a verified
runtime invariant. The [extraction guide](https://cactuscompute.com/blog/structured-extraction-with-needle)
documents recovery from suppressed calls; this feature deliberately declines those records.
M0 records observed behavior for the exact 4.1.0 pin; no vendor benchmark substitutes for measurements.

### Edit Sites (Blueprint Anchors)

Only one existing Python file changes. Anchor count verified with `grep -Fc`: 1.
The CREATE groups below enumerate each file; the grouping only shortens repeated prefixes.

| File | Action | Verbatim anchor | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/tools/manager.py` | MODIFY | `    async def execute_tool(` | :1799 | 1 |
| `packages/ai-parrot/pyproject.toml` | MODIFY | `needle = [` | :791 | 1 |
| `uv.lock` | MODIFY (M4 resolution) | `version = 1` | `uv.lock:1` | 1 |
| `packages/ai-parrot/src/parrot/tools/needle_models.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/tools/needle_delegation.py` | CREATE | — | — | — |
| `packages/ai-parrot-client-needle/pyproject.toml` | CREATE | — | — | — |
| `packages/ai-parrot-client-needle/README.md` | CREATE | — | — | — |
| `packages/ai-parrot-client-needle/src/parrot/clients/needle/__init__.py` | CREATE | — | — | — |
| `packages/ai-parrot-client-needle/src/parrot/clients/needle/client.py` | CREATE | — | — | — |
| `packages/ai-parrot-client-needle/src/parrot/clients/needle/runtime.py` | CREATE | — | — | — |
| `packages/ai-parrot-client-needle/src/parrot/clients/needle/worker.py` | CREATE | — | — | — |
| `packages/ai-parrot-client-needle/src/parrot/clients/needle/schema.py` | CREATE | — | — | — |
| `packages/ai-parrot-client-needle/tests/test_schema.py` | CREATE | — | — | — |
| `packages/ai-parrot-client-needle/tests/test_runtime.py` | CREATE | — | — | — |
| `packages/ai-parrot-client-needle/tests/test_client.py` | CREATE | — | — | — |
| `packages/ai-parrot-client-needle/tests/test_entry_points.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/tools/test_needle_delegation.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/unit/test_needle_evaluation.py` | CREATE | — | — | — |
| `artifacts/needle/__init__.py` | CREATE | — | — | — |
| `artifacts/needle/models.py` | CREATE | — | — | — |
| `artifacts/needle/worker.py` | CREATE | — | — | — |
| `artifacts/needle/evaluate.py` | CREATE | — | — | — |
| `artifacts/needle/README.md` | CREATE | — | — | — |
| `artifacts/needle/fixtures/calibration.jsonl` | CREATE | — | — | — |
| `artifacts/needle/fixtures/evaluation.jsonl` | CREATE | — | — | — |
| `sdd/state/FEAT-874/verification/evaluation-summary.json` | CREATE during M0 | — | — | — |
| `sdd/state/FEAT-874/verification/decision.md` | CREATE during M0 | — | — | — |
| `wiki/clients/needle.md` | CREATE | — | — | — |

## 7. Implementation Notes & Constraints

Use async-first APIs, Pydantic v2, self.logger, black and ruff. No direct SDK invocation
outside the client-owned adapter; no changes to clients/base.py. Never send credentials,
permission context, hidden arguments or arbitrary prior tool results to the model.
Catalogue visibility follows the caller's allowlist; execute_tool remains the authorization
boundary. A whitelist is not a replacement for PermissionContext or confirmation guards.
Do not treat schema correctness as truth, and do not bypass guards because confidence is high.

### External Dependencies

| Dependency | Version / policy | Purpose |
|---|---|---|
| cactus-compute | `==4.1.0`; latest published release verified 2026-11-10; evaluated first in M0 | Current Needle 3 runtime |
| cactus-needle | Remove existing 3.0.4 declaration from the Needle extra in M4 | Obsolete development dependency; no compatibility obligation |
| Pydantic | Existing workspace v2 dependency | Schemas and final validation |
| jsonschema | Existing >=4.20, verified `packages/ai-parrot/pyproject.toml:97` | Visible argument validation |
| Python standard library | Existing supported interpreter | Processes, IPC, hashing, metrics |

M0 must verify wheel/platform availability, model licensing and offline cache behavior before
packaging. The user authorizes the latest current runtime pin; evaluation must still establish
its suitability before production implementation. Do not install
training, GPU or embedding libraries merely to run tool inference.

### Known Risks / Gotchas

Top-five selection can omit the correct tool; expose recall independently of model accuracy.
Native schema compilers may implement only a subset; reject unsupported shapes. Required
nullable is not optional: preserve Pydantic's required list. Engine caches keyed only by names
can leak stale facts/schema; include content and reset per request. CPU timings are host-specific.
The earlier FEAT-590 spike reported process trouble: M0 must reproduce or resolve it before
adopting this runtime design. Guarded output can differ from raw tool output; never recover
unredacted data merely to satisfy an output model. Failed validation after a side effect cannot
be rolled back automatically. No benchmark report is proof of production safety.

## Consequences

<!-- decision-audit: input_digest=sha256:e25a47365e2ae0038d1aea6c6d3ff005d9b69fcbfa9a5050a1d5141ed693a2db evaluation_digest=sha256:76c6bc73778992e55cc365819d1e309a00646c8f015d608f450b84190965aed7 rules_version=1 status=pass -->

Audit status: `pass` (exit 0)

Findings:
- none

Diagnostics:
- `SPEC_BLOCK_MISSING`; path: /home/jesuslara/proyectos/ai-parrot/sdd/specs/needle-tool.spec.md; message: no fenced yaml block under '## Decisions'

Coverage:
- Subsystems: bots, clients, config, flows, knowledge-graphindex, knowledge-pageindex, knowledge-wiki, memory, skills, tools
- Unmapped tags: local-inference, needle, structured-output, tool-calling
- Targets resolved: 0/0
- Impact complete: true
- Inventory complete: true
- Omitted ids: not recorded

```json
{
  "coverage": {
    "impact_complete": true,
    "inventory_complete": true,
    "omitted_ids": [],
    "subsystems": [
      "bots",
      "clients",
      "config",
      "flows",
      "knowledge-graphindex",
      "knowledge-pageindex",
      "knowledge-wiki",
      "memory",
      "skills",
      "tools"
    ],
    "targets_resolved": 0,
    "targets_total": 0,
    "unmapped_tags": [
      "local-inference",
      "needle",
      "structured-output",
      "tool-calling"
    ]
  },
  "diagnostics": [
    {
      "code": "SPEC_BLOCK_MISSING",
      "decision_id": null,
      "message": "no fenced yaml block under '## Decisions'",
      "path": "/home/jesuslara/proyectos/ai-parrot/sdd/specs/needle-tool.spec.md"
    }
  ],
  "evaluation_digest": "sha256:76c6bc73778992e55cc365819d1e309a00646c8f015d608f450b84190965aed7",
  "exit_code": 0,
  "findings": [],
  "input_digest": "sha256:e25a47365e2ae0038d1aea6c6d3ff005d9b69fcbfa9a5050a1d5141ed693a2db",
  "snapshot": {
    "approvals_digest": "6e5b5a5fb07d04ec7e7cdbf3afac1a634711ea195aa4061a8261bcf61b19992f",
    "config_digest": "sha256:a6bce9c0800713c30eaa78146ad0c06399f6ec0e9b083129e494abb6fd073343",
    "inventory": {
      "adr:doc:171b17ccd26bdbd2d71040746b22371a335d364d": "b22c79daae2a187f2091ea23449825e8769e2c07",
      "adr:doc:34394c36f5bf140678b8e17d43c3628e3d2c1440": "3fa15352d0e9ed972bd5de7ac1fd60e06906e60b",
      "adr:doc:666d8f740c695673063f76777db7b7b0e9d95a2e": "47f1bebe56724843f6c0981f67bbba72917b4b0b",
      "adr:doc:87781d348dff80cbfb25c253989a8940badd08d1": "49458f64f4bb614a9ff42750b53d9caa806f81a0",
      "adr:doc:89e808b78adee5c727e047ac239817bfd29e5cfe": "9feeb90ec52cb53395d978a3b946323a7b9072ab",
      "adr:doc:96dabb33251cd210186d7ab5c456ded102a4b025": "b537050f62f77a85b651af8c2595f4dc7fd4cebe",
      "adr:doc:c3c29b415ba46e730ee37c6fc520914a1905d022": "0cd9cc9f082b9d988da023e3886d310f8eed8eae",
      "adr:doc:c6b0e17a26d4b1ae2be8569a33db9a3aeedc0fbd": "804496ec336c99570df5502580ff980a38f56bfc",
      "adr:doc:e7c5ae770b06db3b35cdd4cba93001a58bfa7bef": "394f4656c71618a256427d81350fdc32335fa791"
    },
    "rules_version": 1,
    "structural_revision": "sha256:b11fe8e33d80455017c18de7c66615b790b28eae29c88d3cc6defc398db393fb",
    "taxonomy_digest": "65548b9a71329b13ab44f4904dff99814e1aac0da4bb2b58171a7201e3a9ba39"
  },
  "status": "pass"
}
```

## 8. Open Questions

- [x] Scope — user requested both a tool-first client and internal ToolManager delegation.
- [x] Evaluation ordering — user requested a first Needle 3 efficiency evaluation like FEAT-589.
- [x] Current API versus legacy compatibility — resolved by user: new product, no legacy compatibility;
  use the latest published exact pin, `cactus-compute==4.1.0` as verified 2026-11-10.
- [ ] Target platform viability on the pinned current runtime — owner: M0; required gate evidence.
- [ ] Are the draft quality/latency/RSS targets suitable for the deployment CPU? Owner: spec reviewer;
  freeze any changes before held-out inference.
- [ ] Optional cloud comparison provider/model/budget — owner: evaluation operator; omit comparison when unset.

## 9. Design Research Cross-Check

Status: skipped (direct request with notes; no accepted brainstorm/proposal or completed
intake synthesis exists, so the independent research precondition was not met).
Source verification and FEAT-589 evidence inspection were performed; they are not an
independent design review.

## 10. Documentation

- Policy: required.
- Create `wiki/clients/needle.md`: installation, supported schemas, extraction and Agent
  delegation examples, structured refusals/errors, catalogue recall limits, permissions,
  process cleanup, offline setup, the current API/version requirement, and links to M0 results/limitations.
- Create satellite README with minimal setup and explicit capability matrix.
- Create evaluation README with exact reproducible command, pinned environment, fixture provenance,
  budgets, metrics and go/no-go interpretation.
- API modules: `parrot.clients.needle`, `parrot.tools.needle_delegation`; complete typed docstrings.

## Worktree Strategy

Isolation: per-spec — one FEAT-874 worktree; task-level sub-worktrees managed by SDD.
M0 is first. All production modules depend on its passing evidence; the current-only API choice is settled.
M1 -> M0; M2 -> M1; M3 -> M1 and M2 (uses NeedleClient.propose_calls and shared models);
M4 -> M0, M1, M2 and M3 (packages and documents the implemented public interfaces).
Independent test/schema fixture work may run concurrently within these actual dependencies.
Shared file: manager.py belongs exclusively to M3. Exclusive resource: lock resolution in
M4 and measured native evaluation in M0 require parallel:false. No other module writes the
lock or runs competing performance measurements. FEAT-590 and FEAT-589 are already present;
no unmerged cross-feature dependency is required.

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-11-10 | Jesus Lara / Codex | Draft; evaluation-first gate, client and guarded manager delegation |
| 0.2 | 2026-11-10 | Jesus Lara / Codex | User approved current API only; pin cactus-compute 4.1.0 and remove legacy compatibility gates |
