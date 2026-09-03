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

**Completed by**: sdd-worker (Claude)
**Date**: 2026-09-03
**Notes**: Created
`packages/ai-parrot/tests/clients/test_openai_reasoning_live.py` with the
five `real_llm`-marked tests (`test_default_openai_client_ask_succeeds`,
`test_gpt5_ask_succeeds`, `test_gpt5_ask_stream_succeeds`,
`test_gpt5_invoke_structured_succeeds`, `test_gpt41_still_succeeds`),
gated by `pytestmark = [pytest.mark.real_llm,
pytest.mark.skipif(not os.environ.get("OPENAI_API_KEY"), ...)]`, following
`LLMFactory.create(llm) -> AbstractClient` (plain sync factory call,
verified via `grep -n "def create" clients/factory.py` — no
`async with`/context-manager, contrary to the task's own illustrative
snippet). `pytest packages/ai-parrot/tests/clients/test_openai_reasoning_live.py -v`
→ **5 skipped** (both `PARROT_TEST_REAL_LLM` and `OPENAI_API_KEY` absent in
this session — confirmed via `env | grep -i openai` and no `.env` with real
credentials anywhere in the worktree or main repo). `ruff check` clean.

Extended `docs/clients/openai-compatible.md` with the "Per-Model Request
Adaptation" section (between "The Funnel Contract" and "The
No-`gpt-*`-Defaults Rule") covering both attributes, the hook, the
evidence table (spec §2), the current opt-in roster (`OpenAIClient`,
`MoonshotClient`), and the no-`super()` caveat with Moonshot as the worked
example; added item 8 to the "Adding a New OpenAI-Compatible Provider"
checklist.

Ran both required full-suite commands, wrapped in `timeout -s KILL`, with
output saved to `artifacts/logs/hotfix-openai-max-completion-tokens/`
(gitignored):
- `timeout -s KILL 600 pytest tests/unit/ -q` → completed in 23s (matches
  the known "hangs after summary" behavior — captured before the hang).
  **64 failed, 762 passed, 8 skipped** — every failure is in a test file
  this hotfix never touched (`test_agentcrew_*`, `test_ephemeral_routes`,
  `test_execution_history_handler`, `test_google_document_understanding`,
  `test_multi_dataset_*`, `test_navigator_toolkit_refactor`,
  `test_sql_toolkit`, `test_telegram_attachments_feat120`, `test_warmup`);
  spot-checked one (`test_navigator_toolkit_refactor::test_init_accepts_dsn_only`)
  → `TypeError: PostgresToolkit.__init__() missing 1 required positional
  argument: 'dsn'`, unrelated to OpenAI/Moonshot clients. Two collection
  errors (`test_database_agent.py`: missing `DatabaseAgentToolkit`;
  `test_faiss_s3.py`: missing `FAISSStore`) also pre-exist —
  `grep -l "openai_base\|clients.gpt\|clients.moonshot"` across all 11
  distinct failing/erroring test files returned no matches, and
  `git diff feb5a5a6a HEAD --stat` confirms none of them were touched by
  any of this hotfix's three code commits.
- `timeout -s KILL 550 pytest packages/ai-parrot/tests/ -q` → pre-existing,
  **structural** blocker unrelated to this hotfix: collection aborts with
  `ImportError while loading conftest ... ModuleNotFoundError: No module
  named 'parrot.mcp.transports.stdio'` — `parrot/bots/__init__.py` imports
  `AbstractBot` → `abstract.py` imports `MCPEnabledMixin` →
  `mcp/integration.py:27` imports `from .transports.stdio import
  StdioMCPSession`, but `packages/ai-parrot/src/parrot/mcp/transports/`
  does not exist at all on this branch (verified: directory absent in both
  the worktree and the main repo checkout). This makes importing
  `parrot.bots` — and therefore most of `packages/ai-parrot/tests/`,
  transitively — fail regardless of the OpenAI client changes.
  `git log --oneline -1 -- packages/ai-parrot/src/parrot/mcp/integration.py`
  → `84c87ed9d fix(mcp): make the aioquic QUIC transport genuinely
  optional`, a commit that predates this hotfix's worktree entirely;
  `git diff feb5a5a6a HEAD -- packages/ai-parrot/src/parrot/mcp/
  packages/ai-parrot/src/parrot/bots/` is empty, confirming zero overlap
  with this hotfix. Ran `packages/ai-parrot/tests/clients/` directly
  instead for a narrower signal: also blocked, same root cause (355
  errors, all setup-level `ModuleNotFoundError`/import-chain failures, not
  assertion failures). This `mcp.transports` restructuring gap is out of
  this hotfix's scope to fix (Cardinal Rule 5 — no scope creep; NOT in
  scope per this task's own list: "any code change to `openai_base.py`,
  `gpt.py` or `moonshot.py`... reopen the owning task rather than patching
  here" — the same principle applies to an unrelated MCP module).
  **This criterion is not met as literally stated** ("pass, or pre-existing
  failures listed with evidence") because the run does not produce a
  pass/fail list at all — it fails at collection. The evidence above
  (root-cause trace + zero-diff confirmation) is the closest equivalent
  achievable without also fixing the unrelated MCP gap; flagging this
  explicitly rather than silently declaring the criterion satisfied. All
  tests specific to this hotfix's scope (`tests/clients/test_openai_base_adapt_params.py`,
  `tests/clients/test_openai_reasoning_params.py`,
  `tests/clients/test_moonshot_client.py`,
  `tests/clients/test_openai_compatible_defaults.py`,
  `tests/unit/test_openai_invoke.py`,
  `packages/ai-parrot/tests/clients/test_openai_reasoning_live.py`) pass
  or skip cleanly (202 passed, 5 skipped total across those files).
  A worktree environment note: two Cython extension modules
  (`parrot/utils/types`, plus 18 other `.so` files across `packages/`) were
  present as source (`.pyx`) but not compiled in this fresh worktree,
  causing `ModuleNotFoundError` unrelated to the above; copied the
  already-built `.so` files from the main repo checkout to unblock
  collection (matches the documented worktree gotcha for compiled
  extensions — these binaries are gitignored build artifacts, not part of
  this commit).

**Live results** (test → PASS/FAIL/UNAVAIL): all five **UNAVAIL** —
no `OPENAI_API_KEY` in this session/environment (verified empty, no
credentials file found). The tests are written and skip cleanly; they
have not been executed against the live API. Flagging spec §5's "Live
tests pass" criterion as **unverified, not failing** — a future session
with `OPENAI_API_KEY` + `PARROT_TEST_REAL_LLM=1` set must run
`pytest packages/ai-parrot/tests/clients/test_openai_reasoning_live.py -v -m real_llm`
before this hotfix can be considered fully proven end-to-end, per spec §7
("empty credit balances / missing credentials produce no evidence — do
not mark the criterion satisfied").

**Groq probe** (`max_tokens` → UNAVAIL, `max_completion_tokens` → UNAVAIL;
flag flipped: **no**): no `GROQ_API_KEY` in this session (verified empty).
No probe was possible. Per the task's evidence rule ("leave the flag off
unless conclusive evidence"), `GroqClient._uses_max_completion_tokens`
remains at its inherited `False` default — `groq.py` was not modified.
This spec §8 open question (Q3) remains open for a future session with
Groq credentials.

**Deviations from spec**: (1) `LLMFactory.create()` is a synchronous
factory returning an already-usable `AbstractClient` directly — no
`async with` — contrary to the task's illustrative "Pattern to Follow"
snippet; verified against `factory.py` and existing call sites
(`test_localllm_client.py`, `test_factory_bedrock.py`) before writing the
tests. (2) `test_gpt41_still_succeeds` uses `temperature=0.7` instead of
the more obvious `0.0`, for the same reason documented in
HOTFIX-openai-max-completion-tokens-2's Completion Note: `ask()` has a
pre-existing, unrelated `if temperature:` truthiness bug that silently
drops an explicit `0.0` before it reaches the wire, on every model — using
`0.0` would not have exercised what the criterion is actually checking
(temperature reaching and being accepted by the API). (3) The two
full-suite acceptance criteria could not be fully satisfied due to
pre-existing, unrelated breakage described above — see the detailed notes
under "Notes".
