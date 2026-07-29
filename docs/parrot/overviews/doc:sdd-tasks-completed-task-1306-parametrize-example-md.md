---
type: Wiki Overview
title: 'TASK-1306: Parametrize `examples/google/structured_with_tools.py` over the
  whitelist'
id: doc:sdd-tasks-completed-task-1306-parametrize-example-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'The current example at `examples/google/structured_with_tools.py` is hardcoded
  to `gemini-2.0-flash` (a non-whitelisted model that falls back to the two-phase
  flow). To let the user exercise the new combined-mode path against each whitelisted
  model, extend the example to iterate '
relates_to:
- concept: mod:parrot.clients.google.client
  rel: mentions
- concept: mod:parrot.models.basic
  rel: mentions
- concept: mod:parrot.models.google
  rel: mentions
- concept: mod:parrot.tools.abstract
  rel: mentions
- concept: mod:parrot.tools.manager
  rel: mentions
---

# TASK-1306: Parametrize `examples/google/structured_with_tools.py` over the whitelist

**Feature**: FEAT-193 — Google GenAI client: simultaneous tool-calling + structured output
**Spec**: `sdd/specs/google-genai-combined-tools-and-schema.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1304, TASK-1305
**Assigned-to**: unassigned

---

## Context

The current example at `examples/google/structured_with_tools.py` is hardcoded to `gemini-2.0-flash` (a non-whitelisted model that falls back to the two-phase flow). To let the user exercise the new combined-mode path against each whitelisted model, extend the example to iterate over the whitelist or accept a `--model` CLI argument.

This example is the user's tactile validation of FEAT-193 — running it against `gemini-3.5-flash` and `gemini-3.1-pro-preview` should show ONE LLM call's worth of latency; running it against `gemini-2.5-pro` should still work (two-phase fallback) and show the historical two-call pattern.

Implements spec §3 Module 3.

---

## Scope

- Add `argparse`-based CLI: `--model <model-id>` accepts a single model identifier. If omitted, the script iterates over the default whitelist plus `gemini-2.5-pro` for regression visibility.
- For each model invocation, print:
  - Model identifier and a separator.
  - The prompt sent.
  - Pass/fail with a short reason if an exception was raised.
  - `len(response.tool_calls)`.
  - Whether `response.structured_output` is a `WeatherReport` instance (and the field values if it is).
  - Response time (wall-clock, `time.perf_counter()`).
  - A short note: `[combined-mode]` if the model is in the client's default whitelist, `[two-phase]` otherwise.
- Keep the existing `WeatherReport` Pydantic schema and `WeatherTool` (`AbstractTool` subclass) — DO NOT introduce new tools or schemas in this task.
- Preserve the `GOOGLE_API_KEY` env-var check at the bottom and the `asyncio.run(main())` entry point.

**NOT in scope**:
- The client refactor (TASK-1303 / 1304 / 1305).
- Adding new tools / schemas.
- Adding tests for the example (the example IS the manual smoke test).
- Replacing `AbstractTool` with `genai.types.FunctionDeclaration` — the example must continue exercising the parrot tool wiring, not the raw SDK.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `examples/google/structured_with_tools.py` | MODIFY | Rewrite `main()` to accept `--model` and iterate the whitelist. Keep the `WeatherReport` schema and `WeatherTool` class as-is. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Verified at HEAD on dev (2026-05-27) — these all exist:
import asyncio
import os
import json                                                      # already imported, even if unused after refactor
from typing import List, Optional
from pydantic import BaseModel, Field
from parrot.clients.google.client import GoogleGenAIClient       # already imported
from parrot.models.google import GoogleModel                     # already imported
from parrot.tools.abstract import AbstractTool                   # already imported
from parrot.tools.manager import ToolManager                     # already imported
from parrot.models.basic import ToolCall                         # already imported

# New imports needed:
import argparse
import time
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/clients/google/client.py  (verified at HEAD)
class GoogleGenAIClient(AbstractClient):
    # After TASK-1303 + 1304 + 1305 are merged:
    _default_combined_call_prefixes: tuple[str, ...]
    # __init__ accepts:
    #   api_key, tool_manager, enable_tools, combined_call_prefixes, ...

    async def ask(
        self,
        prompt: str,
        model: Union[str, GoogleModel] = None,
        structured_output: Union[type, StructuredOutputConfig] = None,
        use_tools: bool = ...,
        ...
    ) -> AIMessage: ...

# packages/ai-parrot/src/parrot/models/responses.py — AIMessage attributes used:
class AIMessage:
    response: str
    content: str
    structured_output: Any
    tool_calls: List[ToolCall]
    to_text: str                  # exists, used by the existing example at line 81
```

### Existing example structure (verified — DO NOT recreate from scratch)

The current example (99 lines) defines:
- `class WeatherReport(BaseModel)` — keep as-is.
- `class WeatherTool(AbstractTool)` with `name = "get_weather"`, `description`, `get_schema()`, and `async _execute(location, **kwargs)` — keep as-is.
- `async def main()` — REWRITE THIS to add the CLI + iteration.
- `if __name__ == "__main__":` block with `GOOGLE_API_KEY` check — keep as-is, but route through the new `main()`.

### Does NOT Exist

- ~~`GoogleGenAIClient.combined_call_models`~~ — the attribute is `_combined_call_prefixes` (underscore prefix, plural "prefixes" not "models").
- ~~`response.structured_output_type`~~ — no such attribute. Check `isinstance(response.structured_output, WeatherReport)` instead.
- ~~`AIMessage.is_combined_mode`~~ — no such introspection field. The example must label the mode based on whether the model matches the whitelist (compute locally).
- ~~`AIMessage.latency_ms`~~ — measure with `time.perf_counter()` around the `await client.ask(...)` call.

---

## Implementation Notes

### Suggested structure

```python
import argparse
import asyncio
import os
import time

from pydantic import BaseModel, Field
from parrot.clients.google.client import GoogleGenAIClient
from parrot.tools.abstract import AbstractTool
from parrot.tools.manager import ToolManager


# Default test set: 3 whitelisted + 1 known-fallback model for regression visibility.
DEFAULT_MODELS = (
    "gemini-3.5-flash",
    "gemini-3.1-pro-preview",
    "gemini-3.1-flash-lite-preview",
    "gemini-2.5-pro",            # falls back to two-phase — keep for regression visibility
)


class WeatherReport(BaseModel):
    # ... unchanged from existing example ...


class WeatherTool(AbstractTool):
    # ... unchanged from existing example ...


def _is_combined_mode_default(model: str) -> bool:
    """Local helper — mirrors the client's default whitelist without importing private state."""
    return any(
        model.startswith(p)
        for p in GoogleGenAIClient._default_combined_call_prefixes
    )


async def run_one(client: GoogleGenAIClient, model: str, prompt: str) -> None:
    mode = "combined-mode" if _is_combined_mode_default(model) else "two-phase"
    print(f"\n=== {model}  [{mode}] ===")
    print(f"Prompt: {prompt}")
    t0 = time.perf_counter()
    try:
        response = await client.ask(
            prompt=prompt,
            model=model,
            structured_output=WeatherReport,
            use_tools=True,
        )
    except Exception as e:
        elapsed = time.perf_counter() - t0
        print(f"  ❌ {type(e).__name__}: {e}  ({elapsed:.2f}s)")
        return

    elapsed = time.perf_counter() - t0
    is_weather = isinstance(response.structured_output, WeatherReport)
    print(f"  ✅ structured_output_is_WeatherReport={is_weather}  "
          f"tool_calls={len(response.tool_calls or [])}  ({elapsed:.2f}s)")
    if is_weather:
        print(f"     → {response.structured_output}")
    if response.tool_calls:
        for tc in response.tool_calls:
            print(f"     → tool {tc.name}({tc.arguments}) -> {tc.result}")


async def main(models: list[str], prompt: str) -> None:
    tool_manager = ToolManager()
    tool_manager.register_tool(WeatherTool())
    client = GoogleGenAIClient(
        api_key=os.environ.get("GOOGLE_API_KEY"),
        tool_manager=tool_manager,
        enable_tools=True,
    )
    for model in models:
        await run_one(client, model, prompt)


if __name__ == "__main__":
    if not os.environ.get("GOOGLE_API_KEY"):
        print("Please set GOOGLE_API_KEY environment variable")
        raise SystemExit(1)

    parser = argparse.ArgumentParser(
        description="Exercise combined-mode tool-calling + structured output for Gemini models."
    )
    parser.add_argument(
        "--model",
        action="append",
        dest="models",
        help="Model identifier to test. Repeat the flag to test multiple. "
             "If omitted, the default whitelist + gemini-2.5-pro is tested.",
    )
    parser.add_argument(
        "--prompt",
        default="What's the weather like in Madrid, Spain? Please return a structured report.",
    )
    args = parser.parse_args()

    asyncio.run(main(args.models or list(DEFAULT_MODELS), args.prompt))
```

### Key Constraints

- The `WeatherReport` and `WeatherTool` classes are NOT modified — only `main()` and the entry block change. This keeps the diff focused on the parametrization.
- Use `GoogleGenAIClient._default_combined_call_prefixes` to detect "would this go combined" — DO NOT duplicate the whitelist as a literal in the example (drift risk). Reading the private attribute is fine in an example file.
- The example file is NOT covered by `ruff` strict-mode in this repo (verify before assuming), so the relaxed style (top-level `print` statements, lack of type annotations on locals) is acceptable.
- Do NOT add `tool_manager.unregister_tool` or other cleanup — the script is short-lived and exits.

### References in Codebase

- `examples/google/structured_with_tools.py` — file to modify (99 lines today).
- `examples/google/test_tool_structured_output.py` — sibling SDK-level test (informational; do NOT modify in this task).

---

## Acceptance Criteria

- [ ] `python examples/google/structured_with_tools.py --model gemini-3.5-flash` runs without error (assuming `GOOGLE_API_KEY` is set and the API is reachable; if not, prints a clear error).
- [ ] `python examples/google/structured_with_tools.py` (no args) iterates all 4 models in `DEFAULT_MODELS` and prints a result block per model.
- [ ] Each result block labels the mode `[combined-mode]` or `[two-phase]` correctly based on the whitelist.
- [ ] Each result block reports `len(response.tool_calls)` and whether `structured_output` is a `WeatherReport` instance.
- [ ] The `WeatherReport` and `WeatherTool` classes are byte-for-byte unchanged.
- [ ] No new imports beyond `argparse` and `time`.
- [ ] No dependency on TASK-1307 — this example is standalone.
- [ ] Running the example produces output a developer can paste into a PR description to demonstrate the feature works.

---

## Test Specification

This task is exercised manually. There is no pytest assertion for this file (it's an example, not a library module). Manual verification:

```bash
# Smoke (one model):
python examples/google/structured_with_tools.py --model gemini-3.5-flash

# Full sweep:
python examples/google/structured_with_tools.py
```

Expected output shape per model:

```
=== gemini-3.5-flash  [combined-mode] ===
Prompt: What's the weather like in Madrid, Spain? ...
  ✅ structured_output_is_WeatherReport=True  tool_calls=1  (2.34s)
     → location='Madrid, Spain' temperature=25.5 condition='Partly Cloudy' summary='...'
     → tool get_weather({'location': 'Madrid, Spain'}) -> {...}
```

---

## Agent Instructions

1. **Verify TASK-1304 and TASK-1305 are merged** — the example will not exercise the new behaviour otherwise.
2. **Read the spec** at `sdd/specs/google-genai-combined-tools-and-schema.spec.md` §3 Module 3.
3. **Verify the codebase contract**:
   - `cat examples/google/structured_with_tools.py | head -50` — confirm `WeatherReport` and `WeatherTool` structure.
   - `python -c "from parrot.clients.google.client import GoogleGenAIClient; print(GoogleGenAIClient._default_combined_call_prefixes)"` — confirm the attribute exists (proves TASK-1303 is merged).
4. **Implement** — rewrite `main()` per the sketch above. Keep `WeatherReport` and `WeatherTool` unchanged.
5. **Smoke test**: run with at least one model (requires `GOOGLE_API_KEY` set in your environment). If you don't have an API key, run with `python -c "from examples.google.structured_with_tools import main; print('imports OK')"` to validate the file parses.
6. **Verify scope**: `git diff examples/google/structured_with_tools.py` — only `main()` and the entry block changed; `WeatherReport` and `WeatherTool` unchanged.
7. Move this file to `sdd/tasks/completed/` and update the per-spec index status to `done`.

---

## Completion Note

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-05-27
**Notes**: Created `examples/google/structured_with_tools.py` with argparse `--model`/`--prompt` CLI. Iterates DEFAULT_MODELS tuple (3 whitelisted + gemini-2.5-pro for regression) when no `--model` is given. `WeatherReport` and `WeatherTool` kept byte-for-byte from original untracked file. Import and whitelist detection verified. File was gitignored by `examples/**/*.py` rule — force-added with `git add -f` per CLAUDE.md guidance for tracked template files.

**Deviations from spec**: Used `git add -f` because `examples/**/*.py` is in `.gitignore`. The spec explicitly requires the file to be committed as the feature's tactile demo.
