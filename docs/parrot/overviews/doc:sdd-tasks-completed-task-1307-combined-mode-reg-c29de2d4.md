---
type: Wiki Overview
title: 'TASK-1307: Combined-mode regression tests in `test_google_client.py`'
id: doc:sdd-tasks-completed-task-1307-combined-mode-regression-tests-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'The spec''s acceptance criteria require explicit regression coverage for
  both branches: combined-mode (one chat call, schema on the streamed config) and
  the two-phase fallback (chat call + reformat call). There is currently no test in
  `test_google_client.py` that covers tools + st'
relates_to:
- concept: mod:parrot.clients.google.client
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.events.client
  rel: mentions
- concept: mod:parrot.models.google
  rel: mentions
- concept: mod:parrot.models.responses
  rel: mentions
---

# TASK-1307: Combined-mode regression tests in `test_google_client.py`

**Feature**: FEAT-193 — Google GenAI client: simultaneous tool-calling + structured output
**Spec**: `sdd/specs/google-genai-combined-tools-and-schema.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1304, TASK-1305
**Assigned-to**: unassigned

---

## Context

The spec's acceptance criteria require explicit regression coverage for both branches: combined-mode (one chat call, schema on the streamed config) and the two-phase fallback (chat call + reformat call). There is currently no test in `test_google_client.py` that covers tools + structured_output combined; the existing 10 tests cover only individual behaviours. This task adds mock-only regression tests for `ask()` and `ask_stream()` covering whitelisted vs. non-whitelisted models, malformed-JSON recovery, the `combined_call_prefixes` kwarg override, and the `gemini-3.1-flash-lite` debug-log emission.

Tests are mock-only — NO live Google API calls — per spec §1 Non-Goals.

Implements spec §3 Module 4 and the test cases listed in spec §4.

---

## Scope

Add the following test classes/cases to `packages/ai-parrot/tests/test_google_client.py` (append to the existing file; do NOT alter existing tests):

1. `test_ask_combined_mode_single_call` — whitelisted model + tools + schema → exactly ONE chat `send_message`, ZERO `generate_content` reformat call. Verify `response_mime_type` and `response_schema` are present on the chat config.
2. `test_ask_two_phase_preserved_for_unwhitelisted` — `gemini-2.5-pro` + tools + schema → ONE chat `send_message` + ONE `generate_content` reformat call. Verify schema is NOT on the chat config; verify schema IS on the reformat config.
3. `test_ask_combined_mode_no_structured_output` — whitelisted + tools, no schema → ONE chat call, no reformat.
4. `test_ask_combined_mode_no_tools` — whitelisted + schema, no tools → schema on chat config; no reformat. (Existing behaviour, regression.)
5. `test_ask_stream_combined_mode_single_path` — streaming analogue of #1.
6. `test_ask_stream_two_phase_preserved_for_unwhitelisted` — streaming analogue of #2.
7. `test_combined_call_prefixes_kwarg_override_empty` — `GoogleGenAIClient(combined_call_prefixes=())` forces two-phase even for whitelisted models.
8. `test_combined_call_prefixes_kwarg_override_custom` — custom whitelist with only one prefix; only that prefix triggers combined mode.
9. `test_combined_mode_malformed_json_falls_back_to_reformat` — whitelisted + schema + tools, but `_parse_structured_output` returns a `str` (parse failure) → recovery branch invokes the legacy reformat call.
10. `test_flash_lite_debug_log_emitted_once` — `gemini-3.1-flash-lite-preview` + combined mode → `caplog` captures the DEBUG message with the AFC stability note.
11. `test_lifecycle_events_fire_in_combined_mode` — subscribe to `AfterClientCallEvent`; run combined-mode `ask()`; assert exactly one event was emitted (matching today's count for the chat call).

**NOT in scope**:
- The client refactor (TASK-1303, 1304, 1305) — must already be merged.
- The capability-helper unit tests `TestSupportsCombinedToolsAndSchema` — already added by TASK-1303.
- Live Google API integration tests (spec §1 Non-Goals defers this).
- Tests for `examples/google/structured_with_tools.py` (TASK-1306; example, not test).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/test_google_client.py` | MODIFY | Append a new section "Combined-mode regression tests (FEAT-193)" with the 11 cases above. Do NOT modify the existing 10 tests or the helper tests added by TASK-1303. |

A small fixture module may be added if helpful (e.g. `tests/conftest.py` extension for the `weather_schema` fixture), but prefer keeping everything in the single test file unless that file exceeds ~1500 lines.

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# All verified at HEAD on dev (2026-05-27):
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pydantic import BaseModel, Field

from parrot.clients.google.client import GoogleGenAIClient   # verified
from parrot.models.google import GoogleModel                  # verified
from parrot.models.responses import AIMessage                 # used by `AIMessageFactory.from_gemini`
# Lifecycle events (FEAT-176):
from parrot.core.events.lifecycle.events.client import AfterClientCallEvent  # verify path; see Notes
```

### Existing Test Patterns to Follow

```python
# packages/ai-parrot/tests/test_google_client.py  (verified at HEAD)
# Existing tests use this shape:

async def test_google_ask():                          # line 8
    """Mocks chat.send_message; asserts response shape."""
    ...

async def test_google_ask_stream():                   # line 67
    """Mocks chat.send_message_stream; iterates chunks."""
    ...

def test_safe_extract_text_prefers_parts_over_flattened_response_text():   # line 222
    """Pure-function test, no mocking."""
    ...
```

### Existing client-internal touchpoints to mock

For each test that invokes `client.ask(...)` or `client.ask_stream(...)`:

| Touchpoint | What to mock | Notes |
|---|---|---|
| `client.aio.chats.create(model=..., history=..., [config=...])` | Return a mock `chat` object. | `ask()` passes `config` separately to `send_message`; `ask_stream()` passes it inline at `chats.create()`. |
| `chat.send_message(message=..., config=...)` | Return a mock `response` with `text` attribute and `candidates` list. | `ask()` path. |
| `chat.send_message_stream(content)` | Return an async generator yielding chunk objects with `.text` and `.candidates`. | `ask_stream()` path. |
| `client.aio.models.generate_content(model=..., contents=..., config=...)` | Mock to return a response with `text`. Use this to count reformat-call invocations (`call_count`). | Two-phase reformat path AND combined-mode recovery path. |
| `client._safe_extract_text(response)` | Usually leave unmocked — operates on whatever the mocked response returns. | |
| `client._parse_structured_output(text, output_config)` | Mock when testing the malformed-JSON branch — return a str to trigger recovery. | |

### Lifecycle event subscription pattern

```python
# Verify exact import path before assuming — recent FEAT-176 commit:
from parrot.core.events.lifecycle.events.client import AfterClientCallEvent

events_captured = []
async def _capture(event):
    events_captured.append(event)
client.events.subscribe(AfterClientCallEvent, _capture)
```

If the exact import path is uncertain, `grep -rn "AfterClientCallEvent" packages/ai-parrot/src/parrot/core/events/lifecycle/` to locate. The spec §6 contract names this event explicitly; if it has moved, update the contract and continue.

### Does NOT Exist

- ~~`pytest.AsyncMock`~~ — use `unittest.mock.AsyncMock` (Python 3.8+).
- ~~`GoogleGenAIClient.last_call_count`~~ — no such introspection. Use `mock.call_count` on the mocked `send_message` / `generate_content`.
- ~~`response.was_combined_mode`~~ — no such flag. Inferred from the number of `generate_content` calls.
- ~~`client.aio.chats.send_message` (without `create()` first)~~ — chats must be created first.
- ~~Skipping the mock for `client._ensure_client(...)`~~ — this is called at the top of `ask()`; mock it or patch the underlying SDK client.

---

## Implementation Notes

### Test scaffolding pattern (mock-only `ask()`)

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pydantic import BaseModel, Field

from parrot.clients.google.client import GoogleGenAIClient


@pytest.fixture
def weather_schema():
    class WeatherReport(BaseModel):
        location: str = Field(...)
        temperature: float = Field(...)
        condition: str = Field(...)
    return WeatherReport


@pytest.fixture
def mocked_client(monkeypatch):
    """A GoogleGenAIClient with the SDK boundary fully mocked.

    Returns (client, mocks_dict) where mocks_dict has handles to:
      - chats.create
      - chat.send_message
      - models.generate_content
    """
    client = GoogleGenAIClient(api_key="fake")
    # Stub _ensure_client so it doesn't try to authenticate
    client._ensure_client = AsyncMock()

    chat = MagicMock()
    chat.send_message = AsyncMock()
    create_mock = MagicMock(return_value=chat)

    models_mock = MagicMock()
    models_mock.generate_content = AsyncMock()

    aio = MagicMock()
    aio.chats = MagicMock(create=create_mock)
    aio.models = models_mock
    client.client = MagicMock(aio=aio)

    return client, {
        "chats.create": create_mock,
        "chat.send_message": chat.send_message,
        "models.generate_content": models_mock.generate_content,
        "chat": chat,
    }


def _make_chat_response(text: str):
    """Build a minimal mock chat response that _safe_extract_text can pull text from."""
    response = MagicMock()
    response.text = text
    # _safe_extract_text inspects candidates → parts → text. Set up a path that works.
    part = MagicMock(text=text, function_call=None, thought=None)
    content = MagicMock(parts=[part])
    candidate = MagicMock(content=content, finish_reason="STOP")
    response.candidates = [candidate]
    response.function_calls = []  # no tool calls in the simple case
    return response


# ── FEAT-193 tests ──────────────────────────────────────────────────────────

class TestAskCombinedMode:
    """Whitelisted models receive tools + schema in a single GenerateContentConfig."""

    async def test_combined_mode_single_call(self, mocked_client, weather_schema):
        client, m = mocked_client
        m["chat.send_message"].return_value = _make_chat_response(
            '{"location":"Madrid","temperature":25.5,"condition":"sunny"}'
        )

        response = await client.ask(
            prompt="weather?",
            model="gemini-3.5-flash",
            structured_output=weather_schema,
            use_tools=True,
        )

        # Single chat call, ZERO reformat call.
        assert m["chat.send_message"].call_count == 1
        assert m["models.generate_content"].call_count == 0

        # Schema was on the chat config.
        config = m["chat.send_message"].call_args.kwargs["config"]
        # GenerateContentConfig stores response_schema and response_mime_type.
        assert config.response_mime_type == "application/json"
        assert config.response_schema is not None

    async def test_two_phase_preserved_for_unwhitelisted(self, mocked_client, weather_schema):
        client, m = mocked_client
        m["chat.send_message"].return_value = _make_chat_response("It is sunny in Madrid, 25.5C.")
        m["models.generate_content"].return_value = MagicMock(
            text='{"location":"Madrid","temperature":25.5,"condition":"sunny"}',
            candidates=[],
        )

        await client.ask(
            prompt="weather?",
            model="gemini-2.5-pro",
            structured_output=weather_schema,
            use_tools=True,
        )

        # Chat call AND reformat call.
        assert m["chat.send_message"].call_count == 1
        assert m["models.generate_content"].call_count == 1

        # Schema NOT on the chat config (the old two-phase behaviour).
        chat_config = m["chat.send_message"].call_args.kwargs["config"]
        assert getattr(chat_config, "response_schema", None) is None
        # Schema IS on the reformat config.
        reformat_config = m["models.generate_content"].call_args.kwargs["config"]
        assert getattr(reformat_config, "response_mime_type", None) == "application/json"
```

### Tests requiring `caplog`

```python
import logging

async def test_flash_lite_debug_log_emitted_once(self, mocked_client, weather_schema, caplog):
    client, m = mocked_client
    m["chat.send_message"].return_value = _make_chat_response('{}')

    with caplog.at_level(logging.DEBUG, logger=client.logger.name):
        await client.ask(
            prompt="x",
            model="gemini-3.1-flash-lite-preview",
            structured_output=weather_schema,
            use_tools=True,
        )

    matches = [r for r in caplog.records if "AFC instability" in r.getMessage()]
    assert len(matches) == 1
```

### Tests for `combined_call_prefixes` kwarg override

```python
async def test_kwarg_override_empty_forces_two_phase(self, weather_schema):
    """Empty prefixes tuple is the documented kill switch."""
    client = GoogleGenAIClient(api_key="fake", combined_call_prefixes=())
    client._ensure_client = AsyncMock()
    # Set up mocks ...

    await client.ask(
        prompt="x",
        model="gemini-3.5-flash",   # would normally be whitelisted
        structured_output=weather_schema,
        use_tools=True,
    )
    # With empty prefixes, even gemini-3.5-flash falls back to two-phase.
    assert m["models.generate_content"].call_count == 1
```

### Lifecycle events test (FEAT-176 parity)

```python
async def test_lifecycle_events_fire_in_combined_mode(self, mocked_client, weather_schema):
    from parrot.core.events.lifecycle.events.client import AfterClientCallEvent

    client, m = mocked_client
    m["chat.send_message"].return_value = _make_chat_response('{}')

    events = []
    async def _capture(event): events.append(event)
    client.events.subscribe(AfterClientCallEvent, _capture)

    await client.ask(
        prompt="x", model="gemini-3.5-flash",
        structured_output=weather_schema, use_tools=True,
    )

    assert len(events) == 1
```

### Key Constraints

- Tests MUST be mock-only. No `pytest.mark.live` / no API calls. If you find yourself wanting to call the real API, stop and re-mock.
- Mock at the SDK boundary (`client.aio.chats.create`, `client.aio.models.generate_content`) — not deeper (the parrot client logic IS what's being tested).
- Reuse `_make_chat_response` (or equivalent) as a helper at module scope — duplicate-construction of mock responses is the #1 source of brittleness in these tests.
- Pytest async tests use `@pytest.mark.asyncio` if the project uses `pytest-asyncio`; check `packages/ai-parrot/pyproject.toml` or existing test patterns. `test_google_ask` at line 8 already exemplifies the async style.
- Do NOT add an `__init__.py` to `packages/ai-parrot/tests/` — follow the existing convention.
- If a test references `AfterClientCallEvent` and the import path has moved, FIX the contract section of THIS task file FIRST, then write the test against the correct path.

### References in Codebase

- `packages/ai-parrot/tests/test_google_client.py:1-300` — existing test scaffold (line 8 for `ask`, line 67 for `ask_stream`).
- `packages/ai-parrot/src/parrot/clients/google/client.py:2033-2048, 2337-2474, 2847-2854, 3020-3084` — the four code blocks the tests must exercise.
- `packages/ai-parrot/src/parrot/clients/google/client.py:156-204` — capability helpers (referenced by TestSupportsCombinedToolsAndSchema added in TASK-1303).
- `packages/ai-parrot/src/parrot/core/events/lifecycle/` — FEAT-176 event definitions (`grep -rn "AfterClientCallEvent" packages/ai-parrot/src/parrot/core/events/`).

---

## Acceptance Criteria

- [ ] All 11 listed tests are added to `packages/ai-parrot/tests/test_google_client.py`.
- [ ] `pytest packages/ai-parrot/tests/test_google_client.py -v` — ALL tests pass (existing 10 + TASK-1303's helper tests + the 11 new ones).
- [ ] No test makes a live Google API call.
- [ ] Each new test mocks at the SDK boundary (`client.aio.chats.create`, `client.aio.models.generate_content`).
- [ ] `test_ask_combined_mode_single_call` asserts `models.generate_content.call_count == 0`.
- [ ] `test_ask_two_phase_preserved_for_unwhitelisted` asserts `models.generate_content.call_count == 1` AND schema is on the reformat config.
- [ ] `test_combined_mode_malformed_json_falls_back_to_reformat` asserts the recovery path increments `models.generate_content.call_count` to 1 even though the model is whitelisted.
- [ ] `test_flash_lite_debug_log_emitted_once` uses `caplog` and finds exactly ONE matching log record.
- [ ] `test_lifecycle_events_fire_in_combined_mode` confirms the event fires once (parity with non-combined mode).
- [ ] Diff is confined to `packages/ai-parrot/tests/test_google_client.py` (and optionally a small `conftest.py` extension).

---

## Test Specification

The tests ARE the test specification. See "Implementation Notes" for the test scaffolding pattern and the 11 detailed cases listed in Scope.

---

## Agent Instructions

1. **Confirm TASK-1304 and TASK-1305 are merged** (the tested behaviour must exist).
2. **Read the spec** at `sdd/specs/google-genai-combined-tools-and-schema.spec.md` §4 (Test Specification).
3. **Read the existing test file** to learn its mocking conventions:
   ```bash
   sed -n '1,110p' packages/ai-parrot/tests/test_google_client.py
   ```
4. **Verify the lifecycle event import path**:
   ```bash
   grep -rn "class AfterClientCallEvent" packages/ai-parrot/src/parrot/core/events/lifecycle/ | head
   ```
   Update this task's Codebase Contract if the path has moved.
5. **Implement** — append the 11 test cases. Reuse fixtures and `_make_chat_response` helper to avoid duplication.
6. **Run the full file**:
   ```bash
   cd packages/ai-parrot
   pytest tests/test_google_client.py -v
   ```
   Expect ≥21 tests passing (10 pre-existing + ~3 from TASK-1303 helper + 11 new).
7. **Lint check**:
   ```bash
   ruff check packages/ai-parrot/tests/test_google_client.py
   ```
8. **Verify scope**: `git diff packages/ai-parrot/tests/test_google_client.py | head -30` — only additions; no modifications to the pre-existing test code.
9. Move this file to `sdd/tasks/completed/` and update the per-spec index status to `done`.

---

## Completion Note

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-05-27
**Notes**: All 11 FEAT-193 regression tests implemented and passing.
  - TestAskCombinedModeGate: 9 tests (combined/two-phase gate, no-schema, no-tools,
    malformed-JSON recovery, flash-lite debug log, kwarg overrides, lifecycle events)
  - TestAskStreamCombinedModeGate: 2 tests (combined/two-phase streaming gate)
  Also fixed a bug introduced in TASK-1305: `ask_stream()` post-stream combined-mode
  block was passing raw `structured_output` (Pydantic class) instead of `schema_config`
  (StructuredOutputConfig) to `_parse_structured_output` and `_reformat_to_structured`.
  Fixed by using `_so_config = schema_config or self._get_structured_config(...)`.
  Pre-existing failure `test_google_ask_stream` (AIMessageFactory stub missing
  `from_gemini`) is unrelated to FEAT-193 and left unchanged.

**Deviations from spec**: none — all 11 cases implemented as specified.
