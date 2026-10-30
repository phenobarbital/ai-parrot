---
kind: brief
slug: sdd-coder-seat-effort
key: sdd-coder-seat-effort
base_branch: dev
source:
  type: text
  ref: sdd-coder-seat-effort
  url: null
jira_issue_key: null
ledger_issue: null
created: '2026-10-27'
---

# Brief: Per-seat reasoning effort for the sdd-coder roster

## Problem

There is no way to set the reasoning effort of an sdd-coder seat from the roster
configuration (`.parrot/mcp-toolkits.yaml` → `sdd-coder.kwargs`). Today effort is
global per backend:

- zai / moonshot / google-compat: env `DEV_LOOP_{ZAI,MOONSHOT,GOOGLE_COMPAT}_REASONING_EFFORT`
  (`agent_builder.py:255`, `:264`, `:288`);
- codex: inherited from the operator's `~/.codex/config.toml` (`model_reasoning_effort`),
  because development dispatches run with `ignore_user_config=False`;
- google_coding: `GoogleCodingDispatchProfile.effort` exists but `build_dispatcher` never sets it;
- nova / grok / claude-code / nvidia / gemini: no effort knob at all.

Two seats on the same backend cannot have different effort, and a complex task cannot get
more effort than a standard one on the same strong seat.

Source (operator request, verbatim intent): "agregar effort a RosterSeat y que se pueda definir
en strong_models el nivel de effort", configurable in `.parrot/mcp-toolkits.yaml`.

## Root cause

`RosterSeat` (`packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py:155`) carries only
`label/kind/backend/model/fallback_model`, and `SddCoderEngine._run_attempt` builds each attempt's
profile from `DevAgentSpec(agent=seat.backend, model=seat.model)` alone
(`packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py:3539-3540`), so no seat-level
setting can reach the dispatcher. `StrongModelIdentity` (`sdd_coder/complexity_models.py:80`) has
`extra="forbid"`, so an `effort:` key in `complexity.strong_models` crashes toolkit start-up, while
`RosterSeat` has no `extra="forbid"` and silently drops an `effort:` key — it looks configured and
does nothing. The codex command builder (`dispatchers/codex.py:432-480`) has no effort override.

## Research findings

- Profile build site: `engine.py:3545`
  `profile = profile.model_copy(update={"subagent": "sdd-coder"})`, followed by
  `_profile_with_runner_binaries` (`engine.py:1376`) and `_profile_with_scaled_turns`.
  **`model_copy(update=...)` does NOT validate in Pydantic v2** — an out-of-range effort would be
  written straight into the profile. Values must be checked against the target field explicitly.
- The complexity assessment for the task is already resolved a few lines above
  (`engine.py:3514-3524`, `assessment.classification in ("complex", "unknown")` and the
  `(seat.backend, seat.model)` strong-key match), so the strong-model override can reuse it.
- Accepted values per profile field:
  - `ZaiCodeDispatchProfile.reasoning_effort`: `Literal["max","xhigh","high","medium","low","minimal","none"]` (`models/zai.py:31`)
  - `MoonshotCodeDispatchProfile.reasoning_effort`: free `str` (`models/moonshot.py:34`)
  - `GoogleCompatCodeDispatchProfile.reasoning_effort`: `Literal["none","low","medium","high"]` (`models/google_compat.py:20`)
  - `GoogleCodingDispatchProfile.effort`: `Optional[Literal["low","medium","high"]]` (`models/google_coding.py`)
  - `CodexCodeDispatchProfile`: no effort field (`models/codex.py:10`) — to be added.
- Codex already passes config overrides with `-c` (`dispatchers/codex.py:463-464`,
  `approval_policy=...`), so `-c model_reasoning_effort=<x>` follows the same pattern.
- `policy_sha256 = _canonical_hash(policy)` (`sdd_coder/complexity_collectors.py:94`) hashes the
  whole `ComplexityPolicy`; adding a field to `StrongModelIdentity` changes the hash and invalidates
  previously cached complexity evidence once. Acceptable; document it.
- Blast radius (`wikitoolkit symbols blast RosterSeat|StrongModelIdentity`): tests only
  (`test_roster.py`, `test_models.py`, `test_complexity_routing.py`, `test_execution_pool_integration.py`,
  engine tests). Adding an Optional field with default `None` is backward compatible.
- Ledger context for the touched files: no open issue overlaps this change.
- Test fakes in `test_engine_dispatch.py:75` always return `LLMCodeDispatchProfile`, so the
  backend mapping must live in a pure helper module that can be unit-tested with the real
  profile classes, not only through the engine.

## Assumptions

Decided with the operator in conversation (no further Q&A round needed):

1. **Vocabulary**: `effort: Optional[Literal["none","minimal","low","medium","high","xhigh","max"]] = None`
   on both `RosterSeat` and `StrongModelIdentity`. A typo fails at start-up (Pydantic); a value
   valid globally but not accepted by the seat's backend logs a WARNING and is skipped.
2. **Precedence** for one attempt on seat `S` running task `T`:
   1. `strong_models[i].effort` where `(i.backend, i.model) == (S.backend, S.model)`, **only if**
      `T` is classified `complex` or `unknown`;
   2. else `S.effort`;
   3. else unchanged current behaviour (env defaults / `~/.codex/config.toml`).
3. **Backend mapping**: zai / moonshot / google-compat → `reasoning_effort`; google_coding → `effort`;
   codex → new `CodexCodeDispatchProfile.reasoning_effort` emitted as `-c model_reasoning_effort=<x>`
   (accepted: `minimal|low|medium|high|xhigh`); nova / grok / claude-code / nvidia / gemini →
   unsupported: WARNING, ignored. Never silently dropped.
4. **Native seats** (`kind: native` — haiku/sonnet/opus via the sdd-worker `Agent` tool) are OUT OF
   SCOPE. A native seat with `effort` set logs a WARNING that it is not applied yet. Tracked as a
   separate ledger issue.
5. `.parrot/mcp-toolkits.yaml` is git-ignored operator config: not edited by these tasks; the
   operator updates it after merge. Only the shipped template and the example are updated.

## Fix plan

- **HOTFIX-sdd-coder-seat-effort-1** — schema + codex: `effort` on `RosterSeat` (with native-seat
  warning) and `StrongModelIdentity`; `reasoning_effort` on `CodexCodeDispatchProfile`; emit
  `-c model_reasoning_effort=<x>` in `CodexCodeDispatcher._build_command` when set.
- **HOTFIX-sdd-coder-seat-effort-2** — resolution + wiring: new pure module
  `sdd_coder/effort.py` (`resolve_seat_effort`, `apply_effort_to_profile`), called from
  `_run_attempt` right after the `subagent` copy; update `mcp/_toolkit_templates/sdd-coder.yaml` and
  `examples/sdd-coder-mcp.yaml` with commented examples. Depends on task 1.

## Validation commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_models.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_codex_command_variants.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_effort.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_dispatch.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_roster.py -q`
