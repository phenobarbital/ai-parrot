---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Brainstorm: LocalLLM Image Understanding

**Date**: 2026-09-18
**Author**: Jesus Lara and Codex
**Status**: exploration
**Recommended Option**: A

---

## Problem Statement

`LocalLLMClient` has no public `ask_to_image()` method. Applications needing local
vision inference must assemble provider-shaped messages themselves. Planogram
compliance is the first consumer, but the missing capability belongs in the general
client API: ask a question about multiple images and obtain a validated structured
answer from llama-server through its OpenAI-compatible interface.

The name means image understanding, not image generation. Current source inherits
`OpenAIBaseClient`, which supplies image encoding but no public vision operation.
The older `localllm-client.spec.md:42` inheritance description is stale; it must not
be used as evidence that local vision already works.

## Constraints & Requirements

### Confirmed in Q&A round 1

- Flow: `feature`, based on `dev`.
- Add image understanding through `LocalLLMClient.ask_to_image()`.
- First backend: llama-server, using its OpenAI-compatible endpoint.
- Multiple images and structured outputs are required.
- API is general purpose; planogram compliance is its first consumer.

### Engineering constraints

- Remain within the `AbstractClient` hierarchy; consumers must not call SDKs directly.
- Preserve configured local endpoint/model/authentication and memory ownership.
- Do not modify `clients/base.py` or change existing text APIs for this feature.
- Preserve image ordering; no image may disappear on retries or concurrent calls.
- Structured results must validate against the requested Pydantic model; malformed
  or truncated output must not masquerade as successful structured data.
- Use existing dependencies; no dependency additions are approved by this brainstorm.
- Keep I/O asynchronous and avoid CPU-heavy image encoding on the event loop.
- Backend compatibility depends on the deployed vision model and server build;
  broad Ollama/vLLM certification is outside the initial acceptance scope.

### Q&A round 2: proposals awaiting user answers

1. Mirror the existing primary `image` plus `reference_images` inputs, including
   `Path`, `bytes`, and optionally `PIL.Image.Image`, or adopt one `images` list?
2. On schema rejection, fail explicitly or retry with schema instructions and
   validate the result? Recommendation: fail explicitly in v1.
3. Include plain-text results, caller-supplied history/system prompt, and defer
   streaming/tool use? Recommendation: yes.

These are proposed defaults, not recorded user approvals. The description below
uses them to make the options concrete; resolve them before formalizing the API.

---

## Options Explored

### Option A: Add a focused LocalLLM vision method

Implement the public operation within the local client satellite. Assemble one
multimodal user turn and use inherited lifecycle, completion transport, schema,
and response primitives where their semantics match the new contract.

**Pros:**

- Directly serves the requested client and first consumer.
- Keeps provider-specific defaults out of local requests.
- Small public surface and limited regression scope.

**Cons:**

- Some orchestration overlaps the OpenAI provider's vision method.
- Existing helpers need careful treatment: synchronous encoding, MIME handling,
  permissive parsing, telemetry, and budget accounting cannot be copied blindly.

**Effort:** Medium.

**Libraries / Tools:**

| Package | Purpose | Verified availability |
|---|---|---|
| `ai-parrot` | Base client, responses, history | Local package dependency at `packages/ai-parrot-client-local/pyproject.toml:16` |
| `openai` | Existing compatible transport inside client hierarchy | Core dependency at `packages/ai-parrot/pyproject.toml:70` |
| `pydantic` | Schema generation and response validation | Core dependency at `packages/ai-parrot/pyproject.toml:54` |
| Python standard library | Byte encoding and bounded process-based work if required | No new distribution |

**Existing Code to Reuse:**

- `packages/ai-parrot-client-local/src/parrot/clients/local/client.py:91` — endpoint-configured client creation.
- `packages/ai-parrot/src/parrot/clients/openai_base.py:228` — completion funnel.
- `packages/ai-parrot/src/parrot/models/responses.py:405` — response factory.
- `packages/ai-parrot/src/parrot/clients/openai_base.py:1137` — encoding contract; reuse subject to async/MIME audit.

### Option B: Promote a generic vision operation into OpenAIBaseClient

Create a shared OpenAI-compatible vision operation and have local/provider clients
adapt it. Keep OpenAI-only model defaults and behavior in the OpenAI satellite.

**Pros:**

- Centralizes request/response shaping for compatible clients.
- Offers a path to remove duplicated provider vision implementations.

**Cons:**

- Broadens the change to shared core used by several satellites.
- An inherited method does not establish that every backend/model supports vision.
- Provider migration and regression coverage exceed the immediate local-client need.

**Effort:** High.

**Libraries / Tools:** Existing `openai` and `pydantic` dependencies cited in Option A;
no additional library required. Pillow remains conditional as documented below.

**Existing Code to Reuse:**

- `packages/ai-parrot/src/parrot/clients/openai_base.py:737` — existing completion orchestration and accounting pattern.
- `packages/ai-parrot-client-openai/src/parrot/clients/openai/client.py:1468` — provider vision signature and behavior to audit before migration.
- `packages/ai-parrot-client-local/src/parrot/clients/local/client.py:27` — inheritance seam.

### Option C: Request-scoped multimodal adapter over the existing ask pipeline

Less obvious approach: prepare image content in `ask_to_image()` and carry it in
request-local state to a narrowly overridden message-builder, then delegate to the
existing `ask()` pipeline. No instance-wide image state or monkey-patching.

**Pros:**

- Reuses the established text pipeline's transport, telemetry, and budgeting.
- Could establish a future path for multimodal `ask()` without duplicating orchestration.

**Cons:**

- Introduces hidden request context between public call and message construction.
- Existing parsing permits raw-text fallback, requiring explicit validation afterward.
- Subclass dispatch, nested requests, and context cleanup require extra tests.
- The current `ask()` signature does not accept image content directly.

**Effort:** Medium, with greater coupling than A.

**Libraries / Tools:** Python `contextvars` plus the verified dependencies in Option A.
No new library; the existing vLLM context pattern demonstrates task-local request options.

**Existing Code to Reuse:**

- `packages/ai-parrot/src/parrot/clients/base.py:1724` — message-builder override seam; read-only base.
- `packages/ai-parrot/src/parrot/clients/openai_base.py:737` — inherited `ask()` pipeline.
- `packages/ai-parrot-client-vllm/src/parrot/clients/vllm/client.py:36` — existing request-local `ContextVar` pattern.

---

## Recommendation

**Option A** best matches the confirmed scope. A dedicated local operation gives
callers a clear API without a cross-provider migration. Reuse the completion funnel
and response models, but keep local image ordering and strict structured validation
explicit. The cost is maintaining a small vision orchestration path.

During specification, audit budget and telemetry requirements before choosing the
exact internal seam. If direct orchestration cannot preserve those contracts without
substantial duplication, reconsider Option C. Do not silently expand into Option B.

## Feature Description

### User-Facing Behavior

Proposed contract: a prompt, primary image, and ordered reference images; optional
Pydantic output model, model override, max tokens, temperature, system prompt, and
already-rendered history. Return the existing `AIMessage` type with text or a validated
Pydantic object, accurate local provider/model attribution, and available usage.

The default model remains caller configuration; no cloud vision model or automatic
model download is introduced. A planogram caller supplies its own prompt and schema.
Catalogs, crops, scoring, caching, and planogram interpretation stay in the consumer.

Plain-text mode omits `response_format`. Structured mode requests JSON-schema output
and validates locally. A successful two-image comparison returning the requested
Pydantic object is the primary acceptance scenario.

### Internal Behavior

1. Resolve the configured model and initialize the client through the existing lifecycle.
2. Validate and encode supported inputs, preserving primary/reference ordering.
   Use image content blocks, not a file-upload endpoint.
3. Compose independent messages from the optional history and system prompt,
   appending exactly one current multimodal user turn without mutating caller data.
4. Send through the inherited completion funnel, preserving its subclass hooks.
   Specify how budget scope, retry accounting, cancellation, and telemetry apply.
5. Check response shape and finish reason before parsing. Validate structured output;
   convert to `AIMessage` and set provider from the actual client identity.
6. Persist no conversation history; the owning bot remains the writer.

### Edge Cases & Error Handling

- Missing files, empty/corrupt bytes, unsupported types and media: actionable errors
  before sending where detectable; do not relabel arbitrary bytes as JPEG.
- Input count/size limits: define a configurable policy before implementation; never
  silently drop, reorder, crop, or downscale images to fit a budget.
- Unsupported vision model/projector or schema: preserve useful server errors.
  Proposed v1 behavior is explicit failure without downgrading the request.
- If prompt-schema fallback is selected, it must preserve every image, consume the
  same request budget, and still validate output. Existing text-only invoke fallback
  is unsuitable unchanged.
- Invalid JSON, schema mismatch, empty choices, absent content and truncated output:
  fail explicitly for structured mode. Missing usage must not crash valid responses.
- Preserve `temperature=0`; do not use truthiness to select defaults.
- Concurrent calls use independent messages, model overrides and schemas.
- No image/base64 payloads in routine logs or persistent memory added by this method.

### Validation to carry into the specification

Mocked transport tests should assert image order and prompt count, local endpoint/model,
plain-text versus schema request shape, successful Pydantic validation, malformed and
truncated output failures, zero temperature, missing usage, concurrency isolation,
and error behavior. Add lifecycle, budget/telemetry, and text-call regression checks
appropriate to the implementation seam.

An opt-in integration check must use a recorded llama-server build and vision model,
two small images, and a Pydantic schema. It should establish protocol compatibility,
not claim planogram recognition accuracy. No live server was tested for this brainstorm.

---

## Capabilities

### New Capabilities

- `localllm-ask-to-image`: multiple-image understanding with validated structured output.

### Modified Capabilities

- `localllm-client`: extend its public API; preserve existing text calls and configuration.

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `packages/ai-parrot-client-local/src/parrot/clients/local/client.py` | extends | Public vision method and local orchestration |
| `packages/ai-parrot-client-local/tests/` | extends | Focused transport/contract tests |
| `packages/ai-parrot-client-local/README.md` | extends | Usage and deployment prerequisites |
| Core encoding/completion/response helpers | depends on | Audit semantics; proposed Option A avoids base changes |
| `vLLMClient` | inherits | Inherits new local method; do not claim tested vLLM compatibility |
| Planogram FEAT-565 / TASK-3342 | downstream consumer | Coordinate adoption; adapter edits outside this feature |
| Dependency declarations | unresolved | Pillow is not directly declared by local/core; see below |

No new HTTP handler, UI, tool, factory alias, or local inference runtime is needed.

## Code Context

Research baseline: `dev` at `effd29003`. Wiki query and page reads preceded source
inspection; all references below were checked in source. Source changes after this
baseline require line/signature revalidation during specification.

### User-Provided Code

No code snippets were supplied. User requirements, preserved verbatim:

> 1. feature from dev 2. yes 3. llama-server using OpenAI-compatible 4. multiples images and structured outputs 5. general client use but first consumer is planogram compliance

### Verified Codebase References

#### Classes & Signatures

| Symbol | Verified signature/contract | Source |
|---|---|---|
| `LocalLLMClient` | `class LocalLLMClient(OpenAIBaseClient)` | `packages/ai-parrot-client-local/src/parrot/clients/local/client.py:27` |
| `LocalLLMClient.get_client` | `async def get_client(self) -> "AsyncOpenAI"` | Same file, line 91 |
| `LocalLLMClient.ask` | `async def ask(self, prompt: str, model: Union[str, LocalLLMModel] = None, **kwargs)` | Same file, line 117 |
| `OpenAIClient.ask_to_image` | `prompt`, `image`, `reference_images`, `model`, `max_tokens`, `temperature`, `structured_output`, `history`, `no_memory`, `low_quality`; returns `AIMessage` | `packages/ai-parrot-client-openai/src/parrot/clients/openai/client.py:1468` |
| `OpenAIBaseClient._encode_image_for_openai` | `(self, image: Path \| bytes \| Image.Image, low_quality: bool = False) -> dict[str, Any]` | `packages/ai-parrot/src/parrot/clients/openai_base.py:1137` |
| `OpenAIBaseClient._chat_completion` | `async def _chat_completion(self, model: str, messages: Any, use_tools: bool = False, stream: bool = False, **kwargs) -> Any` | Same file, line 228 |
| `AbstractClient._ensure_client` | `async def _ensure_client(self, **hints: Any) -> Any` | `packages/ai-parrot/src/parrot/clients/base.py:964` |
| `AIMessageFactory.from_openai` | `(response, input_text, model, user_id=None, session_id=None, turn_id=None, structured_output=None) -> AIMessage` | `packages/ai-parrot/src/parrot/models/responses.py:405` |

#### Verified Imports

Static source verification, not a runtime import smoke test:

- `from parrot.clients.local import LocalLLMClient` — export at `packages/ai-parrot-client-local/src/parrot/clients/local/__init__.py:1`.
- `from parrot.clients.openai_base import OpenAIBaseClient` — equivalent relative import used at `packages/ai-parrot-client-local/src/parrot/clients/local/client.py:15`.
- `from parrot.models.responses import AIMessage, AIMessageFactory` — definitions at `packages/ai-parrot/src/parrot/models/responses.py:75` and `:369`.
- `from parrot.memory.render import HistoryMessage` — equivalent relative import at `packages/ai-parrot/src/parrot/clients/openai_base.py:52`.
- `from parrot.models import StructuredOutputConfig` — existing relative import at `packages/ai-parrot-client-local/src/parrot/clients/local/client.py:20`.

#### Key Attributes, Dependencies, and Reuse Hazards

- Local provider keys are `local`, `localllm`, `ollama`, `llamacpp`; default model
  is `llama3.1:8b` (`local/client.py:62`). Defaults do not establish vision capability.
- Local `get_client()` uses `LOCAL_LLM_TIMEOUT`, default 120, and configured `base_url`
  (`local/client.py:106`). Preserve these settings.
- `vLLMClient` inherits `LocalLLMClient` at
  `packages/ai-parrot-client-vllm/src/parrot/clients/vllm/client.py:53`.
- Encoder opens paths synchronously, labels raw bytes JPEG, and imports Pillow even
  for byte/path inputs (`openai_base.py:1152`). It is not automatically safe to reuse
  unchanged for asynchronous, format-correct input handling.
- Pillow is explicitly declared in the embeddings `multimodal` extra
  (`packages/ai-parrot-embeddings/pyproject.toml:94`), not directly in local/core base
  dependencies. Existing optional availability is not a clean-install guarantee.
  Decide dependency ownership before promising PIL input; do not introduce it silently.
- OpenAI vision prepends each reference (`openai/client.py:1499`), defaults plain calls
  to JSON (`:1526`), and can swallow validation errors (`:1540`). Do not copy these semantics.
- Shared parsing can return raw text (`clients/base.py:2548`); strict structured
  success requires an additional check or explicit Pydantic validation.
- `AIMessageFactory.from_openai()` sets provider to `openai`
  (`models/responses.py:442`); local attribution must be corrected.
- Local schema fallback recreates text-only messages (`local/client.py:338`);
  reusing it as-is would discard images.
- `_chat_completion()` integrates a budget scope when configured and otherwise
  retries selected SDK errors (`openai_base.py:262`). Audit how a new public operation
  supplies the expected accounting context; do not claim parity from transport reuse alone.

### Does NOT Exist (Anti-Hallucination)

- `LocalLLMClient.ask_to_image` and `LocalLLMClient.image_understanding`: absent in
  searches of the local satellite and its shared bases.
- `OpenAIBaseClient.ask_to_image` / `AbstractClient.ask_to_image`: absent.
- An `images` argument on inherited `ask()`: absent from its signature
  (`openai_base.py:737`); `files` is not a verified equivalent.
- The proposed planogram `examples/planogram/plancheck/vision.py` is not present in
  this checkout. TASK-3342 is pending in `sdd/tasks/index/new-planogram-compliance-algo.json:152`.

### External Backend Evidence

The upstream [llama-server README](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md)
documents multimodal OpenAI-compatible chat input and schema-constrained JSON.
Its [grammar documentation](https://github.com/ggml-org/llama.cpp/blob/master/grammars/README.md)
describes a supported subset of JSON Schema. These sources were checked on 2026-09-18;
they support the protocol choice, not compatibility with an unspecified installed
build/model. Pin both in the integration evidence.

## Parallelism Assessment

- **Internal parallelism**: implementation and contract tests are closely coupled;
  documentation and opt-in integration fixtures can follow the agreed API independently.
- **Cross-feature independence**: Option A avoids the broad shared-client changes of B.
  FEAT-565's pending vision adapter is a consumer coordination point, not a reason
  to include planogram code in this feature. Recheck active changes when creating tasks.
- **Recommended isolation**: per-spec.
- **Rationale**: one local-client worktree keeps contract changes and tests coherent;
  no internal worktree split is justified for this scope.

## Open Questions

- [x] Flow metadata? — *Owner: Jesus Lara*: feature from dev.
- [x] Image generation or understanding? — *Owner: Jesus Lara*: image understanding.
- [x] First backend? — *Owner: Jesus Lara*: llama-server through its OpenAI-compatible API.
- [x] Required capabilities and consumer? — *Owner: Jesus Lara*: multiple images and structured outputs; general client use, planogram compliance first.
- [ ] Primary image plus references, or a single list; which input types? — *Owner: Jesus Lara*: round 2 asks; recommend primary plus ordered references, subject to Pillow ownership.
- [ ] Fail on schema rejection, or validated prompt-schema fallback? — *Owner: Jesus Lara*: round 2 asks; recommend explicit failure in v1.
- [ ] Plain text/history/system prompt in scope; streaming/tools deferred? — *Owner: Jesus Lara*: round 2 asks; recommend yes.
- [ ] Which llama-server build, vision model and projector establish compatibility? — *Owner: Jesus Lara*: record these with integration evidence.
- [ ] How to handle async image preparation, Pillow availability, and request limits without unapproved dependencies? — *Owner: spec author*: audit existing facilities; choose and document limits and dependency ownership.
- [ ] Which completion seam preserves budgeting, telemetry and strict validation with minimal duplication? — *Owner: spec author*: audit Option A before fixing the task boundaries; reconsider C if necessary.
