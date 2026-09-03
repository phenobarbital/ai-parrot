# HOTFIX-openai-max-completion-tokens-4: Live `real_llm` verification, Groq re-probe, and docs

**Feature**: hotfix `openai-max-completion-tokens` (no Jira ticket — user decision 2026-09-03) — OpenAI `max_completion_tokens` for reasoning models *(hotfix — no `FEAT-<NNN>` reserved, FEAT-466)*
**Spec**: `sdd/specs/openai-max-completion-tokens.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: HOTFIX-openai-max-completion-tokens-2, HOTFIX-openai-max-completion-tokens-3
**Assigned-to**: unassigned

---

## Context

Tasks 1-3 are verified with fake SDK clients. This defect survived a full
cross-provider matrix run precisely because a billing error masked the
parameter error (spec §7), so the acceptance criteria demand **live** proof
that the exact calls that 400 today now succeed, plus a regression guard for
`gpt-4.1`. This task also closes spec §8's open questions that need a live
signal (Groq opt-in) and documents the two new attributes so future
`OpenAIBaseClient` subclasses know when to set them (spec §5, docs criterion).

---

## Scope

- Create `packages/ai-parrot/tests/clients/test_openai_reasoning_live.py`
  with `@pytest.mark.real_llm` tests (auto-skipped unless
  `PARROT_TEST_REAL_LLM=1` by `packages/ai-parrot/tests/conftest.py:16`; add a
  second `pytest.mark.skipif` on missing `OPENAI_API_KEY`):
  - `test_default_openai_client_ask_succeeds` — `LLMFactory.create("openai").ask("Say OK.")`, the exact call that 400s on `main`
  - `test_gpt5_ask_succeeds` — `LLMFactory.create("openai:gpt-5-mini").ask(...)` returns non-empty content
  - `test_gpt5_ask_stream_succeeds` — drains `ask_stream()` on `gpt-5-mini` (closes spec §8 Q4: yes, cover it live — it is cheap and each path assembles kwargs separately)
  - `test_gpt5_invoke_structured_succeeds` — `invoke()` with a Pydantic `output_type` returns an instance of that model
  - `test_gpt41_still_succeeds` — `ask()` on `gpt-4.1` with `temperature=0.0` (regression guard: temperature is still sent and accepted)
- Run them: `PARROT_TEST_REAL_LLM=1 pytest packages/ai-parrot/tests/clients/test_openai_reasoning_live.py -v -m real_llm`
  and save the output under `artifacts/logs/hotfix-openai-max-completion-tokens/` (gitignored).
- **Groq re-probe** (spec §8 Q3): through `GroqClient` (its funnel wraps the
  native `AsyncGroq` SDK), send one request with `max_tokens` and one with
  `max_completion_tokens` to Groq's default model. Record the two results in
  the Completion Note. Leave `GroqClient._uses_max_completion_tokens` **off**
  unless `max_completion_tokens` returns 200 **and** `max_tokens` returns a
  parameter error — a 403/429/billing response is no evidence. If the flag
  is flipped, add `GroqClient` to task 2's opt-in test and exclude it from task
  1's defaults sweep.
- Docs: in `docs/clients/openai-compatible.md` add a subsection after
  "The Funnel Contract" (before "The No-`gpt-*`-Defaults Rule", line ~188)
  titled "Per-Model Request Adaptation" that documents
  `_uses_max_completion_tokens`, `_fixed_temperature_models`,
  `_adapt_completion_params()`, which clients opt in and why, the evidence
  table from spec §2, and the rule that a subclass overriding
  `_chat_completion` without `super()` must call the hook itself (Moonshot
  is the worked example). Also add one bullet to "Adding a New
  OpenAI-Compatible Provider" (line 208) telling authors to leave the flag
  off until their endpoint is probed.
- Run the full unit suites required by spec §5:
  `timeout -s KILL 600 pytest tests/unit/ -q` and
  `timeout -s KILL 600 pytest packages/ai-parrot/tests/ -q`
  (the `timeout` wrapper is required — `tests/unit` is known to hang after its
  summary line).

**NOT in scope**: any code change to `openai_base.py`, `gpt.py` or
`moonshot.py` (if a live test fails, the fix belongs to the owning task — reopen
it rather than patching here); enabling the flag on Z.ai, vLLM, LocalLLM,
OpenRouter or Mantle (not probed, spec §2); changing `_default_model`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/clients/test_openai_reasoning_live.py` | CREATE | Five `real_llm` tests |
| `docs/clients/openai-compatible.md` | MODIFY | New "Per-Model Request Adaptation" subsection + provider-checklist bullet |
| `packages/ai-parrot/src/parrot/clients/groq.py` | MODIFY (conditional) | Only if the Groq probe is conclusive in favour |
| `artifacts/logs/hotfix-openai-max-completion-tokens/live-run.log` | CREATE (gitignored) | Evidence of the live run |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `origin/main` at `feb5a5a6a` on 2026-09-03.

### Verified Imports
```python
from parrot.clients.factory import LLMFactory             # verified: packages/ai-parrot/src/parrot/clients/factory.py
from parrot.clients.gpt import OpenAIClient               # verified: clients/gpt.py:81
from parrot.clients.groq import GroqClient                # verified: clients/groq.py:50
from parrot.models.responses import InvokeResult          # verified: used at tests/unit/test_openai_invoke.py:7
from pydantic import BaseModel
```

### Existing Signatures to Use
```python
# packages/ai-parrot/tests/conftest.py:16-19 — the real_llm gate (package-local; the
#   repo-root tests/conftest.py has NO such gate, so live tests MUST live under
#   packages/ai-parrot/tests/)
#   """Skip tests marked real_llm unless PARROT_TEST_REAL_LLM=1 is set."""
#   if not os.environ.get("PARROT_TEST_REAL_LLM"): ... skip(reason="Set PARROT_TEST_REAL_LLM=1 to run real LLM tests")

# pyproject.toml:227-229 — `--strict-markers` is on; `real_llm` is registered:
#   "real_llm: mark a test as requiring a live LLM provider"

# Existing real_llm usages to copy the shape from:
#   packages/ai-parrot/tests/agents/test_obsidian.py
#   packages/ai-parrot/tests/outputs/a2ui/test_producer.py

# packages/ai-parrot/src/parrot/clients/gpt.py
class OpenAIClient(OpenAIBaseClient):        # line 81
    _default_model: str = "gpt-5-mini"       # line 89
    _lightweight_model: str = "gpt-4.1"      # line 91 — why `LLMFactory.create("openai").invoke()` passed on main

# docs/clients/openai-compatible.md headings (line numbers on origin/main)
#   168 ## The Funnel Contract
#   190 ## The No-`gpt-*`-Defaults Rule
#   208 ## Adding a New OpenAI-Compatible Provider
#   264 ## Live Smoke Testing
```

### Does NOT Exist
- ~~`packages/ai-parrot/tests/clients/test_structured_output_live_matrix.py`~~ — cited by the spec as "the pattern to copy"; **not on `main`**. Use the `conftest.py` gate + the two `real_llm` files listed above instead.
- ~~a `real_llm` gate in the repo-root `tests/conftest.py`~~ — only the package-local conftest has it; a `real_llm` test under `tests/` would run unconditionally
- ~~`OPENAI_API_KEY` handling in conftest~~ — add your own `skipif` for missing credentials
- ~~`GroqClient._uses_max_completion_tokens = True`~~ — off on `main`; only flip with conclusive evidence

---

## Implementation Notes

### Pattern to Follow
```python
# packages/ai-parrot/tests/clients/test_openai_reasoning_live.py
import os
import pytest
from pydantic import BaseModel
from parrot.clients.factory import LLMFactory

pytestmark = [
    pytest.mark.real_llm,
    pytest.mark.skipif(not os.environ.get("OPENAI_API_KEY"), reason="OPENAI_API_KEY not set"),
]


class _Verdict(BaseModel):
    answer: str


@pytest.mark.asyncio
async def test_default_openai_client_ask_succeeds():
    async with LLMFactory.create("openai") as client:      # confirm the factory's actual context-manager / creation API before use
        msg = await client.ask("Say OK.")
    assert msg.content.strip()
```
Verify `LLMFactory.create()`'s real signature and whether the returned client
needs `async with` (see how `packages/ai-parrot/tests/agents/test_obsidian.py`
obtains a live client) before writing the five tests.

### Key Constraints
- A billing/credit failure (`429 ... credits`) or a `403` is **not** a pass and
  **not** a fail — report it as `UNAVAIL` in the Completion Note and do not
  mark the criterion satisfied (spec §7, FEAT-481 convention).
- Never commit API keys or the raw log; `artifacts/` is gitignored.
- Wrap both full-suite runs in `timeout -s KILL 600` (known hang after summary).
- Docs must describe *when to set* the attributes, not just that they exist.

### References in Codebase
- `packages/ai-parrot/tests/conftest.py:16` — live gate
- `docs/clients/openai-compatible.md:168-206` — the section to extend
- `sdd/specs/openai-max-completion-tokens.spec.md` §2 evidence table, §8 open questions

---

## Acceptance Criteria

- [ ] Five live tests exist, are `real_llm`-marked, skip cleanly without `PARROT_TEST_REAL_LLM=1` or without `OPENAI_API_KEY`
- [ ] `PARROT_TEST_REAL_LLM=1 pytest packages/ai-parrot/tests/clients/test_openai_reasoning_live.py -v` → 5 passed (log saved under `artifacts/logs/hotfix-openai-max-completion-tokens/`)
- [ ] `LLMFactory.create("openai").ask("Say OK.")` returns content (spec §5 criterion 1)
- [ ] `gpt-4.1` passes with `temperature=0.0` sent (regression guard)
- [ ] Groq probe recorded; `GroqClient` flag state matches the evidence rule above
- [ ] `docs/clients/openai-compatible.md` documents both attributes, the hook, the opt-in roster, and the no-`super()` caveat
- [ ] `timeout -s KILL 600 pytest tests/unit/ -q` and `timeout -s KILL 600 pytest packages/ai-parrot/tests/ -q` pass (or pre-existing failures are listed in the Completion Note with evidence they fail on `origin/main` too)
- [ ] `ruff check packages/ai-parrot/tests/clients/test_openai_reasoning_live.py` clean

---

## Test Specification

See "Pattern to Follow" — extend to the five tests listed in Scope. For
`test_gpt5_ask_stream_succeeds` collect chunks into a list and assert the
joined text is non-empty; for `test_gpt5_invoke_structured_succeeds` assert
`isinstance(result.output, _Verdict)` (check `InvokeResult`'s attribute name at
`packages/ai-parrot/src/parrot/models/responses.py` first).

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — HOTFIX-openai-max-completion-tokens-2 and HOTFIX-openai-max-completion-tokens-3 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — confirm anchors on your branch
4. **Update status** in `sdd/tasks/index/openai-max-completion-tokens.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met — with the live log as evidence
7. **Move this file** to `sdd/tasks/completed/`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below (live results table + Groq probe table)

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Live results** (test → PASS/FAIL/UNAVAIL):

**Groq probe** (`max_tokens` → …, `max_completion_tokens` → …; flag flipped: yes/no):

**Deviations from spec**: none | describe if any
