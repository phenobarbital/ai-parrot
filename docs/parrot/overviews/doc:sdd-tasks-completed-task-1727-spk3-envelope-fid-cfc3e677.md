---
type: Wiki Overview
title: 'TASK-1727: SPK-3: LLM envelope fidelity spike (Claude + Gemini)'
id: doc:sdd-tasks-completed-task-1727-spk3-envelope-fidelity-spike-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements **Module 0b** of the spec (§3, "SPK-3 LLM envelope fidelity spike").
  Before the LLM producer (Module 9, TASK-1737) hardens its catalog-validate-retry
  loop, we need a measured structured-output validity rate for `CreateSurface` envelopes
  generated against the registered
relates_to:
- concept: mod:parrot.clients.claude
  rel: mentions
- concept: mod:parrot.clients.google.client
  rel: mentions
- concept: mod:parrot.models.outputs
  rel: mentions
- concept: mod:parrot.outputs.a2ui
  rel: mentions
- concept: mod:parrot.outputs.a2ui.models
  rel: mentions
- concept: mod:parrot.outputs.a2ui.producer
  rel: mentions
---

# TASK-1727: SPK-3: LLM envelope fidelity spike (Claude + Gemini)

**Feature**: FEAT-273 — A2UI Protocol Integration — Rendering Core (parrot.outputs.a2ui)
**Spec**: sdd/specs/a2ui-implementation.spec.md
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1721, TASK-1724
**Assigned-to**: unassigned

---

## Context

Implements **Module 0b** of the spec (§3, "SPK-3 LLM envelope fidelity spike"). Before the LLM producer (Module 9, TASK-1737) hardens its catalog-validate-retry loop, we need a measured structured-output validity rate for `CreateSurface` envelopes generated against the registered catalog with its embedded `instructions`, on both Claude and Gemini. The spike's single most important output is the **retry-budget number** that Module 9 will use. Spike gates were waived and embedded as early tasks (spec §8); this code is throwaway and never shipped.

---

## Scope

- Write a throwaway spike harness under `artifacts/spikes/spk3-envelope-fidelity/` that:
  - Builds the catalog context from the components registered so far (TASK-1721 registry + at least the Chart/DataTable/Map components from TASK-1724), including their embedded `instructions` strings.
  - Runs **N ≥ 20 diverse display-UI prompts** (dashboards, comparisons, KPI summaries, tabular reports, map views…) against BOTH clients: `AnthropicClient` (`parrot/clients/claude.py:67`) and `GoogleGenAIClient` (`parrot/clients/google/client.py:95`).
  - Uses the EXISTING structured-output path — `await client.ask(prompt, model=..., structured_output=StructuredOutputConfig(output_type=CreateSurface))` per the verified `AbstractClient.ask` signature (spec §6). **NO client code changes.**
  - Classifies each response: (a) parsed into `CreateSurface` at all, (b) passed catalog allowlist validation, (c) failure taxonomy for the rest (raw-text degradation, schema violation, unknown component, `requires_actions` component, malformed binding, other).
- Compute and record per-client **validity %** (first-shot), the failure taxonomy histogram, and — from the failure distribution — a recommended **retry-budget number for TASK-1737** (Module 9) with a one-paragraph rationale.
- Write evidence to `artifacts/spikes/spk3-envelope-fidelity/`: prompt set, raw per-run results (JSONL), `results.md` with the numbers and the retry-budget recommendation.
- Update spec §8: check off "SPK-3 outcome — retry budget number for Module 9" with the number, and record the same in this task's Completion Note.

**NOT in scope**:
- ANY change to `parrot/clients/` — `_parse_structured_output` degrades to raw text by design today (spec §6); the spike measures that behavior, it does not fix it.
- The Module 9 producer / retry loop itself (TASK-1737) — it consumes this number.
- Shipping spike code into `packages/*/src/`; adding tests to the package suites.
- Fine-tuning prompts to game the number — the prompt set must stay representative.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `artifacts/spikes/spk3-envelope-fidelity/prompts.json` | CREATE | N ≥ 20 diverse display-UI prompts |
| `artifacts/spikes/spk3-envelope-fidelity/spike_fidelity.py` | CREATE | Throwaway harness: prompts × {Claude, Gemini} → structured output → catalog validation → classification |
| `artifacts/spikes/spk3-envelope-fidelity/runs.jsonl` | CREATE | Raw per-run results (client, prompt id, outcome class, error detail) |
| `artifacts/spikes/spk3-envelope-fidelity/results.md` | CREATE | Validity % per client, failure taxonomy, retry-budget recommendation for TASK-1737 |
| `sdd/specs/a2ui-implementation.spec.md` | MODIFY | Check the §8 SPK-3 checkbox with the retry-budget number |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
from parrot.models.outputs import OutputMode, StructuredOutputConfig  # models/outputs.py:36/:72
from parrot.clients.claude import AnthropicClient        # clients/claude.py:67
from parrot.clients.google.client import GoogleGenAIClient  # clients/google/client.py:95
from parrot.outputs.a2ui.models import CreateSurface     # created by TASK-1720 — verify exact export names before use
# catalog validation entry point — created by TASK-1721; verify its exact name in
# parrot/outputs/a2ui/catalog/__init__.py before use
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/clients/base.py:1526 — AbstractClient.ask (verified):
async def ask(self, prompt: str, model: str, max_tokens: int = 4096,
    temperature: float = 0.7, files: Optional[List[Union[str, Path]]] = None,
    system_prompt: Optional[str] = None,
    structured_output: Union[type, StructuredOutputConfig, None] = None,
    user_id: Optional[str] = None, session_id: Optional[str] = None,
    tools: Optional[List[Dict[str, Any]]] = None, use_tools: Optional[bool] = None,
    deep_research: bool = False, background: bool = False,
    lazy_loading: bool = False) -> MessageResponse

# packages/ai-parrot/src/parrot/models/outputs.py:72 — StructuredOutputConfig:
class StructuredOutputConfig:
    output_type: type
    # methods: get_schema() (:78), format_schema_instruction() (:171)

# clients/base.py:1473 `def _get_structured_config` — normalizes type vs config.
# clients/base.py:2183 anchor `f"Fallback parsing failed: {e}. Payload start: ..."`
# → structured-output parse failure DEGRADES TO RAW TEXT at client level; the
#   spike must detect "response is not a CreateSurface" as a failure class,
#   not expect an exception.
```

### Does NOT Exist
- ~~`AbstractClient.completion()`~~, ~~`response_model`~~, ~~public `response_format` param~~ — the surface is `ask`/`ask_stream`/`invoke` with `structured_output` (spec §6).
- ~~Client-level structured-output validate-retry loop~~ — nothing re-prompts on ValidationError today; Module 9 builds that loop USING this spike's budget.
- ~~`parrot.outputs.a2ui.producer` / `generate_envelope`~~ — Module 9 (TASK-1737) creates it.
- ~~A registered full nine-component catalog~~ — only the components landed by TASK-1721/TASK-1724 (Chart, DataTable, Map at minimum) are available; the spike runs against whatever is registered and records which.

### Environment Notes
- Requires live API credentials for Anthropic + Google GenAI from the environment (never hardcode keys). If one provider's credentials are unavailable, run the other, mark the gap prominently in `results.md`, and do NOT fabricate numbers.
- `source .venv/bin/activate` before any run.

---

## Implementation Notes

### Pattern to Follow
Structured-output invocation exactly as the verified signature: `structured_output=StructuredOutputConfig(output_type=CreateSurface)` through `client.ask(...)` — the same path Module 9 will productize (spec §6 integration row "Module 9 producer → AbstractClient.ask"). Validation after parse uses the TASK-1721 catalog allowlist entry point with producer-origin = LLM (so `requires_actions` components count as failures, matching v1 production rules).

### Key Constraints
- Prompt set must be diverse and committed (`prompts.json`) so the measurement is reproducible; N ≥ 20 per client.
- Record model IDs, temperature, and max_tokens used — fidelity numbers are meaningless without them; prefer each client's default/flagship chat model and note it.
- Failure taxonomy is the deliverable that shapes the retry loop's re-prompt messages: keep the classes crisp (raw-text degradation / pydantic schema violation / unknown component / requires_actions / malformed binding / other).
- Retry-budget recommendation: derive from observed first-shot validity and whether failures look retry-recoverable (schema/component errors are; provider refusal-to-JSON typically is not). One number + rationale.
- Throwaway code: async harness is fine, no production polish, but no secrets in committed files and raw LLM outputs sanitized if they echo anything sensitive.

### References in Codebase
- `packages/ai-parrot/src/parrot/outputs/formatter.py` — `format_with_retry` / `DEFAULT_RETRY_PROMPTS`: the retry-loop precedent Module 9 lifts; the spike's taxonomy should map cleanly onto re-promptable error contexts.
- `sdd/specs/a2ui-implementation.spec.md` §3 Module 9 + §8 SPK-3 open question.

---

## Acceptance Criteria

- [ ] `artifacts/spikes/spk3-envelope-fidelity/` contains prompt set (N ≥ 20), harness, raw `runs.jsonl`, and `results.md`.
- [ ] `results.md` reports per-client first-shot validity % (parse rate AND catalog-valid rate), model/params used, and the failure-taxonomy histogram.
- [ ] A single recommended retry-budget number for TASK-1737 is stated with rationale, recorded in `results.md`, this task's Completion Note, and the spec §8 SPK-3 checkbox (checked).
- [ ] Zero changes under `packages/ai-parrot/src/parrot/clients/`; no spike code under `packages/*/src/`; no dependency changes.
- [ ] No credentials or secrets committed in evidence files.
- [ ] Existing suite untouched and green: `pytest packages/ai-parrot/tests/outputs/a2ui/ -v`
- [ ] No linting errors introduced in package code: `ruff check packages/ai-parrot/src/parrot/outputs/a2ui/` (spike scripts under `artifacts/` are exempt)

---

## Test Specification

> Spike task — no shipped tests. The scaffold below is the self-check the
> harness must perform and report before results count.

```python
# artifacts/spikes/spk3-envelope-fidelity/spike_fidelity.py (self-check outline, throwaway)

def check_prompt_set_size_and_diversity():
    """Prompt set has N >= 20 entries spanning at least 4 display-UI categories."""
    ...

def check_structured_output_path_used():
    """Every call goes through client.ask(structured_output=StructuredOutputConfig(...)) — no ad-hoc JSON parsing of raw completions."""
    ...

def check_every_run_classified():
    """Each (client, prompt) run lands in exactly one taxonomy class in runs.jsonl."""
    ...

def check_catalog_validation_applied_as_llm_origin():
    """Parsed envelopes are validated with producer-origin=LLM so requires_actions counts as failure."""
    ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in the per-spec index → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-1727-spk3-envelope-fidelity-spike.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below — for this spike the note MUST state the measured validity % and the retry-budget number

---

## Completion Note

*(Agent fills this in when done — MUST include per-client validity % and the retry-budget number handed to TASK-1737)*

**Completed by**: sdd-worker (Claude)   ·   **Status: done-with-issues**
**Date**: 2026-07-11
**Measured validity rates**: **NOT measured** — both `AnthropicClient` and
`GoogleGenAIClient` returned HTTP **404 model-not-found** for every call in this build
environment (`claude-3-5-sonnet-latest` and `gemini-1.5-pro` are not accessible to the
available credentials). `runs.jsonl` holds 22 `call_error` rows per client and zero
genuine fidelity samples. Per the task's explicit instruction I did **not** fabricate
numbers.
**Retry-budget number handed to TASK-1737**: **`max_attempts = 3` (1 initial + 2
catalog-validate retries)** — grounded in the in-repo `OutputFormatter` `max_retries=2`
precedent (evidence-pending; revisit once live numbers exist). Recorded in `results.md`
and spec §8 (checkbox checked with the pending-evidence note).

**Notes**: Committed the reproducible 22-prompt set (6 display-UI categories), the
throwaway harness (`spike_fidelity.py`) using the verified structured-output path +
catalog LLM-origin classification taxonomy, `runs.jsonl` (the honest 404 outcomes), and
`results.md`. No client code changed; no secrets committed; no dependency changes. The
a2ui core suite remains green.

**Deviations from spec**: live validity measurement not obtainable in this environment
(model access unavailable → 404); harness + prompts + taxonomy + a precedent-grounded
retry budget are delivered so TASK-1737 is unblocked. Re-run `spike_fidelity.py` with
valid Anthropic + Google GenAI credentials (and accessible model IDs) to fill in the
numbers.
