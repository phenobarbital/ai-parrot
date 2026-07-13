# TASK-1737: LLM envelope producer with catalog-validate-retry loop

**Feature**: FEAT-273 — A2UI Protocol Integration — Rendering Core (parrot.outputs.a2ui)
**Spec**: sdd/specs/a2ui-implementation.spec.md
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1721, TASK-1724, TASK-1727
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 9 (LLM producer, validate-retry loop) — the D1b half of the
dual-producer design (G2): the LLM produces envelopes only for freeform
display UI, via structured output plus a **catalog-validate-retry loop**.

This module exists precisely because the client layer does NOT retry:
`AbstractClient._parse_structured_output` silently degrades to raw text on
`ValidationError` (verified — see contract). The producer wraps the existing
`ask(...)` + `StructuredOutputConfig` machinery, validates the result against
the catalog allowlist, re-prompts with error context on failure, and — after
the budget is exhausted — degrades to plain text, **never raw passthrough**
(G1 must survive the failure path).

The retry budget number comes from **SPK-3 (TASK-1727)** — its completion note
records measured structured-output validity rates on Claude + Gemini and sets
the budget. TASK-1724 supplies real registered components (Chart/DataTable/Map)
so producer tests validate against a non-trivial catalog.

---

## Scope

- Implement `packages/ai-parrot/src/parrot/outputs/a2ui/producer.py` with the
  spec §2 public interface:
  - `async def generate_envelope(client, prompt, *, catalog, max_attempts) -> CreateSurface`
  - Call path: `client.ask(prompt, ..., structured_output=StructuredOutputConfig(output_type=CreateSurface))`
    through the EXISTING client machinery — no new client methods.
  - On catalog-validation failure (unknown component, schema violation,
    `requires_actions` component present): re-prompt the client with the
    structured error context appended (validation error list + offending
    fragment), bounded by `max_attempts`.
  - Default `max_attempts` from the SPK-3 budget recorded in TASK-1727's
    completion note (fallback default of 2 — mirroring
    `OutputRetryConfig.max_retries` — if SPK-3's number is absent; record
    which was used).
  - Final failure → **plain-text degradation** (a typed result carrying the
    text and the failure reason), never the raw invalid payload (G1).
  - **Display-only enforcement (D10b)**: any component with
    `requires_actions=True` in an LLM-produced envelope is a validation
    failure — rejected via the catalog's LLM-context validation from
    TASK-1721 (do not re-implement the walk if TASK-1721 exposes it; call it).
  - Compose the producer prompt from the catalog's embedded per-component
    `instructions` (the reason components carry them).
- Write unit tests with a **mock/fake client** (no real LLM calls):
  `test_producer_retry_bounded_then_degrades`,
  `test_llm_envelope_rejects_requires_actions` (spec §4 rows for Modules 9/2).

**NOT in scope**:
- SPK-3 itself (TASK-1727) — this task consumes its budget number.
- Catalog validation internals / `requires_actions` walk (TASK-1721) — the
  producer *invokes* validation, it does not own it.
- `CreateSurface`/message models and serialization (Module 1).
- Renderers, baking, delivery, deep links (Modules 5-8).
- Wiring into `OutputMode.A2UI` / bots / handlers (Module 10) and tool
  builders (Module 11).
- Any interactive/`action` production — FEAT-B.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/a2ui/producer.py` | CREATE | `generate_envelope` + retry loop + plain-text degradation result |
| `packages/ai-parrot/tests/outputs/a2ui/test_producer.py` | CREATE | Bounded-retry, degradation, and requires_actions-rejection tests (mock client) |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports

```python
from parrot.models.outputs import StructuredOutputConfig  # verified: packages/ai-parrot/src/parrot/models/outputs.py:72
```

`CreateSurface` and the catalog validation entry point come from Module 1 /
TASK-1721 (`parrot.outputs.a2ui.models`, `parrot.outputs.a2ui.catalog`);
verify exact import paths against their committed code before writing any.

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/clients/base.py:244 — class AbstractClient(EventEmitterMixin, ABC)
# ask() verified at :1526 (signature copied verbatim, spec §6 anchor):
async def ask(
    self,
    prompt: str,
    model: str,
    max_tokens: int = 4096,
    temperature: float = 0.7,
    files: Optional[List[Union[str, Path]]] = None,
    system_prompt: Optional[str] = None,
    structured_output: Union[type, StructuredOutputConfig, None] = None,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    tools: Optional[List[Dict[str, Any]]] = None,
    use_tools: Optional[bool] = None,
    deep_research: bool = False,
    background: bool = False,
    lazy_loading: bool = False,
) -> MessageResponse: ...
# also available: async def ask_stream (:1564), async def invoke — do NOT invent others
# _get_structured_config (:1473) · _parse_structured_output (:2116) —
#   degrades to RAW TEXT on ValidationError, anchor :2183:
#   f"Fallback parsing failed: {e}. Payload start: {json_text[:50]!r}"

# packages/ai-parrot/src/parrot/models/outputs.py:72
@dataclass
class StructuredOutputConfig:
    output_type: type
    format: OutputFormat = OutputFormat.JSON
    custom_parser: Optional[Callable[[str], Any]] = None
    # methods: get_schema(), format_schema_instruction()

# packages/ai-parrot/src/parrot/outputs/formatter.py — RETRY-LOOP PRECEDENT (pattern, not dependency)
DEFAULT_RETRY_PROMPTS = {...}          # :49 — per-mode repair-prompt templates with
                                       #   {original_output} / {error_message} slots
class OutputRetryConfig:               # :20 — max_retries: int = 2 (:35)
class OutputRetryResult:               # :110
class OutputFormatter:                 # :129
    async def format_with_retry(       # :608
        self, mode: OutputMode, data: Any, original_prompt: Optional[str] = None,
        llm_client: Optional["AbstractClient"] = None,
        retry_config: Optional[OutputRetryConfig] = None, **kwargs
    ) -> OutputRetryResult
    # budget check anchor :698: `if retry_count >= config.max_retries:`

# Spec §2 target interface (parrot/outputs/a2ui/producer.py):
async def generate_envelope(client, prompt, *, catalog, max_attempts: int) -> CreateSurface: ...
```

### Does NOT Exist

- ~~`AbstractClient.completion()`~~ — no such method; the surface is
  `ask`/`ask_stream`/`invoke`.
- ~~`response_model` parameter~~ / ~~public `response_format` parameter~~ —
  structured output goes ONLY through `structured_output=` (type or
  `StructuredOutputConfig`).
- ~~Client-level structured-output validate-retry loop~~ —
  `_parse_structured_output` (:2116) silently degrades to raw text with NO
  re-prompt; that gap is exactly why this module exists.
- ~~`parrot.outputs.a2ui.producer`~~ — created by this task.
- ~~`ActionRouter` / action dispatch~~ — FEAT-B; this producer is display-only.
- ~~`OutputMode.A2UI`~~ on `dev` today — added by Module 10, not needed here.
- ~~`exec()`/`eval()` under `parrot/outputs/a2ui*`~~ — G1 invariant; the
  degradation path returns text, never executes or passes through raw output.

---

## Implementation Notes

### Pattern to Follow

Lift the retry-loop shape from the existing formatter (quoting EXISTING code —
spec §7 "Retry-loop shape from `OutputFormatter.format_with_retry` /
`DEFAULT_RETRY_PROMPTS`, lifted to catalog-validation errors"):

```python
# packages/ai-parrot/src/parrot/outputs/formatter.py:49 — EXISTING repair-prompt shape
DEFAULT_RETRY_PROMPTS = {
    OutputMode.ECHARTS: """You are a JSON repair assistant. ...
**Original Output (with error):**
```
{original_output}
```
**Error encountered:**
{error_message}
...""",
}
# and the bound check at formatter.py:698:
#     if retry_count >= config.max_retries:
#         ... f"Max retries ({config.max_retries}) exceeded for {mode}"
```

Adapt: the producer's repair prompt carries the *catalog validation errors*
(unknown component names, schema violations, `requires_actions` hits) plus the
offending envelope fragment, and re-invokes `client.ask(...)` with the same
`structured_output` config. Do NOT import the legacy formatter — copy the
shape, not the module (one-way import rule G8: core a2ui never imports agents,
DatasetManager, or LLM clients at module level — the client arrives as a call
argument, so `client` must be typed loosely / via `TYPE_CHECKING`).

### Key Constraints

- Bounded loop: attempts ≤ `max_attempts`; each retry logs the validation
  errors via `self.logger`/module logger (no prints).
- **Never raw passthrough**: on final failure the caller receives plain text
  (e.g. the model's textual answer or an apologetic summary) plus a machine-
  readable failure reason — the invalid envelope itself must not escape.
- `requires_actions` rejection happens on EVERY attempt (it is a validation
  failure like any other, re-prompted with "component X is not allowed for
  LLM-produced envelopes").
- Read TASK-1727's completion note for the SPK-3 retry budget; wire it as the
  documented default of `max_attempts` and cite the number in the docstring.
- `MessageResponse` handling: remember `_parse_structured_output` may have
  degraded to raw text — treat a non-`CreateSurface` payload as attempt
  failure (parse-level), feeding the retry loop the same way schema failures do.
- Async throughout; Pydantic v2 for the degradation result model; Google-style
  docstrings; strict type hints.
- Tests use a fake client whose `ask()` returns scripted responses (invalid →
  invalid → valid, invalid × N, requires_actions envelope) so retry counting
  and degradation are asserted without network.

### References in Codebase

- `packages/ai-parrot/src/parrot/outputs/formatter.py:49/:608/:698` — retry precedent.
- `packages/ai-parrot/src/parrot/clients/base.py:1526/:2116/:2183` — client surface + degradation gap.
- Spec §4 rows `test_producer_retry_bounded_then_degrades`, `test_llm_envelope_rejects_requires_actions`; §7 risk "Invalid LLM envelope".
- TASK-1727 completion note — SPK-3 fidelity numbers → retry budget.

---

## Acceptance Criteria

- [ ] `generate_envelope(client, prompt, *, catalog, max_attempts)` implemented per spec §2, using `client.ask` + `StructuredOutputConfig(output_type=CreateSurface)` only.
- [ ] Catalog-validation failure re-prompts with error context; total attempts never exceed `max_attempts` (default sourced from SPK-3 / TASK-1727, fallback documented).
- [ ] Final failure degrades to plain text with failure reason — the invalid envelope is never returned or embedded (G1 on the failure path).
- [ ] Envelopes containing any `requires_actions=True` component are rejected (display-only v1, D10b).
- [ ] All tests pass: `pytest packages/ai-parrot/tests/outputs/a2ui/test_producer.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/outputs/a2ui/producer.py`
- [ ] No module-level import of LLM clients/agents/DatasetManager in `producer.py` (G8 one-way rule); `grep -rn "exec(\|eval(" packages/ai-parrot/src/parrot/outputs/a2ui/` returns nothing.

---

## Test Specification

> Minimal test scaffold (names + one-line docstrings). The agent must make these pass.

```python
# packages/ai-parrot/tests/outputs/a2ui/test_producer.py

class TestGenerateEnvelope:
    async def test_valid_envelope_first_attempt(self):
        """A catalog-valid CreateSurface from the fake client is returned with a single ask() call."""

    async def test_retry_reprompts_with_error_context(self):
        """After an invalid envelope, the second ask() prompt contains the validation error text."""

    async def test_producer_retry_bounded_then_degrades(self):
        """Persistent validation failures re-prompt at most max_attempts times, then return plain-text degradation, never the raw invalid payload."""

    async def test_llm_envelope_rejects_requires_actions(self):
        """An envelope containing a requires_actions component (Form) fails validation and is retried/degraded, never returned."""

    async def test_raw_text_fallback_counts_as_failed_attempt(self):
        """A client response that degraded to raw text (no CreateSurface) consumes one attempt and triggers re-prompt."""
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - Confirm TASK-1721's catalog validation entry point and TASK-1727's recorded retry budget
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in the per-spec index → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-1737-llm-producer-retry.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-11
**Retry budget wired**: `DEFAULT_MAX_ATTEMPTS = 3` (1 initial + 2 catalog-validate
retries) — the SPK-3 (TASK-1727) recommendation. SPK-3 could not measure live validity
in this environment (model 404s), so the number is grounded in the `OutputFormatter`
`max_retries=2` precedent and documented in `producer.py`.

**Notes**: Created `parrot/outputs/a2ui/producer.py` — `generate_envelope(client, prompt,
*, catalog, max_attempts, model, system_prompt) -> ProducerResult`. Uses the EXISTING
`client.ask(..., structured_output=StructuredOutputConfig(output_type=CreateSurface))`
path (no new client methods, client passed as arg — no module-level client import, G8).
Loop: extract envelope (CreateSurface instance / dict-via-serialization-layer /
raw-text→failure) → `validate_envelope(origin=LLM)` (rejects unknown + `requires_actions`
components, D10b) → on failure build a repair prompt carrying the validation errors +
rejected fragment and re-ask, bounded by `max_attempts`. On exhaustion returns a
`ProducerResult` with `degraded=True` + plain-text (`text`) + `failure_reason` — the
invalid envelope is NEVER returned (G1 on the failure path). Composes the producer system
prompt from `catalog_instructions()`. 7 tests pass (first-attempt success, retry-with-error
-context, bounded-then-degrade, requires_actions rejection, raw-text-counts-as-attempt,
dict-output, budget=3). Full a2ui core suite: 100 passed / 4 skipped; ruff clean; no
exec/eval; no module-level LLM/agent import.

**Deviations from spec**: spec §2 sketches the signature as `-> CreateSurface`, but the
degradation path cannot return a `CreateSurface`; I return a typed `ProducerResult`
wrapper (envelope | plain-text + reason) exactly as the task body requires ("a typed
result carrying the text and the failure reason"). The `catalog` param is accepted but
reserved (the global catalog registry is used today) — documented in the docstring.
