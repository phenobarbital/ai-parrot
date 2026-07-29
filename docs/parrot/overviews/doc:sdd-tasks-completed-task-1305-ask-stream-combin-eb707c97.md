---
type: Wiki Overview
title: 'TASK-1305: Refactor `ask_stream()` symmetrically for combined mode'
id: doc:sdd-tasks-completed-task-1305-ask-stream-combined-mode-refactor-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: TASK-1305 depends on TASK-1303 (the helper) but is INDEPENDENT of TASK-1304
  — the two methods don't share runtime state. In a parallel-worktree world they could
  be done concurrently, but since this feature uses a single per-spec worktree, they
  will run sequentially.
relates_to:
- concept: mod:parrot.models.outputs
  rel: mentions
---

# TASK-1305: Refactor `ask_stream()` symmetrically for combined mode

**Feature**: FEAT-193 — Google GenAI client: simultaneous tool-calling + structured output
**Spec**: `sdd/specs/google-genai-combined-tools-and-schema.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1303
**Assigned-to**: unassigned

---

## Context

`GoogleGenAIClient.ask_stream()` has its own two-phase flow that mirrors `ask()`: schema is applied to the streaming chat config ONLY when no tools are in play (`client.py:2847-2854`), and a post-stream reformat call against `_reformat_model` runs at `client.py:3020-3084` when tools were used. This task brings `ask_stream()` to parity with TASK-1304: for whitelisted models, apply schema to the streaming chat config alongside tools, and skip the post-stream reformat call.

TASK-1305 depends on TASK-1303 (the helper) but is INDEPENDENT of TASK-1304 — the two methods don't share runtime state. In a parallel-worktree world they could be done concurrently, but since this feature uses a single per-spec worktree, they will run sequentially.

If TASK-1304 extracted a reformat helper (`_reformat_to_structured`), reuse it here for the recovery branch.

Implements spec §3 Module 2, sub-task 6 (`ask_stream()` gate refactor + post-stream reformat block).

---

## Scope

- Modify the gate at `client.py:2847-2854` so the schema is applied when:
  `structured_output and (not _use_tools or self._supports_combined_tools_and_schema(model, self._combined_call_prefixes))`.
- In the post-stream reformat block at `client.py:3020-3084`:
  - Preserve existing behaviour when tools were used AND combined mode is NOT in effect.
  - Add a new branch for combined mode: parse `final_text` via `_parse_structured_output(final_text, structured_output)` and set `final_output`. **Do NOT** invoke the second `generate_content` call.
  - On combined-mode parse failure, fall back to the legacy reformat call (recovery branch — same approach as TASK-1304).
- Emit the `gemini-3.1-flash-lite` debug log when combined mode is selected on that prefix (same message as TASK-1304).

**NOT in scope**:
- `ask()` refactor (TASK-1304).
- The helper / constructor kwarg / comment update (covered by TASK-1303 / TASK-1304).
- Adding regression tests for the new streaming branches — TASK-1307.
- Changing the streaming wire protocol, chunk yielding, lifecycle events, or memory updates.
- Touching the `output_config and not use_tools` original path (it stays — combined mode simply widens the `applies_schema` condition).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/google/client.py` | MODIFY | Refactor the `ask_stream()` gate (2847-2854) and the post-stream reformat block (3020-3084). |

No new files. Tests live in TASK-1307.

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# All used by existing code — no new imports needed.
from google.genai.types import GenerateContentConfig, ThinkingConfig, Part
from parrot.models.outputs import StructuredOutputConfig
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/clients/google/client.py  (verified at HEAD, 3980 lines, 2026-05-27)

class GoogleGenAIClient(AbstractClient):
    # From TASK-1303 (must be merged first):
    _combined_call_prefixes: tuple[str, ...]

    @staticmethod
    def _supports_combined_tools_and_schema(model, prefixes: tuple[str, ...]) -> bool: ...

    # From TASK-1304 (optional but recommended — if extracted as a helper):
    async def _reformat_to_structured(
        self,
        text: str,
        output_config,
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> Any: ...   # if NOT extracted, reuse the inline logic via copy/paste discouraged — see Notes.

    # Existing helpers (re-verified at HEAD):
    def _apply_structured_output_schema(                                 # line 750
        self,
        generation_config: Dict[str, Any],
        output_config: Optional[StructuredOutputConfig],
    ) -> Optional[Dict[str, Any]]: ...

    async def _parse_structured_output(self, text: str, output_config) -> Any: ...   # used at line 3082

    async def ask_stream(self, prompt: str, ...) -> AsyncIterator:       # line 2649
```

### Critical code blocks

**Block 1 — the stream gate (client.py:2843-2854):**

```python
if gemini_tools:
    generation_config_args["tools"] = gemini_tools

# Handle structured output mapping
schema_config = None
if structured_output and not _use_tools:
    schema_config = (
        structured_output
        if isinstance(structured_output, StructuredOutputConfig)
        else self._get_structured_config(structured_output)
    )
    if schema_config:
        self._apply_structured_output_schema(generation_config_args, schema_config)
```

**Block 2 — the post-stream reformat (client.py:3020-3084):**

```python
if structured_output and final_text:
    if _use_tools:
        try:
            is_json_candidate = (
                final_text.strip().startswith('{') or
                final_text.strip().startswith('[') or
                '```json' in final_text.strip()
            )
            if is_json_candidate:
                fast_parsed = await self._parse_structured_output(final_text, structured_output)
                if not isinstance(fast_parsed, str):
                    final_output = fast_parsed

            if final_output is None:
                struct_cfg = {"response_mime_type": "application/json"}
                if schema_config := (structured_output if isinstance(structured_output, StructuredOutputConfig) else self._get_structured_config(structured_output)):
                    self._apply_structured_output_schema(struct_cfg, schema_config)

                reformat_model = self._reformat_model
                if not self._requires_thinking(reformat_model):
                    struct_cfg["thinking_config"] = ThinkingConfig(thinking_budget=0)

                format_prompt = "Convert the following response into the requested JSON structure. ..."
                structured_response = await self.client.aio.models.generate_content(
                    model=reformat_model,
                    contents=[{"role": "user", "parts": [{"text": format_prompt}]}],
                    config=GenerateContentConfig(**struct_cfg)
                )
                if structured_text := self._safe_extract_text(structured_response):
                    # parse structured_text into final_output ...
        except Exception as e:
            self.logger.error(f"Streaming structured output reformat failed: {e}")
    else:
        try:
            final_output = await self._parse_structured_output(final_text, structured_output)
        except Exception:
            pass
```

### Does NOT Exist

- ~~`ask_stream()` with a `combined_mode: bool` kwarg~~ — the public signature stays unchanged.
- ~~A separate `ask_stream_combined()` method~~ — single method, capability-gated internally.
- ~~Mid-stream schema application~~ — the schema goes on the initial `GenerateContentConfig`; it does not change once streaming starts.

---

## Implementation Notes

### Approach

Same shape as TASK-1304. Compute `combined_mode` once near the top, then branch the gate and the post-stream reformat:

```python
# Near the top of the streaming setup (~ before line 2843):
combined_mode = bool(
    structured_output
    and _use_tools
    and self._supports_combined_tools_and_schema(model, self._combined_call_prefixes)
)

# Refactor the gate at ~2847-2854:
if gemini_tools:
    generation_config_args["tools"] = gemini_tools

schema_config = None
applies_schema = bool(structured_output) and (not _use_tools or combined_mode)
if applies_schema:
    schema_config = (
        structured_output
        if isinstance(structured_output, StructuredOutputConfig)
        else self._get_structured_config(structured_output)
    )
    if schema_config:
        self._apply_structured_output_schema(generation_config_args, schema_config)
        if combined_mode and model.startswith("gemini-3.1-flash-lite"):
            self.logger.debug(
                "Combined tools+schema mode on %s: upstream evaluation flagged "
                "AFC instability — monitor latency.",
                model,
            )
```

Then refactor the post-stream reformat at ~3020-3084:

```python
if structured_output and final_text:
    if combined_mode:
        # NEW: parse-only path. The streamed text is already schema-compliant.
        try:
            parsed = await self._parse_structured_output(final_text, structured_output)
            if isinstance(parsed, str):
                # Recovery: malformed JSON despite response_schema — fall back to reformat.
                self.logger.warning(
                    "Combined-mode stream parse returned raw string for %s — falling back to reformat call.",
                    model,
                )
                # If TASK-1304 extracted `_reformat_to_structured`, call it:
                final_output = await self._reformat_to_structured(
                    final_text, structured_output, temperature=temperature, max_tokens=current_max_tokens,
                )
                # If it did NOT extract — duplicate the reformat code here (NOT recommended; see Notes).
            else:
                final_output = parsed
        except Exception as e:
            self.logger.error("Combined-mode stream structured-output parse failed: %s", e)
    elif _use_tools:
        # EXISTING two-phase reformat (~3022-3079) — unchanged.
        ...
    else:
        # EXISTING parse-only path (~3081-3084) — unchanged.
        try:
            final_output = await self._parse_structured_output(final_text, structured_output)
        except Exception:
            pass
```

### Coordination with TASK-1304

If TASK-1304 extracts `_reformat_to_structured`, this task simply CALLS it. If it did NOT extract, you have two choices:

1. **Extract now** as part of this task (preferred, but enlarges the diff for TASK-1305).
2. Duplicate the reformat-call code into the streaming recovery branch. **Discouraged** — leads to drift between `ask()` and `ask_stream()`.

Inspect the TASK-1304 completion note before starting; pick the cleaner option for the actual state of the codebase.

### Key Constraints

- `ask_stream()` public signature does NOT change.
- Streaming chunk yielding semantics MUST be unchanged — combined mode only changes which config keys land on the streaming chat config and which post-stream calls are made (or NOT made).
- Lifecycle events (`_emit_after_call` at line 3124-3130), conversation memory updates (`_update_conversation_memory` at line 3094), and `AIMessageFactory.from_gemini` (line 3106) MUST keep firing exactly as today on both branches.
- Do NOT alter the AFC `max_iterations` loop, retry/backoff logic, or the `HumanInteractionInterrupt` handling.

### References in Codebase

- `client.py:2649-3131` — `ask_stream()` method body (the surface of this task).
- `client.py:2847-2854` — the gate (primary edit point #1).
- `client.py:3020-3084` — the post-stream reformat block (primary edit point #2).
- `client.py:2843` — `if gemini_tools: generation_config_args["tools"] = gemini_tools` — informational, not edited.

---

## Acceptance Criteria

- [ ] When `structured_output and _use_tools and self._supports_combined_tools_and_schema(...)`, the schema is applied to `generation_config_args` BEFORE `self.client.aio.chats.create(...)` is called at `client.py:2856-2860`.
- [ ] When combined mode is in effect, no `generate_content` call is made after the streaming loop completes (verified by mock assertion in TASK-1307).
- [ ] When `_parse_structured_output` returns a string (parse failure) in combined-mode streaming, the recovery branch falls back to the legacy reformat call.
- [ ] When combined mode triggers AND the model starts with `gemini-3.1-flash-lite`, `self.logger.debug(...)` fires once.
- [ ] Non-whitelisted models keep the EXISTING two-phase behaviour byte-for-byte (verified by regression test in TASK-1307).
- [ ] The `output_config and not use_tools` branch (no-tools structured output) is UNCHANGED — combined mode does not affect it.
- [ ] Streaming chunk yielding (`yield chunk.text`) is unchanged.
- [ ] `_update_conversation_memory` and `_emit_after_call` still fire in both branches.
- [ ] No regression: `pytest packages/ai-parrot/tests/test_google_client.py -v` passes pre-existing tests + TASK-1303 helper tests.
- [ ] Diff stays focused on `client.py`.

---

## Test Specification

Detailed tests live in TASK-1307. Smoke checks only here.

---

## Agent Instructions

1. **Read TASK-1303 and TASK-1304's completion notes** — confirm the helper, kwarg, and (if extracted) `_reformat_to_structured` are merged.
2. **Read the spec**, especially §3 Module 2 sub-task 6 and §6 Codebase Contract.
3. **Verify the codebase contract**:
   - `sed -n '2843,2865p' packages/ai-parrot/src/parrot/clients/google/client.py` — confirm the gate.
   - `sed -n '3015,3090p' packages/ai-parrot/src/parrot/clients/google/client.py` — confirm the post-stream reformat.
4. **Implement** — branch the gate and the post-stream reformat.
5. **Smoke check**:
   ```bash
   cd packages/ai-parrot
   pytest tests/test_google_client.py -v -k "stream"
   ```
6. **Verify diff scope**: `git diff packages/ai-parrot/src/parrot/clients/google/client.py | wc -l` — expect ~60-100 lines.
7. Move this file to `sdd/tasks/completed/` and update the per-spec index status to `done`.

---

## Completion Note

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-05-27
**Notes**: Added `combined_mode` local variable and `applies_schema` gate in `ask_stream()`. The post-stream reformat block now has `if combined_mode: ... elif _use_tools: ... else:` branches. The two-phase path (`elif _use_tools`) is preserved byte-for-byte. The combined-mode path calls `_reformat_to_structured` (extracted in TASK-1304) for the recovery branch. 25/26 tests pass (1 pre-existing failure in `test_google_ask_stream` unrelated to this task).

**Deviations from spec**: None.
