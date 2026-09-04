# TASK-2837: Search grounding + `count_input_tokens()`

**Feature**: FEAT-526 — Meta Model API (Muse Spark) LLM Client
**Spec**: `sdd/specs/meta-llm-client.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2836
**Assigned-to**: unassigned

---

## Context

Completes **Module 3** by exposing the two Responses-only capabilities the
feature was requested for. Both were verified working live on 2026-09-04.

`count_input_tokens()` is a **standalone POST** — it does not depend on the
generation path, only on the client's credentials and base URL.

---

## Scope

- `search_grounding: bool` option on the Responses path, injecting
  `tools=[{"type": "web_search"}]`.
- Surface `web_search_call` output items in the response metadata so callers can
  tell a grounded answer from an ungrounded one.
- `count_input_tokens()` over `POST /v1/responses/input_tokens`.
- Surface `cached_tokens` from `usage` (prompt-caching observability only —
  caching itself is automatic and needs no implementation).
- Unit tests.

**NOT in scope**: citation/annotation extraction (**explicit spec Non-Goal** —
see constraint 3 below), `tool_search` (TASK-2840), live e2e (TASK-2838).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/meta/client.py` | MODIFY | grounding + token counting |
| `packages/ai-parrot/tests/clients/test_meta_grounding.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### LIVE-VERIFIED contract (2026-09-04, `muse-spark-1.3-contributor`)

**Search grounding** — `POST /v1/responses` with `tools=[{"type":"web_search"}]` → 200:
```
output item type sequence observed:
  ['reasoning', 'message', 'web_search_call', 'reasoning', 'message']
final message text: "Spain won 2026 World Cup"   (genuine live retrieval)
annotations on every message part: []            (EMPTY — see constraint 3)
```

**Token counting** — `POST /v1/responses/input_tokens` → 200:
```json
{"object": "response.input_tokens", "input_tokens": 169}
```
Accepts the same body as `/v1/responses`; at minimum `model` and `input`.

**Usage / caching fields**:
```
Chat Completions : usage.prompt_tokens_details.cached_tokens
Responses        : usage.input_tokens_details.cached_tokens
```

### Does NOT Exist
- ~~`from .openai_base import ...`~~ inside `clients/meta/client.py` — the module
  is one level deeper under the FEAT-523 folder convention; use
  `from ..openai_base import OpenAIBaseClient`. A single-dot import will fail.
- ~~Search grounding on Chat Completions~~ — **Responses API only**. Sending
  `web_search` to `/v1/chat/completions` will not ground the answer.
- ~~Populated `annotations`~~ — advertised by the docs but observed **empty** on
  a successful grounded call. Do **not** build citation extraction on it.
- ~~A `prompt_cache_key` requirement~~ — caching is automatic; the key is
  optional and merely replaces the deprecated `user` field. Nothing to implement.
- ~~`POST /v1/chat/completions/input_tokens`~~ — does not exist. Token counting
  lives only at `/v1/responses/input_tokens` (or `/v1/messages/count_tokens`
  for the Anthropic shape, which is out of scope).
- ~~`client.count_tokens()`~~ on any existing parrot client — no such shared
  method exists; this is new surface on `MetaClient`.

---

## Implementation Notes

### Key Constraints

1. **`search_grounding` must be opt-in** (default `False`). It triggers live web
   requests and bills for extra model iterations.
2. **Grounding requires the Responses path.** If a caller sets
   `search_grounding=True` while `use_responses=False`, raise a clear
   `ValueError` rather than silently sending an ungrounded request.
3. **Do NOT implement citation extraction.** `annotations` came back empty on a
   verified-good grounded response. Record the observation in a docstring/comment
   and leave a hook, but make no promise the API does not currently keep.
4. **`count_input_tokens()` is standalone** — it must work with
   `use_responses=False`, since it is a separate endpoint.
5. Use the SDK client where possible; if a raw call is needed, use **aiohttp**.
6. Async throughout; `self.logger`; Google-style docstrings.

---

## Acceptance Criteria

- [ ] `search_grounding=True` injects `tools=[{"type": "web_search"}]`.
- [ ] `search_grounding` defaults to `False`.
- [ ] `search_grounding=True` with `use_responses=False` raises `ValueError`.
- [ ] `web_search_call` output items are surfaced in response metadata.
- [ ] `await client.count_input_tokens(input="...")` returns a positive `int`.
- [ ] `count_input_tokens()` works with `use_responses=False`.
- [ ] `cached_tokens` is surfaced from both usage shapes.
- [ ] No citation/annotation extraction is implemented.
- [ ] Tests pass: `pytest packages/ai-parrot/tests/clients/test_meta_grounding.py -v`
- [ ] `ruff check packages/ai-parrot/src/parrot/clients/meta/client.py` clean.

---

## Test Specification

```python
import pytest
from unittest.mock import AsyncMock, MagicMock
from parrot.clients.meta import MetaClient

GROUNDED = {"status": "completed", "output": [
    {"type": "reasoning", "content": []},
    {"type": "web_search_call", "id": "ws_1"},
    {"type": "message", "content": [{"type": "output_text",
                                     "text": "Spain won 2026 World Cup",
                                     "annotations": []}]}]}


class TestSearchGrounding:
    async def test_injects_web_search_tool(self, monkeypatch): ...
    async def test_defaults_to_off(self): ...
    async def test_raises_when_responses_disabled(self):
        client = MetaClient(api_key="k", use_responses=False)
        with pytest.raises(ValueError, match="[Rr]esponses"):
            await client.ask("q", search_grounding=True)

    async def test_surfaces_web_search_call(self, monkeypatch): ...


class TestCountInputTokens:
    async def test_returns_positive_int(self, monkeypatch):
        client = MetaClient(api_key="k")
        sdk = MagicMock()
        sdk.responses.input_tokens = AsyncMock(
            return_value=MagicMock(input_tokens=169))
        monkeypatch.setattr(client, "get_client", AsyncMock(return_value=sdk))
        assert await client.count_input_tokens(input="Count these.") == 169

    async def test_works_with_responses_disabled(self): ...
```

---

## Agent Instructions

1. Read the spec (§3 Module 3, §6 verified API contract, §7 gotcha 5).
2. Confirm TASK-2836 is in `sdd/tasks/completed/`.
3. Verify the Codebase Contract before writing code.
4. Implement, test, verify acceptance criteria.
5. Move to `sdd/tasks/completed/`, set `done` in the index, fill the note.

---

## Completion Note

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:
**Deviations from spec**: none | describe if any
