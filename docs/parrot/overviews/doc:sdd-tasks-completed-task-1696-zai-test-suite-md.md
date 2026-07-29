---
type: Wiki Overview
title: 'TASK-1696: Test suite — Zai dispatcher/profile/registry tests, server wiring,
  Grok regression'
id: doc:sdd-tasks-completed-task-1696-zai-test-suite-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Module 5 of FEAT-269 (spec §3, §4). Locks in the whole feature with the
relates_to:
- concept: mod:parrot.clients.zai
  rel: mentions
- concept: mod:parrot.flows.dev_loop.dispatcher
  rel: mentions
- concept: mod:parrot.flows.dev_loop.models
  rel: mentions
- concept: mod:parrot.models.zai
  rel: mentions
---

# TASK-1696: Test suite — Zai dispatcher/profile/registry tests, server wiring, Grok regression

**Feature**: FEAT-269 — Z.ai Code Dispatcher for the Dev Loop (GLM-5.2)
**Spec**: `sdd/specs/zai-client-code.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1692, TASK-1693, TASK-1694, TASK-1695
**Assigned-to**: unassigned

---

## Context

Module 5 of FEAT-269 (spec §3, §4). Locks in the whole feature with the
test matrix from spec §4: registry assertions, profile validation, Z.ai-native
completion-args behavior, the Grok-mirror dispatch-loop tests, server
startup wiring, and the Grok `client_factory` regression.

---

## Scope

- CREATE `packages/ai-parrot/tests/flows/dev_loop/test_zai_code_dispatcher.py`
  with (names from spec §4, keep them verbatim):
  - `test_glm_5_2_in_enum_and_thinking_capable`
  - `test_zai_client_default_model_is_glm_5_2`
  - `test_zai_profile_defaults`
  - `test_zai_profile_model_syncs_llm`
  - `test_zai_profile_max_tokens_bounds`
  - `test_zai_completion_args_native_thinking`
  - `test_zai_completion_args_thinking_disabled`
  - `test_zai_thinking_warns_non_capable_model` (use `caplog`)
  - `test_zai_dispatch_runs_tool_loop_and_validates_final_output`
  - `test_zai_text_json_final_output_is_supported`
  - `test_zai_invalid_final_tool_payload_raises_validation_error`
  - `test_zai_cwd_outside_worktree_base_rejected`
  - `test_zai_client_factory_forwards_model_args`
- MODIFY `packages/ai-parrot/tests/flows/dev_loop/test_grok_code_dispatcher.py`:
  add `test_grok_client_factory_forwards_model_args` (regression for the
  TASK-1694 lambda fix; assert calling the default `_client_factory` with
  `model_args={"temperature": 0.0}` does not raise `TypeError` — stub
  `LLMFactory.create` via monkeypatch so no real client is built).
- MODIFY `packages/ai-parrot/tests/flows/dev_loop/test_server_repo_wiring.py`:
  - `test_server_zai_agent_startup` — mirror
    `test_server_grok_agent_startup` (line 158): set
    `DEV_LOOP_DEVELOPMENT_AGENT=zai` (+ `ZAI_API_KEY` dummy env), start the
    app factory, assert `development_dispatcher` is a `ZaiCodeDispatcher`
    and the profile is a `ZaiCodeDispatchProfile` with model `glm-5.2`,
    thinking on, effort `max`.
  - `test_server_invalid_agent_lists_zai` — invalid agent value raises
    `RuntimeError` whose message contains `'zai'`.
- The dispatch-loop tests mirror the Grok harness: a fake client whose
  `_ensure_client()` returns a fake SDK exposing
  `chat.completions.create(**kwargs)` that records kwargs and returns
  scripted OpenAI-shaped responses (assistant tool_calls turns, then
  `final_output`). Assert recorded kwargs contain
  `thinking`/`reasoning_effort` and NOT `extra_body`.

**NOT in scope**: implementation changes (if a test exposes a bug in
TASK-1692–1695 code, fix it in the touched module and note it in the
completion note), performance/benchmark tests, live API calls (everything
mocked; no `ZAI_API_KEY`-dependent network tests).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/flows/dev_loop/test_zai_code_dispatcher.py` | CREATE | 13 unit tests per spec §4 |
| `packages/ai-parrot/tests/flows/dev_loop/test_grok_code_dispatcher.py` | MODIFY | add factory regression test |
| `packages/ai-parrot/tests/flows/dev_loop/test_server_repo_wiring.py` | MODIFY | add 2 server wiring tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-07-03 against `dev` (implementation objects exist after
> TASK-1692…1695 — re-verify their final shapes before writing assertions).

### Verified Imports
```python
from parrot.models.zai import ZaiModel, THINKING_CAPABLE_ZAI_MODELS  # models/zai.py
from parrot.clients.zai import ZaiClient                             # clients/zai.py:22
from parrot.flows.dev_loop.dispatcher import (
    ZaiCodeDispatcher,           # after TASK-1694
    GrokCodeDispatcher,          # dispatcher.py:2565
    LLMCodeDispatcher,           # dispatcher.py:1721
    DispatchExecutionError, DispatchOutputValidationError,
)
from parrot.flows.dev_loop.models import ZaiCodeDispatchProfile      # after TASK-1693
import pytest
from pydantic import BaseModel, ValidationError
```

### Existing Signatures to Use
```python
# packages/ai-parrot/tests/flows/dev_loop/test_grok_code_dispatcher.py — THE HARNESS TO MIRROR
#   lines 107-119: fake-client factory + monkeypatch:
def _client_factory(*args: Any, **kwargs: Any) -> _FakeGrokClient:   # line 107
    ...
monkeypatch.setattr(disp, "_client_factory", _client_factory)        # line 119
#   test names to mirror:
#     test_grok_dispatch_runs_tool_loop_and_validates_final_output   # line 142
#     test_grok_text_json_final_output_is_supported                  # line 199
#     test_grok_invalid_final_tool_payload_raises_validation_error   # line 232
#     test_grok_cwd_outside_worktree_base_rejected                   # line 252
#   shared `brief` fixture lives in tests/flows/dev_loop/conftest.py

# packages/ai-parrot/tests/flows/dev_loop/test_server_repo_wiring.py
async def test_server_grok_agent_startup(monkeypatch) -> None:       # line 158 — template for the zai variant

# Dispatch loop expectations (dispatcher.py:1747-2100):
#   - cwd guard: _enforce_cwd_under_worktree_base(cwd) raises unless cwd is
#     under the configured worktree base (see how Grok's cwd test monkeypatches this)
#   - final result: model calls tool "final_output" with payload matching
#     output_model, OR returns plain-text JSON (validated by _validate_text_output)
#   - events XADD'd to Redis — Grok tests already handle/mock the redis client;
#     copy their approach (check the top of test_grok_code_dispatcher.py for
#     the redis stub / _publish_event handling)
```

### Does NOT Exist
- ~~live Z.ai network access in tests~~ — everything mocked; never require a
  real `ZAI_API_KEY` (use `monkeypatch.setenv("ZAI_API_KEY", "test-key")`
  where client construction demands one)
- ~~`_FakeZaiClient` / zai test fixtures~~ — created by this task
- ~~`client.client.chat...` path for Zai~~ — the Zai dispatcher calls
  `sdk = await client._ensure_client()` and uses the RETURN VALUE; the fake
  client must implement `async def _ensure_client(self)` returning the fake
  SDK (unlike Grok's fake, which exposes a `.client` attribute)
- ~~`pytest-recording`/VCR cassettes in this test dir~~ — plain
  pytest-asyncio + monkeypatch, per the existing files

---

## Implementation Notes

### Pattern to Follow
Copy `test_grok_code_dispatcher.py` structure wholesale (fixtures, fake
response objects, scripted turn sequences), adapting the fake client to the
Zai contract: `_ensure_client()` → fake SDK object with
`chat.completions.create(**kwargs)` recording `kwargs` into a list the test
asserts on (`thinking`, `reasoning_effort` present; `extra_body` absent).

### Key Constraints
- `pytest-asyncio` conventions as used by the sibling files (check their
  markers/decorators and match).
- Warning assertion via `caplog.at_level(logging.WARNING)`.
- Profile bound tests: `pytest.raises(ValidationError)` for 131073, 255,
  and `reasoning_effort="turbo"`.
- Keep test names EXACTLY as listed in spec §4 (traceability to acceptance
  criteria).
- Run with venv activated: `source .venv/bin/activate` first (repo rule).

### References in Codebase
- `packages/ai-parrot/tests/flows/dev_loop/test_grok_code_dispatcher.py` — harness
- `packages/ai-parrot/tests/flows/dev_loop/test_llm_code_dispatcher.py` — base-loop coverage (don't duplicate)
- `packages/ai-parrot/tests/flows/dev_loop/conftest.py` — shared fixtures
- `sdd/specs/zai-client-code.spec.md` §4 — the authoritative test matrix

---

## Acceptance Criteria

- [ ] All 13 new Zai tests pass; names match spec §4 verbatim
- [ ] `test_grok_client_factory_forwards_model_args` passes (regression)
- [ ] `test_server_zai_agent_startup` + `test_server_invalid_agent_lists_zai` pass
- [ ] Full dev_loop suite green:
      `pytest packages/ai-parrot/tests/flows/dev_loop/ -v`
- [ ] No test performs real network I/O (grep for `api.z.ai` in test file → only in comments, if at all)
- [ ] No linting errors: `ruff check packages/ai-parrot/tests/flows/dev_loop/`

---

## Test Specification

> This task IS the test specification — the spec §4 tables are authoritative.
> Minimal scaffold for the core Z.ai-native assertion:

```python
# packages/ai-parrot/tests/flows/dev_loop/test_zai_code_dispatcher.py
import pytest
from parrot.flows.dev_loop.dispatcher import ZaiCodeDispatcher
from parrot.flows.dev_loop.models import ZaiCodeDispatchProfile


def _make_dispatcher() -> ZaiCodeDispatcher:
    return ZaiCodeDispatcher(
        max_concurrent=1,
        redis_url="redis://localhost:6379/0",
        stream_ttl_seconds=60,
    )


def test_zai_completion_args_native_thinking():
    disp = _make_dispatcher()
    args = disp._completion_args(ZaiCodeDispatchProfile(), tools=[])
    assert args["thinking"] == {"type": "enabled"}
    assert args["reasoning_effort"] == "max"
    assert args["max_tokens"] == 8192
    assert "extra_body" not in args


def test_zai_completion_args_thinking_disabled():
    disp = _make_dispatcher()
    profile = ZaiCodeDispatchProfile(enable_thinking=False)
    args = disp._completion_args(profile, tools=[])
    assert args["thinking"] == {"type": "disabled"}
    assert "extra_body" not in args
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-1692…1695 must all be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Read the FINAL implemented shapes of `ZaiCodeDispatcher` /
     `ZaiCodeDispatchProfile` (they were specified, then built — trust the
     code, and flag mismatches with the spec in the completion note)
   - Read `test_grok_code_dispatcher.py` fully before mirroring it
4. **Update status** in `sdd/tasks/index/zai-client-code.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1696-zai-test-suite.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-03
**Notes**: Created `test_zai_code_dispatcher.py` with all 13 spec §4 tests
(names verbatim), mirroring `test_grok_code_dispatcher.py`'s harness but
adapted to the Zai contract: `_FakeZaiClient._ensure_client()` is an
`AsyncMock` returning a fake SDK object whose `chat.completions.create` is a
plain **synchronous** callable (since `ZaiCodeDispatcher._chat_completion`
wraps it in `asyncio.to_thread`, unlike Grok's async client). Added
`test_grok_client_factory_forwards_model_args` to
`test_grok_code_dispatcher.py` (monkeypatches `LLMFactory.create` and
asserts the fixed lambda forwards `model_args=` without `TypeError`). Added
`test_server_zai_agent_startup` and `test_server_invalid_agent_lists_zai` to
`test_server_repo_wiring.py`, mirroring `test_server_grok_agent_startup`
(a `_MockConfig` stub with `get`/`getint`/`getboolean` plus
`monkeypatch.setenv("ZAI_API_KEY", "test-key")`); `ZaiCodeDispatcher` was
left un-mocked (its `__init__` performs no network I/O) and asserted via
`isinstance` against `server_mod.ZaiCodeDispatcher`. All 16 new/changed
tests pass; full `pytest packages/ai-parrot/tests/flows/dev_loop/ -v` →
321 passed, 5 skipped, and the same 4 pre-existing order-dependent failures
(`test_server_builds_flow_with_repos`, three in `test_webhook.py`) that
reproduce identically on unmodified `dev` — confirmed via a side-by-side
run before touching any code in this feature; unrelated to FEAT-269. No
`api.z.ai` string appears anywhere in the test tree. `ruff check` clean on
all three touched/created files (repo-wide `ruff check` on the whole
`tests/flows/dev_loop/` dir shows 8 pre-existing F401s in unrelated files,
untouched by this feature).

**Deviations from spec**: none
