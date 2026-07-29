---
type: Wiki Overview
title: 'TASK-1304: Refactor `ask()` to support combined tools + structured output'
id: doc:sdd-tasks-completed-task-1304-ask-combined-mode-refactor-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Also includes a malformed-JSON recovery branch: if the model violates `response_schema`
  despite the constraint, fall back to the legacy reformat call (preserves today''s
  reliability).'
relates_to:
- concept: mod:parrot.clients.google.client
  rel: mentions
- concept: mod:parrot.models.outputs
  rel: mentions
---

# TASK-1304: Refactor `ask()` to support combined tools + structured output

**Feature**: FEAT-193 — Google GenAI client: simultaneous tool-calling + structured output
**Spec**: `sdd/specs/google-genai-combined-tools-and-schema.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1303
**Assigned-to**: unassigned

---

## Context

`GoogleGenAIClient.ask()` currently runs a **two-phase flow** whenever both tools and structured output are requested: a tool-using chat call, then a separate `generate_content` call against `_reformat_model` (see `client.py:2033-2048` and `:2337-2474`). This task introduces a capability branch: when the model is whitelisted (per the helper added in TASK-1303), apply `response_mime_type` + `response_schema` to the SAME `GenerateContentConfig` as `tools` and skip the deferred reformat call. Non-whitelisted models — including `gemini-2.5-pro`, which Google's API rejects with 400 when both are combined — keep the existing two-phase flow byte-for-byte.

Also includes a malformed-JSON recovery branch: if the model violates `response_schema` despite the constraint, fall back to the legacy reformat call (preserves today's reliability).

Implements spec §3 Module 2, sub-tasks 4-5 and 7-8 (`ask()` gate refactor + deferred-reformat block + comment update + debug log for `flash-lite`).

---

## Scope

- Replace the gate at `client.py:2033-2048` so the schema is applied immediately to `generation_config` when `_use_tools and use_structured_output and self._supports_combined_tools_and_schema(model, self._combined_call_prefixes)`.
- In the deferred-reformat block at `client.py:2337-2474`:
  - Preserve the existing two-phase behaviour when `structured_output_for_later` is set (non-whitelisted models).
  - Add a new branch for combined mode: parse `assistant_response_text` via `_parse_structured_output(assistant_response_text, output_config)` and store the result in `final_output`. **Do NOT call `generate_content` a second time** in this path.
  - If combined-mode parsing fails (raises or returns the unmodified string), fall back to the legacy reformat call. This recovery branch reuses the same block of code that the two-phase path uses today.
- Update the stale comment at `client.py:109-115` to reflect the new bifurcation (older models still go two-phase; whitelisted models go combined).
- Emit `self.logger.debug("Combined tools+schema mode on %s: upstream evaluation flagged AFC instability — monitor latency.", model)` once per call when combined mode is selected AND the model starts with `gemini-3.1-flash-lite`.

**NOT in scope**:
- `ask_stream()` refactor — TASK-1305.
- Adding the capability helper or constructor kwarg — TASK-1303 (must already be merged).
- Adding regression tests for the new branches — TASK-1307. *(Tests can be sketched here but final coverage lives in TASK-1307.)*
- The example update — TASK-1306.
- Changing the existing `_reformat_model` selection logic, the fast-path JSON detect, the cache plumbing, or the lifecycle event emissions — all preserved as-is.
- Touching the `output_config and not use_tools` branch at `client.py:2475-2484` — leave alone.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/google/client.py` | MODIFY | Refactor the `ask()` gate (2033-2048) and the deferred-reformat block (2337-2474). Update the constraint comment (109-115). Add the debug log inside the combined-mode branch. |

No new files. No test changes here (tests belong to TASK-1307).

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# All used by the existing code already — no new imports needed.
from typing import Optional, Union, Dict, Any
from parrot.models.outputs import StructuredOutputConfig, OutputFormat   # used in _apply_structured_output_schema
from google.genai.types import GenerateContentConfig, ThinkingConfig     # used in ask()
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/clients/google/client.py  (verified at HEAD, 3980 lines, 2026-05-27)

class GoogleGenAIClient(AbstractClient):
    # From TASK-1303 (must be merged first):
    _combined_call_prefixes: tuple[str, ...]     # instance attr set in __init__

    @staticmethod
    def _supports_combined_tools_and_schema(model, prefixes: tuple[str, ...]) -> bool: ...

    # Existing helpers (re-verified at HEAD):
    def _apply_structured_output_schema(                                 # line 750
        self,
        generation_config: Dict[str, Any],
        output_config: Optional[StructuredOutputConfig],
    ) -> Optional[Dict[str, Any]]:
        """Apply `response_mime_type` + `response_schema` to `generation_config`.
        Returns the fixed schema dict or None on failure."""

    async def _parse_structured_output(self, text: str, output_config) -> Any:
        """Parses `text` against the schema in `output_config`.
        Returns the parsed Pydantic/dict on success; returns the input
        string on parse failure (so callers can detect failure via isinstance check)."""

    async def ask(self, prompt: str, ...) -> AIMessage:                  # line 1797
```

### Critical code blocks (must understand BEFORE editing)

**Block 1 — the gate (client.py:2033-2048):**

```python
use_structured_output = bool(output_config)
# Google limitation: Cannot combine tools with structured output
# Strategy: If both are requested, use tools first, then apply structured output to final result
if _use_tools and use_structured_output:
    self.logger.info(
        "Google Gemini doesn't support tools + structured output simultaneously. "
        "Using tools first, then applying structured output to the final result."
    )
    structured_output_for_later = output_config
    # Don't set structured output in initial config
    output_config = None
else:
    structured_output_for_later = None
    # Set structured output in generation config if no tools conflict
    if output_config:
        self._apply_structured_output_schema(generation_config, output_config)
```

**Block 2 — the deferred reformat (client.py:2337-2474):**

```python
# Handle structured output
final_output = None
if structured_output_for_later and use_tools and assistant_response_text:
    try:
        # ... builds structured_config, fast-path JSON detect (2350-2378),
        # then if final_output is None, runs ~140 lines of reformat-call logic
        # against self._reformat_model ...
    except Exception as e:
        self.logger.error(f"Error parsing structured output: {e}")
        final_output = assistant_response_text
elif output_config and not use_tools:
    try:
        final_output = await self._parse_structured_output(
            assistant_response_text,
            output_config
        )
    except Exception:
        final_output = assistant_response_text
else:
    final_output = assistant_response_text
```

**Block 3 — the stale comment (client.py:109-115):**

```python
# Default model used to reformat tool-using responses into structured
# output (Gemini cannot combine tools + response_schema in one call).
# Override per-instance via the ``reformat_model`` constructor kwarg.
# DO NOT downgrade the default to a smaller model (e.g. flash-lite):
# small models hallucinate rows when extracting tabular data from a
# shape-annotated preview, corrupting `data`.
_default_reformat_model: str = GoogleModel.GEMINI_3_FLASH_PREVIEW.value
```

### Does NOT Exist

- ~~`StructuredOutputConfig.combined_mode_enabled`~~ — capability is gated on the MODEL, not on the output config.
- ~~`generate_content_combined()`~~ as a separate method — the change happens inline in the existing `ask()`, NOT via a new method.
- ~~A new ``combined_mode: bool` parameter on `ask()`~~ — the public signature is unchanged; the new behaviour is internal.
- ~~`types.GenerateContentConfig.combined_call=True`~~ — no such flag in the Google GenAI SDK. The "combined" behaviour is just `tools` + `response_schema` in the same config dict.
- ~~Skipping `_apply_structured_output_schema` in combined mode~~ — combined mode CALLS this helper directly to apply the schema; do not duplicate its logic.

---

## Implementation Notes

### Approach

The cleanest refactor is to introduce a `combined_mode: bool` local variable computed once before the gate, then use it to branch both at the gate AND at the deferred-reformat block:

```python
# Pseudo-code — adapt to surrounding code style; consult lines 2033-2048 for context.
use_structured_output = bool(output_config)
combined_mode = (
    _use_tools
    and use_structured_output
    and self._supports_combined_tools_and_schema(model, self._combined_call_prefixes)
)

if _use_tools and use_structured_output and not combined_mode:
    # EXISTING two-phase path — unchanged.
    self.logger.info("Google Gemini doesn't support tools + structured output simultaneously. ...")
    structured_output_for_later = output_config
    output_config = None
elif combined_mode:
    # NEW: apply schema to the SAME chat call.
    structured_output_for_later = None
    self._apply_structured_output_schema(generation_config, output_config)
    if model.startswith("gemini-3.1-flash-lite"):
        self.logger.debug(
            "Combined tools+schema mode on %s: upstream evaluation flagged "
            "AFC instability — monitor latency.",
            model,
        )
else:
    # EXISTING non-tool path — unchanged.
    structured_output_for_later = None
    if output_config:
        self._apply_structured_output_schema(generation_config, output_config)
```

Then at the deferred-reformat block (~2337), the existing `if structured_output_for_later and use_tools and assistant_response_text:` check naturally falls through when `combined_mode is True` (because `structured_output_for_later` is None). Add an explicit elif:

```python
final_output = None
if structured_output_for_later and use_tools and assistant_response_text:
    # ... existing 140-line two-phase logic UNCHANGED ...
elif combined_mode and assistant_response_text and output_config:
    # NEW: combined-mode parse-only path.
    try:
        parsed = await self._parse_structured_output(assistant_response_text, output_config)
        if isinstance(parsed, str):
            # _parse_structured_output returns the input string on parse failure.
            # Recovery: re-run the schema via the legacy reformat call.
            self.logger.warning(
                "Combined-mode parse returned raw string for %s — falling back to reformat call.",
                model,
            )
            structured_output_for_later = output_config   # re-enter two-phase path
            # NOTE: Easiest implementation is to refactor the two-phase logic into a
            # helper method and call it here. Alternative: use a single `goto`-style
            # nested if. Pick whichever keeps the diff small and the control flow legible.
            final_output = await self._reformat_to_structured(  # see Implementation Notes below
                assistant_response_text,
                output_config,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        else:
            final_output = parsed
    except Exception as e:
        self.logger.error("Combined-mode structured-output parse failed: %s", e)
        final_output = assistant_response_text
elif output_config and not use_tools:
    # EXISTING — unchanged.
    try:
        final_output = await self._parse_structured_output(assistant_response_text, output_config)
    except Exception:
        final_output = assistant_response_text
else:
    final_output = assistant_response_text
```

### Refactor decision: extract the reformat logic into a helper?

The simplest safe path is to extract the ~140-line reformat block at `client.py:2337-2474` (everything from `_max = max_tokens or self.max_tokens` through to the final structured-output assignment) into a private helper method `async def _reformat_to_structured(self, text: str, output_config, *, temperature, max_tokens) -> Any`. This:

- Lets the recovery branch call the same code.
- Lets TASK-1305 (the streaming refactor) share the same helper.
- Makes the diff in `ask()` itself much smaller.

If you choose NOT to extract, you must duplicate the reformat code into the recovery branch — which is brittle. **Strongly recommended: extract the helper.**

Place the new helper near `_apply_structured_output_schema` (around line 770) so it sits with related plumbing.

### Constraint comment update (lines 109-115)

Rewrite as something like:

```python
# Default model used to reformat tool-using responses into structured
# output for models that cannot combine tools + response_schema in one
# call (e.g., gemini-2.5-pro). Override per-instance via the
# ``reformat_model`` constructor kwarg. DO NOT downgrade the default to
# a smaller model (e.g. flash-lite): small models hallucinate rows when
# extracting tabular data from a shape-annotated preview, corrupting
# ``data``. Whitelisted Gemini 3.x models (configured via
# ``combined_call_prefixes``) bypass this reformat step — see
# ``_supports_combined_tools_and_schema``.
```

### Key Constraints

- Public signature of `ask()` does NOT change.
- All surrounding FEAT-181 cache hint code (lines 2120-2157), FEAT-176 lifecycle events (`_emit_after_call`), conversation memory updates (`_update_conversation_memory`), and thinking-config selection must keep firing exactly as today on BOTH branches.
- The fast-path JSON detect inside the existing two-phase reformat block (lines 2350-2378) is NOT part of combined mode. Combined mode goes straight to `_parse_structured_output` because the model was already told the schema.
- Do NOT introduce a global `combined_mode` instance attribute — the value is per-call and lives as a local variable.

### References in Codebase

- `packages/ai-parrot/src/parrot/clients/google/client.py:2033-2048` — the gate (the primary edit point).
- `packages/ai-parrot/src/parrot/clients/google/client.py:2337-2474` — the deferred reformat block (extract helper here).
- `packages/ai-parrot/src/parrot/clients/google/client.py:750-771` — `_apply_structured_output_schema` (call site, unchanged).
- `packages/ai-parrot/src/parrot/clients/google/client.py:109-115` — stale comment (update).
- `packages/ai-parrot/src/parrot/clients/google/client.py:2120-2157` — cache hint plumbing (preserve, do not touch).
- `packages/ai-parrot/src/parrot/clients/google/client.py:2475-2484` — `output_config and not use_tools` branch (preserve, do not touch).

---

## Acceptance Criteria

- [ ] When `_use_tools and use_structured_output and self._supports_combined_tools_and_schema(model, self._combined_call_prefixes)`, the schema is applied to `generation_config` in the SAME call (no `structured_output_for_later` set).
- [ ] When the above check is False but tools + structured output are still both requested, the EXISTING two-phase flow runs unchanged.
- [ ] When combined mode is in effect, the deferred reformat block at `client.py:2337-2474` does NOT make a second `generate_content` call (verified by mock assertion in TASK-1307).
- [ ] When `_parse_structured_output` returns a string in combined mode (parse failure), the recovery branch invokes the legacy reformat call against `self._reformat_model`.
- [ ] When combined mode triggers AND the model starts with `gemini-3.1-flash-lite`, `self.logger.debug(...)` is called once with the documented message.
- [ ] The comment at `client.py:109-115` is updated; the surrounding code is otherwise untouched.
- [ ] No regression: `pytest packages/ai-parrot/tests/test_google_client.py -v` passes all pre-existing tests + the TASK-1303 helper tests.
- [ ] `ask()` public signature is unchanged.
- [ ] If the reformat helper is extracted, it lives near `_apply_structured_output_schema` (around line 770) and has a clear docstring.
- [ ] No new external imports.
- [ ] Diff stays focused on `client.py` — no other files modified.

---

## Test Specification

Detailed regression tests live in TASK-1307. This task only needs sanity-level local checks during implementation:

```python
# Sanity-check during implementation (informal — full tests in TASK-1307).
# Run interactively:

from unittest.mock import AsyncMock, MagicMock, patch
from parrot.clients.google.client import GoogleGenAIClient

async def smoke():
    client = GoogleGenAIClient()  # uses defaults
    # Whitelisted: should NOT set structured_output_for_later
    # Non-whitelisted: SHOULD set structured_output_for_later
    # (Walk through the relevant branch in a debugger or with breakpoints.)
```

**Do not commit a half-baked test file in this task.** TASK-1307 owns the full test surface.

---

## Agent Instructions

1. **Read TASK-1303's completion note** — confirm the helper and constructor kwarg are merged.
2. **Read the spec** at `sdd/specs/google-genai-combined-tools-and-schema.spec.md`, especially §3 Module 2 and §6 Codebase Contract.
3. **Verify the codebase contract**:
   - `sed -n '2030,2050p' packages/ai-parrot/src/parrot/clients/google/client.py` — confirm the gate is still at the documented lines.
   - `sed -n '2335,2480p' packages/ai-parrot/src/parrot/clients/google/client.py` — confirm the reformat block.
   - `sed -n '105,120p' packages/ai-parrot/src/parrot/clients/google/client.py` — confirm the comment.
4. **Implement**:
   - Decide whether to extract the reformat helper (recommended). If yes, do that as a first commit before touching `ask()`.
   - Edit the gate.
   - Edit the deferred-reformat block.
   - Update the comment.
   - Add the debug log inside the combined-mode branch.
5. **Run a smoke check**:
   ```bash
   cd packages/ai-parrot
   pytest tests/test_google_client.py -v
   python -c "from parrot.clients.google.client import GoogleGenAIClient; c = GoogleGenAIClient(); print(c._combined_call_prefixes)"
   ```
6. **Verify diff scope**: `git diff packages/ai-parrot/src/parrot/clients/google/client.py | wc -l` — expect on the order of 100-150 lines of changes (mostly additions + the helper extraction).
7. Move this file to `sdd/tasks/completed/` and update the per-spec index status to `done`.

---

## Completion Note

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-05-27
**Notes**: Added `combined_mode` local variable and three-branch gate in `ask()`. Extracted the reformat logic into `_reformat_to_structured` private helper near `_apply_structured_output_schema`. Added `elif combined_mode` branch in the deferred-reformat block. The two-phase path (fast-path JSON detect + reformat call) is preserved byte-for-byte inside the existing `if structured_output_for_later` branch. 25/26 tests pass (1 pre-existing failure in `test_google_ask_stream` unrelated to this task).

**Deviations from spec**: None. The `_reformat_to_structured` helper was extracted as recommended (but not strictly required) by the spec, making the combined-mode recovery branch and future ask_stream() reuse clean.
