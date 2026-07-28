# TASK-1971: Bootstrap multi-backend dispatcher + backend-aware preflight

**Feature**: FEAT-388 — `parrot devloop` CLI Homologation
**Spec**: `sdd/specs/devloop-cli-homologation.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1968
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4 (goal G6). The CLI bootstrap hardcodes
`ClaudeCodeDispatcher` (`bootstrap.py:164`) and its preflight hard-fails
without the `claude` binary — so `DEV_LOOP_DEVELOPMENT_AGENT=codex` (which
the web server honors) is impossible from the CLI. Route the default
development dispatcher through `agent_builder.build_dispatcher` and make
preflight check the *selected* backend's requirements.

---

## Scope

- In `build_runtime()`: resolve the default backend from
  `DEV_LOOP_DEVELOPMENT_AGENT` (fallback `"claude-code"`), build
  `DevAgentSpec(agent=<backend>, model=<DEV_LOOP_*_MODEL if set>)`, and call
  `agent_builder.build_dispatcher(spec)` instead of constructing
  `ClaudeCodeDispatcher` directly. Preserve the existing
  `max_concurrent` / `redis_url` / `stream_ttl_seconds` wiring.
- In `preflight()`: make the `claude-cli` check conditional — hard-fail only
  when the resolved backend is `claude-code`; for other backends check their
  own binary or API-key requirement using the catalog's `BackendInfo`
  metadata. Redis + worktree-base checks unchanged.
- Soft (non-fatal) preflight hint when `DEV_LOOP_INTAKE_LLM`'s provider has
  no credentials configured (intake is optional; `--brief` runs don't need
  it).
- Unit tests.

**NOT in scope**: per-run pool dispatch (already handled by the flow via
`dev_agents`, FEAT-323); console changes (TASK-1970); the catalog move
(TASK-1968).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/cli/devloop/bootstrap.py` | MODIFY | Dispatcher via build_dispatcher; backend-aware preflight |
| `packages/ai-parrot/tests/cli/devloop/test_bootstrap.py` | MODIFY | Extend existing suite |

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-07-28 on `dev` @ `623f0a6`. `agent_builder.py` carries
> uncommitted Google/agy WIP — re-verify signatures after it lands.

### Verified Imports

```python
from parrot.flows.dev_loop.agent_builder import build_dispatcher  # agent_builder.py:100
from parrot.flows.dev_loop.models import DevAgentSpec             # models.py:388
from parrot.flows.dev_loop import catalog                         # created by TASK-1968
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/cli/devloop/bootstrap.py
class DevLoopRuntime:                                       # :42 (dataclass; field `dispatcher`)
async def preflight(*, console=None) -> PreflightResult:    # :55
async def build_runtime(*, console=None) -> DevLoopRuntime: # :140
dispatcher = ClaudeCodeDispatcher(                          # :164 ← REPLACE
    max_concurrent=conf.config.get("CLAUDE_CODE_MAX_CONCURRENT_DISPATCHES", fallback=3),
    redis_url=redis_url,
    stream_ttl_seconds=conf.config.get("FLOW_STREAM_TTL_SECONDS", fallback=604800),
)

# packages/ai-parrot/src/parrot/flows/dev_loop/agent_builder.py:100
def build_dispatcher(spec) -> Tuple[dispatcher, profile]:
# Returns (DevLoopCodeDispatcher subclass instance, dispatch profile).
# Read its body before use: confirm which constructor kwargs
# (max_concurrent/redis_url/stream_ttl_seconds) it forwards, and thread
# them if it doesn't.

# examples/dev_loop/llm_catalog.py → parrot/flows/dev_loop/catalog.py
class BackendInfo:   # :51 — has `id`, `env` (model env var), `requires`
                     # (human-readable requirement, e.g. "`agy` CLI on $PATH")
def get_backend(backend_id: str) -> Optional[BackendInfo]:  # :183
```

### Does NOT Exist

- ~~`BackendInfo.binary` / `BackendInfo.api_key_env`~~ *(unverified — check
  the dataclass fields before use; if only the human-readable `requires`
  exists, derive the binary name from the backend id for CLI-backends
  claude-code/codex/gemini/agy and treat the rest as API-key backends)*.
- ~~`DevLoopRuntime.dispatchers` (plural)~~ — the runtime holds ONE default
  `dispatcher`; per-run pools come from the brief's `dev_agents`.
- `flow = build_dev_loop_flow(dispatcher=...)` (`bootstrap.py:~193`) expects
  the same dispatcher object — pass the one from `build_dispatcher`.

---

## Implementation Notes

### Key Constraints
- `DEV_LOOP_DEVELOPMENT_AGENT` read via
  `conf.config.get("DEV_LOOP_DEVELOPMENT_AGENT", fallback="claude-code")` —
  same key the web server honors (homologation).
- Unknown backend value → preflight FAIL check with a hint listing catalog
  ids (do not raise).
- Preflight stays "never raises — returns PreflightResult" (`bootstrap.py:55`
  docstring contract).
- Keep heavy imports deferred into function bodies (`# noqa: PLC0415`).

### References in Codebase
- `examples/dev_loop/server.py` — `DEV_LOOP_DEVELOPMENT_AGENT` if/elif env
  contract this replaces on the CLI side.
- `packages/ai-parrot/tests/cli/devloop/test_bootstrap.py` — existing
  preflight test patterns (monkeypatched `shutil.which`, conf).

---

## Acceptance Criteria

- [ ] `DEV_LOOP_DEVELOPMENT_AGENT=codex` + no `claude` binary → preflight
      passes (codex requirements present) and runtime dispatcher is the
      Codex dispatcher (G6).
- [ ] Unset env → claude-code default, behavior identical to today.
- [ ] Unknown backend → preflight FAIL with catalog ids in the hint.
- [ ] `pytest packages/ai-parrot/tests/cli/devloop/test_bootstrap.py -v`
      passes.
- [ ] `ruff check` clean.

---

## Test Specification

```python
# extend packages/ai-parrot/tests/cli/devloop/test_bootstrap.py
async def test_default_backend_is_claude_code(monkeypatch): ...
async def test_codex_backend_skips_claude_check(monkeypatch): ...
async def test_unknown_backend_fails_preflight_with_hint(monkeypatch): ...
async def test_build_runtime_uses_build_dispatcher(monkeypatch): ...
async def test_intake_llm_hint_is_soft(monkeypatch): ...
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-1968 in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — especially `build_dispatcher`'s body
   and `BackendInfo`'s real fields
4. **Update status** in `sdd/tasks/index/devloop-cli-homologation.json`
5. **Implement**, **verify**, **move this file** to `sdd/tasks/completed/`,
   **update index**, **fill the Completion Note**

---

## Completion Note

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-07-28
**Notes**: Verified `BackendInfo` (catalog.py, TASK-1968) has no
structured `binary`/`api_key_env` field, only `transport` ("cli"/"api")
+ human-readable `requires` — as the Contract's "Does NOT Exist"
anticipated. `build_runtime()` now resolves `DEV_LOOP_DEVELOPMENT_AGENT`
(fallback `claude-code`) into a bare `DevAgentSpec(agent=backend_id)`
(no manual model pre-resolution — `agent_builder.build_dispatcher`
already resolves the per-backend `DEV_LOOP_*_MODEL` env var internally,
exactly mirroring `examples/dev_loop/server.py`'s own
`build_dispatcher(DevAgentSpec(agent=backend), ...)` call, avoiding
duplicated logic) and calls `build_dispatcher(spec, redis_url=...,
max_concurrent=..., stream_ttl_seconds=...)` in place of the hardcoded
`ClaudeCodeDispatcher(...)`. **Important correctness finding**: verified
`DevelopmentNode.execute()` falls back to `ClaudeCodeDispatchProfile`
whenever `dispatch_profile` is `None` — so `build_dev_loop_flow(...)`
now explicitly receives `development_profile=<profile from
build_dispatcher>` (confirmed via `server.py`'s identical pattern),
otherwise a non-claude-code backend would get the wrong profile type
paired with its dispatcher.

`preflight()`'s old unconditional `claude-cli` check is replaced by a
backend-aware one: hard-fails only when the resolved backend is
`claude-code` (byte-identical check name `"claude-cli"` + hint text, to
keep `test_preflight_missing_claude_cli` passing unmodified); other
CLI-transport backends check their own binary (`_cli_binary_for()`
maps `claude-code`→`claude`, `google_coding`→`agy`, else id==binary);
API-transport backends (nvidia/grok/zai/moonshot) get a soft,
always-`passed=True` check surfacing `BackendInfo.requires` as a hint
(no fabricated env-var names for backends whose exact credential key
isn't verified anywhere in-repo — only `anthropic:ANTHROPIC_API_KEY`,
explicitly named in the spec's Known Risks, is used for the analogous
intake-LLM soft-credentials hint). Unknown backend → new
`"dev-agent-backend"` check, `passed=False`, hint lists every
`catalog.BACKENDS` id — preflight still never raises.

Hit and fixed one recursion bug while writing the new backend-mocking
tests: `patch.object(real_conf.config, "get", side_effect=fake_get)`
where `fake_get`'s fallback branch called `real_conf.config.get(...)`
recurses infinitely once `.get` is already patched — fixed by capturing
`original_get = real_conf.config.get` before patching and calling that
in the fallback branch, in all 4 new tests that needed it.

`pytest packages/ai-parrot/tests/cli/devloop/test_bootstrap.py -v` →
13/13 passed (7 pre-existing unmodified + 6 new); full
`packages/ai-parrot/tests/cli/` → 129 passed, zero regressions. Did not
run a blanket `ruff --fix` on `bootstrap.py` this time (lesson from
TASK-1970) — manually verified the diff touches only the two edited
blocks (preflight's backend-aware check + `build_runtime`'s dispatcher
construction), leaving every untouched line/method byte-identical.

**Out-of-scope risk flagged, not fixed** (per "NOT in scope: per-run
pool dispatch"): `DevLoopRunner(..., codereview_dispatcher=None, ...)`
is unchanged, and `QANode`'s docstring says a `None` codereview
dispatcher "auto-wraps `dispatcher` in a `ClaudeCodeReviewDispatcher`
(backward compat)" — worth confirming in a follow-up that this auto-wrap
behaves sanely when the resolved default `dispatcher` is now a
non-claude-code backend (e.g. Codex/Gemini), since this task did not
touch QA-time codereview dispatcher resolution.

**Deviations from spec**: none in behavior. `development_profile` wiring
into `build_dev_loop_flow` was not explicitly spelled out in this
task's Scope bullet list, but was necessary for correctness (see
`DevelopmentNode`'s profile-type fallback above) and mirrors
`server.py`'s own established pattern exactly.
