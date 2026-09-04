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
> touch anything already there.

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

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:
**Deviations from spec**: none | describe if any
