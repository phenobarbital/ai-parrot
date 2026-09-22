---
id: FEAT-589
title: Evaluate Laya for typed classification and agent model routing
slug: laya-adoption
type: feature
base_branch: dev
status: approved
projects: [ai-parrot, ai-parrot-client-jev]
tags: [laya, classification, model-routing, guardrails, evaluation]
proposal: sdd/proposals/laya-adoption.proposal.md
created: 2026-09-21
updated: 2026-09-21
---

# Feature Specification: Laya CPU Evaluation

**Feature ID**: FEAT-589
**Date**: 2026-09-21
**Author**: Codex, for Jesus Lara
**Status**: approved
**Target version**: standalone evaluation; no package release required

The proposal's FEAT-585 is a research-state identity, not this feature's reserved identity.
The allocator returned FEAT-589. Preserve the proposal and its research directory as provenance.
Projects and tags are carried from the proposal; Jev is comparative context only. The Anthropic
satellite is consumed by the experiment but is not modified.

## 1. Motivation & Business Requirements

### Problem Statement

Evaluate whether Laya can provide useful typed decisions for prompt-injection classification,
same-provider model routing inside an assigned AI-Parrot Agent, and classification grounded in
a supplied document. Marketing latency and model confidence are not evidence of local suitability.
Existing availability fallback does not establish that a selected model is cheaper.

### Goals

- Deliver a runnable end-to-end Python evaluation under `artifacts/laya/`, on CPU, in English.
- Exercise real Laya inference in all three scenarios and optional real Anthropic calls in routing.
- Compare injection results with the existing regex baseline on identical English samples.
- Report reproducible timings, decisions, errors, usage and limitations; produce an exploratory
  report without numerical production-adoption gates.
- Preserve the requester's primary model preference, `anthropic:opus-5`, as configuration intent.
  Verify the actual provider identifier before claiming a successful live run.

### Non-Goals (explicitly out of scope)

Production adoption; Jev replacement; shared clients/bots/guardrails changes; ToolManager or flow
integration; PII redaction; training; ONNX conversion; GPU or multilingual benchmarking;
answer-versus-evidence entailment; streaming and tool-enabled agent routing.

## 2. Architectural Design

### Overview

A host CLI uses the existing repository environment and launches one persistent isolated Python
worker for synchronous Laya inference. Communicate through newline-delimited JSON on subprocess
stdin/stdout, using asyncio subprocess streams in the host. Worker diagnostics go to stderr;
capture third-party stdout so it cannot corrupt the protocol. One request is outstanding at a time.
The worker explicitly uses CPU and loads one English checkpoint once. Startup, load, warmup,
inference and transport time are measured separately. No inference runs on the host event loop.

Use a local checkpoint snapshot identified by immutable revision and content hashes. Worker setup
is an explicit documented action; it never installs packages or downloads weights implicitly at
CLI startup. The separate environment isolates Laya's tensor dependencies from the workspace.
Missing dependencies/snapshot produce a structured incomplete report and actionable instructions.

For injection, ask one `noul` question whose positive outcome means injection. Use its positive
probability for the verdict, never its confidence. The exploratory threshold defaults to 0.5 and
is recorded; tuning is permitted only on disjoint calibration fixtures. Compare both engines on
the same manifest, preserve framework wrappers, and report that the regex baseline strips its
allowlisted framework metadata. This is a comparison with that regex engine, not parity with the
entire production guardrail stack.

For routing, Laya chooses `primary`, `cheap` or `abstain` from a fixed choice question; it cannot
emit model names. A validated decision maps through the run's explicit model allowlist.
Abstention, missing/invalid output, timeout and confidence below the recorded routing threshold
(default 0.8) select primary and retain a reason. An evaluation-only `Agent` subclass uses a
ContextVar-bound decision in `execute_llm_call`, copies kwargs, injects the selected model, and
delegates to `super().execute_llm_call`. Reset the ContextVar in `finally`; never mutate client
defaults. Restrict evaluation to `ask`, `use_tools=False`, `use_vector_context=False` and
`use_conversation_history=False`. Run paired primary-only and routed calls on the same fixtures
with separate sessions and matching generation settings.

`anthropic:opus-5` is the requested primary label, not a verified alias. The inspected Anthropic
model enum contains no OPUS_5; its direct backend passes strings unchanged. Do not silently map it
to a different family. Accept an explicit `--primary-api-model` for the provider identifier and
record both values. Require `--cheap-api-model` and positive `--max-live-calls` for `--live`;
otherwise perform real local routing inference and mark downstream evaluation `incomplete`.
Both live model IDs use one direct Anthropic client configuration. Live preflight rejects missing
inputs before requests, and provider model errors are recorded without substitution. These are
run-time inputs, not a blocker to implementing the evaluation harness.

The live cap counts logical `Agent.ask` calls across both arms, including failed calls; reserve
a slot before dispatch. Require two remaining slots before starting a pair. Record the client's
existing SDK retry/fallback behavior: a logical-call cap is not a hard HTTP-attempt or money cap.
Use an explicit output-token limit (default 256). No live calls are executed while writing this spec.
Read the provider-returned model from `AIMessage.raw_response['model']` where available;
`AIMessage.model` alone is insufficient proof because the factory accepts the requested model.
Record requested, selected, reported and provider-returned models plus fallback metadata. Missing
actual-model evidence makes verification incomplete. Unknown or mismatched models remain visible.

For grounded classification, provide a document and the labels `billing`, `technical`, `sales`,
`other`, `insufficient_evidence`. The question explicitly requires evidence from that document.
Include absent facts and contradictory documents labeled `insufficient_evidence`; never treat
typed output alone as a groundedness guarantee. Report accuracy, confusion matrix and abstention.

### Component Diagram

```text
English fixtures + CLI configuration
                  |
          async evaluation runner ------> regex baseline
                  |
          persistent CPU worker (Laya)
                  |
          validated typed decisions
                  |
          optional routed Agent -------> Anthropic client
                  |
          JSON report + Markdown report
```

### Integration Points

| Existing component | Integration | Constraint |
|---|---|---|
| `Agent` / `AbstractBot.execute_llm_call` | Evaluation subclass | Preserve super dispatch and budget hook; no core edits |
| `AnthropicClient.ask` | Per-call `model` | Same provider, tools disabled, no direct SDK use |
| `AIMessage` | Evidence and usage | Preserve raw model and fallback evidence separately |
| `PromptInjectionDetector` | Regex baseline | Same held-out texts, normal framework stripping |
| Injection benchmark corpus | Fixture provenance | Explicit English manifest; no inferred language field |

### Data Models

All host-owned structured records use Pydantic v2 with forbidden extra fields and finite numbers.
These schemas are new evaluation contracts, not existing Parrot APIs.

| Model | Required fields / invariants |
|---|---|
| `EvaluationConfig` | `worker_python: Path`, `checkpoint_path: Path`, `checkpoint_revision: str`, `scenario: Literal['all','injection','routing','grounded']`, `live: bool=False`, `primary_label: str='anthropic:opus-5'`, `primary_api_model: str|None`, `cheap_api_model: str|None`, `max_live_calls: int=0`, `max_output_tokens: int=256`, `injection_threshold: float=0.5`, `routing_threshold: float=0.8`, `startup_timeout_s: float=300`, `prediction_timeout_s: float=30`, `warmup: int=3`, `repeats: int=10`, `seed: int=42`, `output_dir: Path`; thresholds in [0,1], positive timeouts/repeats/tokens, nonnegative warmup/call cap |
| `EvaluationCase` | `id: str`, `scenario`, `language: Literal['en']`, `split: Literal['calibration','evaluation']`, `state: str`, `expected: str`, `bucket: str`, `source: str`, `source_sha256: str|None`; unique IDs; expected label belongs to scenario's declared set |
| `PredictionRequest` | `request_id: str`, `state: str`, `questions: dict[str, dict[str, Any]]`; one fixed schema per scenario |
| `PredictionResult` | `request_id: str`, `status: Literal['ok','error']`, `answers: dict[str, dict[str, Any]]`, `inference_ms: float|None`, `roundtrip_ms: float|None`, `error_code: str|None`, `error_message: str|None`; answers validated before scenario scoring |
| `RouteDecision` | `choice: Literal['primary','cheap','abstain']`, `selected_model: str|None`, `confidence: float|None`, `reason: str`; no model invented when CLI inputs absent |
| `SampleResult` | `case_id`, `scenario`, `repeat`, `expected`, `predicted: str|None`, `status`, `error_code`, `timings_ms`, `decision: RouteDecision|None`, `requested_model`, `selected_model`, `reported_model`, `actual_model`, `fallback_metadata`, `usage`, `answer: str|None`, `quality_pass: bool|None`; nullable fields remain null rather than zero |
| `EvaluationReport` | `schema_version: Literal['1']`, `status: Literal['complete','incomplete','error']`, `config`, `environment`, `fixture_sha256`, `question_schemas`, `samples: list[SampleResult]`, `metrics`, `limitations`; secrets excluded from serialization |

Stable error codes: `dependency_missing`, `checkpoint_missing`, `startup_timeout`,
`inference_timeout`, `worker_protocol_error`, `worker_failed`, `invalid_answer`, `context_overflow`,
`live_config_missing`, `provider_error`, `model_unverified`, `call_cap_reached`.
Configuration/schema errors raise `ValueError` before execution; operational failures are records.
Propagate cancellation after shutting down the child. Do not turn operational errors into benign
injection verdicts or successful grounded classifications.

### New Public Interfaces

The supported entry point is `python -m artifacts.laya.evaluate` from the repository root.
CLI flags correspond to `EvaluationConfig` fields using hyphenated names, plus `--fixtures`.
`--help` works without Laya installed. No new public package API is introduced.
Output directory must be new or empty; never overwrite an existing report implicitly.
Exit codes: 0 complete exploratory run, 2 invalid CLI configuration, 3 incomplete/error report.

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1 models and fixtures | yes | §2 schemas, English JSONL, fixed label sets, finite validation | — |
| M2 worker and transport | no | Persistent subprocess, JSONL, explicit CPU, deadlines and shutdown | Installed Laya compatibility and token-budget preflight require verification against the pinned version |
| M3 routing adapter | yes | ContextVar scope, explicit allowlist, super dispatch, §2 errors | — |
| M4 evaluation/report CLI | yes | Three scenarios, paired calls, §2 exit codes, §4 metrics | — |
| M5 tests/documentation | yes | Exact acceptance matrix below; mocked and optional real runs separate | — |

### Module 1: Models and fixtures

- **Paths**: new `artifacts/laya/__init__.py`, `artifacts/laya/models.py`,
  `artifacts/laya/fixtures/injection.jsonl`, `routing.jsonl`, `grounded.jsonl`.
- **Responsibility**: §2 models and stable, explicitly labeled English datasets.
- **Depends on**: existing Pydantic v2; benchmark source used only for provenance.
- **Interface Skeleton**:

```python
# artifacts/laya/models.py (new)
def load_cases(path: Path, scenario: str) -> list[EvaluationCase]:
    """Validate JSONL cases; reject duplicate IDs, unknown labels and split overlap."""

def validate_answers(request: PredictionRequest, result: PredictionResult) -> PredictionResult:
    """Validate required question IDs, answer types, choice membership and finite probabilities."""
```

Model classes have the fields specified in §2; use their standard Pydantic validation interfaces.
Choice probabilities must cover exactly the declared choices, lie in [0,1], and sum to 1 within
0.001 rounding tolerance. `noul` and confidence must be finite in [0,1]. No scoring of malformed
results. Keep original case order and a manifest hash; do not infer language through ASCII checks.

### Module 2: Isolated CPU inference

- **Paths**: new `artifacts/laya/worker.py`, `artifacts/laya/runtime.py`,
  `artifacts/laya/pyproject.toml` (standalone, outside workspace membership).
- **Responsibility**: worker-only optional Laya imports, lifecycle, schema boundary and timing.
- **Depends on**: M1; externally installed, pinned Laya runtime.
- **Interface Skeleton**:

```python
# artifacts/laya/worker.py (new; synchronous child-process entry point)
def main(argv: Sequence[str] | None = None) -> int:
    """Load the pinned CPU checkpoint and serve one JSONL request at a time until stdin EOF."""

# artifacts/laya/runtime.py (new)
class LayaWorker:
    """Own one isolated inference subprocess and its request/response stream."""
    def __init__(self, config: EvaluationConfig) -> None:
        """Store configuration without loading models or starting a process."""
    async def __aenter__(self) -> LayaWorker:
        """Start the worker and await a validated ready record within the startup deadline."""
    async def predict(self, request: PredictionRequest) -> PredictionResult:
        """Serialize inference; return validated result or explicit operational error."""
    async def __aexit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        """Close input, await exit, then terminate/kill with bounded waits if necessary."""
```

Ready record includes package versions, checkpoint revision/hash, actual device, token limits,
load time and worker PID. Each response echoes the request ID. Reject malformed/mismatched records.
On timeout, terminate and reap the worker; mark remaining inference incomplete rather than queue
work behind a hung prediction. Use a five-second graceful shutdown then terminate and, after a
further five seconds, kill and await exit. Drain stderr concurrently with bounded retention.
Capture worker peak RSS with platform/unit metadata; unsupported metrics are null with a reason.
Check tokenized input plus question/options against the checkpoint's actual limits before calling
inference. Reject overflow; no silent truncation of evidence. Verify this preflight against the
installed runtime's serialization and truncation behavior before marking M2 complete.

### Module 3: Request-local routing

- **Path**: new `artifacts/laya/routing.py`.
- **Responsibility**: allowlisted selection and scoped model injection.
- **Depends on**: M1, existing Agent and client dispatch.
- **Interface Skeleton**:

```python
# artifacts/laya/routing.py (new)
# Agent verified: packages/ai-parrot/src/parrot/bots/agent.py:1325
# Hook verified: packages/ai-parrot/src/parrot/bots/abstract.py:1215
def choose_route(result: PredictionResult, config: EvaluationConfig) -> RouteDecision:
    """Choose only a configured model; abstention/error/low confidence retains primary."""

class LayaEvaluationAgent(Agent):
    """Evaluation-only Agent with a request-scoped downstream model decision."""
    async def ask_routed(self, question: str, decision: RouteDecision, **kwargs: Any) -> AIMessage:
        """Bind decision, call inherited ask, and reset its ContextVar even on cancellation."""
    async def execute_llm_call(
        self, client: AbstractClient, method: str = "ask", **llm_kwargs: Any
    ) -> Any:
        """Inject the scoped model into copied ask kwargs and delegate through super."""
```

An unbound decision leaves parent behavior unchanged; a bound decision without a model is an
invalid live configuration. Tests establish request isolation at the hook; the CLI itself runs
sequentially and makes no claim that an entire shared Agent is concurrency-safe.

### Module 4: Scenarios, reporting and CLI

- **Paths**: new `artifacts/laya/evaluate.py`, `artifacts/laya/reporting.py`.
- **Responsibility**: invoke three scenarios, optional live pairs, quality checks and report output.
- **Depends on**: M1–M3, existing regex detector and Anthropic satellite.
- **Interface Skeleton**:

```python
# artifacts/laya/evaluate.py (new)
async def run_evaluation(config: EvaluationConfig, cases: list[EvaluationCase]) -> EvaluationReport:
    """Run requested scenarios, preserving incomplete evidence and enforcing the logical-call cap."""

def main(argv: Sequence[str] | None = None) -> int:
    """Parse configuration, run the async evaluation, write reports and return a documented exit code."""

# artifacts/laya/reporting.py (new)
def summarize(samples: list[SampleResult]) -> dict[str, Any]:
    """Compute scenario metrics with explicit denominators and error/abstention counts."""

def write_report(report: EvaluationReport, output_dir: Path) -> tuple[Path, Path]:
    """Write results.json and report.md to a new/empty directory without overwriting existing data."""
```

### Module 5: Regression checks and reproducible instructions

- **Paths**: new `packages/ai-parrot/tests/unit/test_laya_evaluation.py`,
  `packages/ai-parrot/tests/integration/test_laya_evaluation.py`, `artifacts/laya/README.md`.
- **Responsibility**: the tests below, explicit environment/weight setup, commands and interpretation.
- **Depends on**: M1–M4. No production interface; test module skeletons:

```python
async def test_request_local_model_isolation() -> None:
    """Interleave scoped dispatch calls and verify independent model kwargs and unchanged defaults."""

async def test_real_cpu_scenarios() -> None:
    """Opt-in run of all scenarios with real local inference; distinguish unavailable live evidence."""
```

## 4. Test Specification

### Unit Tests

| Test | Module | Required evidence |
|---|---|---|
| Answer validation | M1 | Missing answers, wrong type, unknown choice, NaN/Inf, out-of-range and invalid probability sums rejected |
| Confident negative | M1/M4 | `noul=0.01, confidence=0.99` is negative at threshold 0.5 |
| Fixture validation | M1 | English only, unique IDs, all buckets, label validity, calibration/evaluation disjointness |
| Worker protocol/deadlines | M2 | Fake child exercises startup/inference timeout, stderr noise, malformed IDs, cancellation and reaping |
| Context limits | M2 | Boundary/overflow cases do not silently truncate state or options |
| Routing fallback | M3 | Invalid, abstained and low-confidence results retain primary with distinct reasons |
| Model isolation | M3 | ContextVar reset on success/error/cancel, copied kwargs, super hook reached, defaults unchanged |
| Live configuration/cap | M4 | No calls by default; missing IDs fail preflight; both arms counted; no partial pair after cap |
| Model evidence | M4 | Raw provider model preferred; requested-only metadata cannot establish actual execution; fallback visible |
| Reports | M4 | Correct confusion matrix/quantiles, null unavailable values, failed samples not silently excluded, no overwrite |

### Integration Tests

| Test | Description |
|---|---|
| Mocked end-to-end | Fake protocol worker and fake client produce all reports without model downloads or credentials |
| Real CPU scenarios | Explicit opt-in; real pinned Laya, all three scenarios, CPU verified, warm repeats and startup measured |
| Live paired routing | Explicit opt-in and supplied IDs/cap/key; validate actual-model evidence and usage for both arms |

Tests live beside the core distribution; logs go to `artifacts/logs/laya_evaluation_pytest.log`.
Optional integrations skip with a reason when prerequisites are absent; skipped tests are never
presented as live execution evidence. Run focused pytest, black (120 columns), ruff and diff checks.

### Test Data / Fixtures

Commit explicit English samples with IDs, bucket, label, split and provenance. Injection fixtures
include at least two examples per existing bucket (`clean`, `clean_framework`, `attack_direct`,
`attack_paraphrase`, `attack_obfuscated`), selected from the existing benchmark with content hashes.
Routing includes at least three simple, three complex and two ambiguous requests with expected
routes. Each has an answer-quality rubric of required facts or an exact expected short answer;
store rubric fields in a companion `artifacts/laya/fixtures/routing_rubrics.json` keyed by case ID.
Grounded fixtures include at least two cases per label, including missing and contradictory facts.
All labels are human-authored before inference. Report these as smoke datasets, not representative
production accuracy estimates. Warmup never contributes to measured timings; repeated inference
does not increase the number of independent labeled examples.

Report cold startup/load, worker inference and end-to-end warm p50/p95, repeat/warmup counts,
peak worker RSS, CPU/platform/thread configuration, Python/runtime/checkpoint identity, corpus and
schema hashes, thresholds, per-case predictions, errors, abstentions and confusion matrices.
Percentiles use a documented deterministic nearest-rank definition. Quality metrics use one
record per unique example; prediction changes across repeats are reported separately. Routing
adds labeled-route accuracy, primary/cheap proportions, paired answer-rubric pass rates, latencies
and usage. Cost estimates are optional and require explicit per-model input/output price assumptions
and date in `--price-file`; missing prices yield null cost, never a savings claim. Do not infer that
the configured cheap model is cheaper from its name or the framework's fallback setting.

## 5. Acceptance Criteria

- [ ] Runnable documented CLI and versioned fixtures exist under `artifacts/laya/`.
- [ ] Real CPU inference executes injection, routing classification and document categorization.
- [ ] The regex baseline uses the identical English injection fixture manifest.
- [ ] Positive probability, choice validation and error/abstention policies pass regression tests.
- [ ] Request-local routing preserves parent dispatch, client defaults and budget propagation.
- [ ] Live routing is opt-in, model inputs explicit, logical calls capped, actual-model evidence
  recorded; absent credentials/model IDs leave that scenario incomplete and clearly reported.
- [ ] JSON and Markdown reports capture reproducibility, latency, resource use, quality and failures.
- [ ] Real local reports are produced for review; if prerequisites prevent execution, the feature
  remains unverified rather than claiming end-to-end completion. Live evidence is conditional on
  supplied valid IDs/credentials/cap and is not required to claim local-classifier evaluation only.
- [ ] Focused tests/lint pass; optional skips and limitations are disclosed.
- [ ] No workspace dependency/lockfile or production code changes; documentation covers isolated setup.
- [ ] No numerical adoption gate or production-readiness conclusion is invented.

## 6. Codebase Contract

These imports and signatures are verified from source, not by loading optional runtime dependencies.
Implementation must verify any additional API before using it.

### Verified Imports

```python
from parrot.bots.agent import Agent
# verified: packages/ai-parrot/src/parrot/bots/agent.py:1325
from parrot.clients.base import AbstractClient
# verified: packages/ai-parrot/src/parrot/bots/abstract.py:35 (existing import)
from parrot.clients.anthropic import AnthropicClient
# verified: packages/ai-parrot-client-anthropic/src/parrot/clients/anthropic/__init__.py:1
from parrot.models.responses import AIMessage
# verified: packages/ai-parrot/src/parrot/models/responses.py:75
from parrot.security.prompt_injection import PromptInjectionDetector
# verified: packages/ai-parrot/src/parrot/security/prompt_injection.py:27
from benchmarks.injection_guardrail_latency.corpus import build_eval_set
# verified: benchmarks/injection_guardrail_latency/corpus.py:197
```

### Existing Class Signatures

| Symbol | Verified signature / contract | Anchor |
|---|---|---|
| `AbstractBot.execute_llm_call` | `async def execute_llm_call(self, client: AbstractClient, method: str = 'ask', **llm_kwargs: Any) -> Any`; propagates root budget ownership | `packages/ai-parrot/src/parrot/bots/abstract.py:1215` |
| `AbstractBot.configure` | `async def configure(self, app=None) -> None` | `packages/ai-parrot/src/parrot/bots/abstract.py:1500` |
| Inherited `ask` | `question: str`, `use_vector_context: bool=True`, `use_conversation_history: bool=True`, `use_tools: bool=True`, `**kwargs`; returns `AIMessage` | `packages/ai-parrot/src/parrot/bots/base.py:984` |
| Ask dispatch kwargs | Builds explicit kwargs without forwarding an arbitrary caller `model` | `packages/ai-parrot/src/parrot/bots/base.py:1356` |
| `AnthropicClient.ask` | Exact signature below; supports per-call model and output-token limit | `packages/ai-parrot-client-anthropic/src/parrot/clients/anthropic/client.py:470` |
| `AnthropicClient._resolve_model` | `def _resolve_model(self, model) -> str`; string/enum then backend translation | `packages/ai-parrot-client-anthropic/src/parrot/clients/anthropic/client.py:269` |
| `DirectBackend.translate_model` | Identity mapping of string identifiers | `packages/ai-parrot-client-anthropic/src/parrot/clients/anthropic/backends.py:86` |
| `AIMessage` | `model: str`, `provider: str`, `usage: CompletionUsage` | `packages/ai-parrot/src/parrot/models/responses.py:98` |
| `AIMessageFactory.from_claude` | Copies raw provider response; sets model from its argument | `packages/ai-parrot/src/parrot/models/responses.py:564` |
| Anthropic fallback evidence | `used_fallback_model`, `original_model`, `fallback_model` metadata | `packages/ai-parrot-client-anthropic/src/parrot/clients/anthropic/client.py:775` |
| `AbstractClient._should_use_fallback` | `def _should_use_fallback(self, model: str, error: Exception) -> bool`; capacity/availability-driven | `packages/ai-parrot/src/parrot/clients/base.py:1155` |
| `PromptInjectionDetector.detect_threats` | `def detect_threats(self, text: str) -> List[Dict[str, Any]]`; nonempty means baseline positive | `packages/ai-parrot/src/parrot/security/prompt_injection.py:138` |
| `build_eval_set` | `def build_eval_set() -> tuple[list[str], list[int], list[str]]`; texts/labels/buckets, no language column | `benchmarks/injection_guardrail_latency/corpus.py:197` |

```python
# verified: packages/ai-parrot-client-anthropic/src/parrot/clients/anthropic/client.py:470
async def ask(
    self,
    prompt: str,
    model: Union[Enum, str] = None,
    max_tokens: Optional[int] = None,
    temperature: Optional[float] = None,
    files: Optional[List[Union[str, Path]]] = None,
    system_prompt: Optional[str] = None,
    history: Optional[Sequence[HistoryMessage]] = None,
    structured_output: Union[type, StructuredOutputConfig, None] = None,
    tools: Optional[List[Dict[str, Any]]] = None,
    use_tools: Optional[bool] = None,
    deep_research: bool = False,
    background: bool = False,
    lazy_loading: bool = False,
    context_1m: bool = False,
) -> AIMessage:
    """Ask Claude a question, optionally with rendered conversation history."""
```

### Integration Points

| New component | Connects to | Via | Verified at |
|---|---|---|---|
| Routing adapter | Agent dispatch | `super().execute_llm_call(client, method, **copied_kwargs)` | `packages/ai-parrot/src/parrot/bots/abstract.py:1215` |
| Runner | Anthropic model override | `model=<unqualified provider ID>` in dispatch kwargs | `packages/ai-parrot-client-anthropic/src/parrot/clients/anthropic/client.py:470` |
| Model evidence | Provider response | `message.raw_response.get('model')` if dict, plus fallback metadata | `packages/ai-parrot/src/parrot/models/responses.py:592` |
| Injection baseline | Regex detector | `bool(detector.detect_threats(case.state))` | `packages/ai-parrot/src/parrot/security/prompt_injection.py:138` |

### Does NOT Exist (Anti-Hallucination)

- No Laya dependency in inspected workspace/root and core manifests; no existing evaluation module
  is assumed. Everything under `artifacts/laya/` in this spec is proposed new work.
- No language field in `build_eval_set()`; no implicit English-filter helper may be assumed.
- No `ClaudeModel.OPUS_5` in the inspected enum; no `opus-5` shorthand translation in the inspected
  direct backend. Preserve user intent without claiming provider availability.
- `parrot/clients/anthropic.py` and `parrot/clients/claude.py` are not current core source modules;
  the client is in `packages/ai-parrot-client-anthropic/src/parrot/clients/anthropic/client.py`.
- `Agent.ask(model=...)` is not a verified per-call routing shortcut through the current kwargs path.
- Framework fallback is not a cost-ranking API. Laya's checkpoint router is not an Anthropic router.
- Typed presence classification does not provide PII spans or redacted content.

## 7. Implementation Notes & Constraints

### Patterns to Follow

Async host I/O, process-isolated CPU inference, Pydantic v2 records, explicit lifecycle ownership,
standard logging, existing AbstractClient dispatch and focused diffs. Never modify
`packages/ai-parrot/src/parrot/clients/base.py` or provider code for this experiment.
Use existing pytest/pytest-asyncio, black and ruff. Secrets are environment-only and never reports.

`artifacts/` is ignored by `.gitignore:279`. During implementation, explicitly stage only the
listed source/config/fixture/README files with targeted force-add; do not force-add the directory.
Keep environments, downloaded models, reports and logs untracked. Commit tests in their normal
distribution paths. Do not modify the root ignore rule or lockfile.

### Known Risks / Gotchas

- CPU performance, dependency compatibility and classifier quality remain unmeasured.
- Confidence may be poorly calibrated; thresholds are experimental settings, not security promises.
- Silent input truncation could invalidate grounded results; verified preflight is mandatory.
- Model aliases and provider availability may change. Validate at execution time; no substitution.
- Provider fallback and retries confound latency/cost; disclose them and separate fallback samples.
- SDK model metadata may repeat the requested model. Require the raw provider response for evidence.
- Small synthetic fixtures establish execution and reveal failure cases, not population accuracy.
- A process timeout must terminate inference, not merely abandon an await on a continuing worker.

### External Dependencies

| Package | Version / policy | Reason |
|---|---|---|
| Pydantic | Existing core pin 2.12.5 (`packages/ai-parrot/pyproject.toml:54`) | Host records |
| ai-parrot-client-anthropic | Existing workspace distribution | Live agent calls |
| Laya | Proposed isolated pin 0.3.5; verify installable distribution against inspected API before locking | CPU decisions |
| torch / transformers / safetensors / huggingface_hub / numpy | Resolve only inside standalone evaluation environment; capture exact versions | Laya runtime dependencies |

No dependency is installed by this spec task. New Laya installation remains an explicit setup
step subject to the repository's dependency-approval rule. Do not modify the workspace's resolver.
The existing core comment at `packages/ai-parrot/pyproject.toml:514` explains its transformer bounds.

External contracts inspected 2026-09-21:

- [Laya runtime](https://raw.githubusercontent.com/NandhaKishorM/laya/main/laya/agent.py):
  `Agent(model_id_or_path, device, token, subfolder)` and synchronous `system_one(state, questions)`;
  `noul` is positive probability. Use an explicit CPU device and local snapshot.
- [Laya router](https://raw.githubusercontent.com/NandhaKishorM/laya/main/laya/router.py):
  `Router.predict(state, questions, model=None, task=None, lang=None)` selects Laya checkpoints.
  The worker uses the explicit English checkpoint; downstream routing is our separate choice question.
- [Package metadata](https://raw.githubusercontent.com/NandhaKishorM/laya/main/pyproject.toml):
  inspected version 0.3.5 with Python >=3.10 and the runtime dependencies above.

Moving upstream URLs document research, not reproducible pins. Record installed distribution
hash and checkpoint revision/hash in each report and reverify runtime contracts during M2.

### Worktree Strategy

**Isolation: per-spec.** Implementation branch `feat/FEAT-589-laya-adoption`, based on `dev`,
in `.claude/worktrees/FEAT-589-laya-adoption`. M1 precedes M2/M3; M4 depends on M1–M3;
M5 completes verification and usage documentation. A single worktree avoids unnecessary coordination
over shared schemas and fixtures. Delegation eligibility does not authorize architectural changes.

For spec creation, the requester explicitly authorized ignoring untracked
`examples/clients/bestbuy_catalog/` and `sdd/state/FEAT-585/` and skipping explicit base-branch sync.
Both remain untouched. The mandatory allocator reserved FEAT-589 with its ledger-only remote
commit and built-in local courtesy fast-forward; only this spec is staged for the spec commit.

## 8. Open Questions

- [x] U1 hardware/languages — requester: “1. CPU, lang: English”. Applied throughout.
- [x] U2 primary preference — requester: “2. routing: anthropic:opus-5 as model for routing with laya”.
  Preserve this requested label; Laya makes the decision and the selected Anthropic model answers.
- [ ] U2 live configuration — requester supplies cheaper model, verified primary API identifier and
  positive logical-call cap via CLI. Until then live evidence is incomplete; no default alternative
  model or paid-call budget is inferred. Follow-up requested during spec preparation.
- [x] U3 success criteria — requester: “3. yes, exploratory report”. No production numerical gates.
- [x] U4 grounded classification — requester: “4. agree.” Refers to document categorization with
  known labels and an insufficient-evidence outcome, as proposed in the preceding clarification.
- [ ] Runtime readiness — implementation owner verifies isolated Laya 0.3.5 compatibility, snapshot
  identity and overflow preflight before M2 completion. No adoption result is presumed.

## 9. Design Research Cross-Check

Independent reviewer status: **skipped** (no independent agent review requested).
The following is the author's cross-check of the accepted proposal and code, not an independent review.

| # | Suggestion / finding | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Request-local dispatch override | CONFIRM | Existing kwargs path omits caller model; super retains budget hook | §2, M3 |
| S2 | Positive noul probability | CONFIRM | Confident negative must remain negative | §2, §4 |
| S3 | Persistent CPU worker | CONFIRM | Synchronous inference must not block the event loop | §2, M2 |
| S4 | Explicit live model pair/cap | CONFIRM | Only primary preference supplied; retain remaining inputs as runtime configuration | §2, §8 |
| S5 | Treat returned model as proof | REJECT | AIMessage factory can echo requested model; use raw response and disclose missing evidence | §2, §6 |

Summary: 4 confirmed, 1 rejected, 0 newly escalated design choices; runtime inputs remain explicit.

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-21 | Codex | Initial review specification incorporating requester decisions and verified contracts |
