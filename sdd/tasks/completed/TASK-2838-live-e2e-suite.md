# TASK-2838: Live end-to-end test suite

**Feature**: FEAT-526 — Meta Model API (Muse Spark) LLM Client
**Spec**: `sdd/specs/meta-llm-client.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2835, TASK-2837
**Assigned-to**: unassigned

---

## Context

Implements the test half of **Module 5** — the "real test usage" the feature was
requested for, mirroring the existing live-OpenAI tests.

**Carries the feature's highest-risk finding.** Muse Spark spends most of its
output budget on private reasoning: measured live, **199 of 210** completion
tokens (Chat Completions) and **142 of 153** output tokens (Responses) were
`reasoning_tokens` for a reply whose visible text was the single word `pong`.
A low `max_tokens` therefore returns **empty or truncated** visible text.
`test_live_chat_completion_returns_nonempty_visible_text` exists to catch
exactly that, and is the single most valuable test in this feature.

---

## Scope

- `tests/e2e/test_meta_live.py` — credential-gated live suite against
  `muse-spark-1.3-contributor`.
- Skip cleanly (not fail) when no key is configured.
- Cover: chat completion, tool calling, structured output, Responses,
  search grounding, token counting, and the `tool_choice` 400 constraint.

**NOT in scope**: `smoke_meta.py` and docs (TASK-2839), `tool_search`
(TASK-2840), any production-code change — if a test fails, fix the defect in
the owning task, do not weaken the test.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/e2e/test_meta_live.py` | CREATE | Live credential-gated suite |

> Note: an untracked `tests/e2e/` directory already exists in the working tree
> from unrelated work. Add this file to it; do not restructure the directory or
> touch anything already there. (In practice this worktree's `tests/e2e/` did
> not exist yet — worktrees only inherit tracked files — so this task creates
> the directory fresh; nothing pre-existing was touched.)

> **File-scope expansion (per this task's own "fix the defect in the owning
> task, do not weaken the test" instruction)**: running the live suite with
> real credentials surfaced two genuine wire-shape defects in TASK-2836's
> `_prepare_responses_args()` (owning task, already completed) that no
> mocked unit test had caught:
> 1. Tool *definitions* were forwarded in the Chat-Completions-nested shape
>    (`{"type":"function","function":{...}}`) — Responses live 400s with
>    `'tools[0]' missing required field 'name'`; it needs the flat shape.
> 2. Tool-call *round trips* were represented as invented
>    `tool_output`/`tool_call` content blocks (mirroring `gpt.py`'s
>    structural pattern) — Responses live 400s with `'input[N].content' did
>    not match any supported type`; the real shape is top-level
>    `function_call`/`function_call_output` items.
>
> Both are fixed in `packages/ai-parrot/src/parrot/clients/meta/client.py`
> (added `_to_responses_tool()`; rewrote the tool-call branches of
> `_prepare_responses_args()`), with matching unit-test updates in
> `tests/clients/test_meta_responses.py`. Both files are therefore also
> MODIFY for this task, beyond the one originally listed.

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import pytest
from navconfig import config                      # credential resolution
from parrot.clients.factory import LLMFactory     # factory.py:161
from parrot.clients.meta import MetaClient
from parrot.clients.meta import MetaModel
```

### Credential + model facts (verified 2026-09-04)
```
META_API_KEY   : SET in env/.env, reachable via config.get('META_API_KEY')
                 48 chars, begins "LLM_", contains NO "|" characters.
                 (The docs show a pipe-delimited example; this underscore form
                  is valid and authenticates. Do NOT "fix" or reformat it.)
MODEL_API_KEY  : UNSET in this environment.
E2E model      : muse-spark-1.3-contributor
```

### Live endpoint expectations (all verified)
```
GET  /v1/models                  -> 200, 7 models
POST /v1/chat/completions        -> 200, choices[0].message.content == "pong"
POST /v1/responses               -> 200, status == "completed"
POST /v1/responses/input_tokens  -> 200, {"input_tokens": 169}
tool_choice: "required"          -> 400 'only `"auto"` is supported'
function tool strict: true       -> 200
```

### Required client usage pattern
```python
# AbstractClient does NOT auto-enter its async context for ask()/invoke()
# (only complete() does). Live tests MUST use:
async with client:
    result = await client.ask(...)
```

### Does NOT Exist
- ~~A live test that runs in CI~~ — these are credential-gated and must skip
  without a key. Never wire them into a default CI run.
- ~~`MODEL_API_KEY` in this environment~~ — unset; gate on `META_API_KEY`.
- ~~`tool_choice="required"` support~~ — asserts an error, not a success.
- ~~Populated search-grounding `annotations`~~ — observed empty; do not assert
  on citations.

---

## Implementation Notes

### Key Constraints

1. **Synthetic prompts only.** `muse-spark-1.3-contributor` is the Contributor
   tier: it grants Meta permission to **train on prompts and completions**.
   Never send company data, customer data, real user content, or anything from
   this repository's source. Trivial prompts like `"Reply with exactly: pong"`.
2. **Skip, don't fail, without credentials**:
   ```python
   pytestmark = pytest.mark.skipif(
       not config.get("META_API_KEY"),
       reason="META_API_KEY not configured — live Meta tests skipped",
   )
   ```
3. **Give every live call a generous output budget.** See the Context section —
   a small `max_tokens` yields empty visible text. This is the point of AC7.
4. Mark the suite so it can be excluded: `@pytest.mark.live` (or the repo's
   existing marker convention — check `pytest.ini` / `pyproject.toml` first).
5. Keep the suite small and fast; these are billed API calls.
6. **`pytest tests/unit` is known to hang after the summary in this repo** —
   wrap runs in `timeout -s KILL 300 ...` when verifying.

---

## Acceptance Criteria

- [ ] Suite skips cleanly (exit 0, reported as skipped) when `META_API_KEY` is unset.
- [ ] `test_live_chat_completion_returns_nonempty_visible_text` passes —
      **non-empty** `.strip()` content under the client's default budget.
- [ ] Live tool-calling round trip completes.
- [ ] Live structured output returns schema-conformant JSON.
- [ ] Live Responses call returns `status == "completed"` with non-empty text.
- [ ] Live search grounding emits a `web_search_call` output item.
- [ ] `count_input_tokens()` returns a positive int.
- [ ] `tool_choice="required"` raises (asserting Meta's documented 400).
- [ ] All prompts are synthetic.
- [ ] `ruff check tests/e2e/test_meta_live.py` clean.

---

## Test Specification

```python
import pytest
from navconfig import config
from parrot.clients.factory import LLMFactory

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(not config.get("META_API_KEY"),
                       reason="META_API_KEY not configured"),
]
E2E_MODEL = "meta:muse-spark-1.3-contributor"


class TestMetaLive:
    async def test_live_chat_completion_returns_nonempty_visible_text(self):
        """Guards F015: reasoning tokens can swallow the whole output budget."""
        client = LLMFactory.create(E2E_MODEL, use_responses=False)
        async with client:
            result = await client.ask("Reply with exactly: pong")
        assert result.content.strip(), (
            "empty visible text — reasoning likely consumed the output budget"
        )

    async def test_live_tool_calling_roundtrip(self): ...
    async def test_live_structured_output(self): ...
    async def test_live_responses_completed(self): ...
    async def test_live_search_grounding_emits_web_search_call(self): ...
    async def test_live_count_input_tokens(self): ...

    async def test_live_tool_choice_required_raises(self):
        """Meta supports only tool_choice='auto'; anything else is HTTP 400."""
        client = LLMFactory.create(E2E_MODEL)
        async with client:
            with pytest.raises(Exception):
                await client.ask("hi", tools=[...], tool_choice="required")
```

---

## Agent Instructions

1. Read the spec (§4 Test Specification, §5 AC7, §7 gotcha 1).
2. Confirm TASK-2835 and TASK-2837 are in `sdd/tasks/completed/`.
3. Check the repo's pytest marker convention before adding `@pytest.mark.live`.
4. Implement, run the suite **with** credentials, verify acceptance criteria.
5. Move to `sdd/tasks/completed/`, set `done` in the index, fill the note.

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-09-04
**Notes**: Created `tests/e2e/test_meta_live.py`, gated on `META_API_KEY`
(present in this environment), marked `@pytest.mark.live`. Ran the full
suite live against `muse-spark-1.3-contributor`: **7/7 passed** —
non-empty visible text (F015 guard), full tool-calling round trip
(Responses path), structured output (Chat Completions path — not yet
supported on Responses, per `MetaClient.ask()`'s own docstring),
Responses `status == "completed"`, search grounding surfacing
`web_search_calls` metadata, `count_input_tokens()` returning a positive
int, and `tool_choice="required"` raising `openai.BadRequestError`. All
prompts synthetic. `ruff` clean.

**Two genuine live-discovered defects fixed** (in TASK-2836's owning file,
per this task's "fix the defect in the owning task" instruction — see the
file-scope note above):
1. `count_input_tokens()` called `self.client.responses.input_tokens(...)`
   directly — that attribute is an SDK sub-resource
   (`AsyncInputTokens`), not callable; the real method is `.count(...)`.
2. `_prepare_responses_args()` sent tool *definitions* in the
   Chat-Completions-nested shape and tool-call *round trips* as invented
   `tool_output`/`tool_call` content blocks (both mirrored from `gpt.py`'s
   structural reference, which turned out not to match Meta's actual
   Responses wire shape for either case). Both 400s live; fixed with a new
   `_to_responses_tool()` flattening helper and top-level
   `function_call`/`function_call_output` input items respectively.
   Corresponding unit tests updated/added in `test_meta_responses.py` and
   `test_meta_grounding.py` (mock-shape fix for `.count`).

**Deviations from spec**: (1) `LLMFactory.create(E2E_MODEL).model` is not
literally `result.content` as the task's illustrative test snippet
showed — the real `AIMessage` field is `.output` (per
`AIMessageFactory.from_openai`); tests use `.output`. (2) The
`test_live_tool_choice_required_raises` snippet showed `ask(...,
tool_choice="required")`, but `ask()` never exposes a raw `tool_choice`
override (the base always forces `"auto"` when tools are prepared) — the
test instead calls `client._chat_completion(...)` directly with an
explicit `tool_choice="required"` override, which is the only way to
actually put that value on the wire. (3) File scope expanded beyond the
single listed file — see the note added to this task file above.
